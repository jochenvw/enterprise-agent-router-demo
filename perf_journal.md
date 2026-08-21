# Performance Journal

Tracks every latency experiment run against the live Azure deployment (`agent-router-dev-rg`,
eastus): what we changed, how we measured it, what happened, and what we decided.

Methodology: measurements come from `scripts/try-orchestrator.ps1` (single query, fresh process)
and `scripts/demo-queries.ps1` (10 Falcon-themed queries), both printing a `[Performance]` block
with `Overall / AI Search / Reasoning / A2A` time and reasoning-only token counts. Numbers are
single-run wall-clock samples against real Azure resources (AI Search, Azure OpenAI, Container
Apps) — treat them as directional, not lab-grade benchmarks.

---

## Experiment 1 — Baseline: GPT reasoning always on

**Hypothesis:** Let GPT-5.4-nano re-rank every query for maximum decision quality.

**Change:** `orchestrator/cli.py` called `reason_over_candidates()` unconditionally for every
routed query.

**Measured:** ~40–50 seconds per query.

**Root cause found:** Not model latency — Azure OpenAI's own `service_ttlt_ms` was ~400–1000ms.
It was a **capacity/quota mix-up** in `infra/modules/foundry.bicep`: the embedding deployment was
accidentally given `capacity: 10` and the reasoning deployment `capacity: 1`, so the reasoning
deployment (used on every single query) throttled hard.

**Decision:** Fix capacity allocation (Experiment 2), then reconsider whether reasoning should run
on every query at all (Experiment 3).

---

## Experiment 2 — Fix deployment capacity + compact reasoning prompt

**Change:**
- `infra/modules/foundry.bicep`: swapped capacities — embedding `capacity: 1`, `gpt-5.4-nano`
  reasoning `capacity: 10`.
- `orchestrator/reasoning.py`: shrank the prompt (dropped full description/examples, capped
  `max_completion_tokens=100`), added `max_retries=0` and `timeout=10.0` so failures surface fast
  instead of silently retrying.

**Measured:** Successful reasoning calls dropped to **~3–4 seconds** each, but a batch of 10
sequential forced-reasoning calls still intermittently hit **HTTP 429** under load — reasoning
capacity contention, not something a single client can avoid.

**Decision:** GPT-5.4-nano reasoning is valuable but too slow/unreliable to sit on the critical
path of every query. Keep it, but stop calling it by default (Experiment 3).

---

## Experiment 3 — Confidence-gated fast path (reasoning becomes opt-in)

**Hypothesis:** Azure AI Search's hybrid score + the ownership/boundary rerank
(`_ownership_rerank` in `registry/store.py`) is already decisive for the demo's query set. GPT
reasoning should be a demonstrable *option*, not a default hop on every request.

**Change:** `orchestrator/cli.py` only calls `reason_over_candidates()` when `--force-reasoning`
is passed or `FORCE_REASONING=1` is set. Otherwise a `ReasoningResult` stub is built directly from
the router's own decision (`elapsed_ms=0`, `input_tokens=0`, `output_tokens=0`).

**Measured (single-query CLI, fresh process each time):**

| Query type | Overall | AI Search | Reasoning | A2A |
|---|---|---|---|---|
| Delegated | ~1.9–2.4 s | ~1.2–1.5 s | 0 ms | ~0.7–1.0 s |
| Clarification | ~1.3–1.5 s | ~1.3–1.5 s | 0 ms | 0 ms |

**Decision:** Kept. This is the default. Reasoning stays fully wired and demonstrable via
`--force-reasoning`, but no longer taxes every query.

**Also fixed alongside this:** `reasoned_candidate` overwrite bug (skipped-reasoning stub was
clobbering the router's own clarification text — guarded with
`if should_reason and decision.candidates`), and an investment-planning routing miss (added
"budget", "approved" to its `owns` vocabulary in `card.yaml`).

---

## Experiment 4 — Find the real bottleneck: per-process cold start

**Observation:** Even in the fast path, single-query runs showed a large, unexplained
**"Uninstrumented overhead"** — in one baseline run, `Overall: 1896 ms` but the actual wall clock
was closer to `4716 ms` (overhead = 2820 ms). That gap lives *before* `search_start` is set: it's
`create_embedder()` — building the `AzureOpenAI` client and, at the time, probing the embedding
dimension with a throwaway API call.

**Isolated with a standalone timing script** (`DefaultAzureCredential` → token → client → probe
call):

| Step | Time |
|---|---|
| `import azure.identity` | 448 ms |
| `DefaultAzureCredential()` construction | 131 ms |
| First `get_bearer_token_provider(...)()` (token acquisition) | **1229 ms** |
| `AzureOpenAI(...)` client init | 838 ms |
| Dimension-probe `embeddings.create()` call (discarded result) | **1113 ms** |

That's **~3.6 s of fixed cold-start cost paid by every fresh CLI process**, before the first real
embedding call for the user's query even starts.

**Sub-experiment: does a persistent MSAL token cache help?** Tried
`DefaultAzureCredential(token_cache_persistence_options=TokenCachePersistenceOptions(...))` across
two separate process invocations. Token acquisition stayed ~1.3–1.4 s both times — the
`DefaultAzureCredential` chain still walks through Environment/ManagedIdentity/CLI credential
probing before it can even consult a persisted cache, and `AzureCliCredential` itself shells out to
`az` as a subprocess (~1.2 s) with no observed savings on repeat. **Conclusion: not worth pursuing
further for this demo — the win has to come from not re-paying this cost per query, not from
speeding up any single credential path.**

**Decision:** Two concrete fixes, both applied:

1. **Remove the dimension probe** (Experiment 5).
2. **Add a batch mode** so a whole demo run pays the cold-start cost once, not once per query
   (Experiment 6) — this is the change that actually matters for the "10 similar queries" demo.

---

## Experiment 5 — Remove the embedding dimension probe

**Change:** `registry/embeddings.py` — added `KNOWN_EMBEDDING_DIMENSIONS` (a small lookup for
`text-embedding-3-small` → 1536, `text-embedding-3-large` → 3072, `text-embedding-ada-002` → 1536).
`AzureOpenAIEmbedder.__init__` now uses the known value directly and only falls back to a live
probe call for an unrecognized deployment name.

**Measured:** Saves ~1.1 s of real network work per process (the wasted probe call). In a
single-process run this doesn't show up as a smaller "Overall" number, because the time just
shifts into whichever phase makes the *first* real network call (usually AI Search's embed step) —
but the total wall-clock time across two otherwise-identical runs dropped from ~4.7 s to ~4.4 s.
The bigger win from removing wasted work shows up clearly once cold-start is amortized (Experiment
6), since the probe would otherwise repeat needlessly if ever called per-query.

**Decision:** Kept — strictly removes wasted work with no behavior change (verified against the
router eval suite: still 11/11, wrong-delegation rate 0.0).

---

## Experiment 6 — Batch mode: amortize cold start across queries

**Hypothesis:** The 10-query demo (`scripts/demo-queries.ps1`) was spawning **10 separate
`uv run route-query` processes**, so every single query paid the full ~2–3.5 s cold-start tax
(credential + Azure OpenAI client init) independently. A single warm process should only pay it
once.

**Change:**
- `orchestrator/cli.py`: split `run()` into `run()` (single query, builds its own embedder/router)
  and `run_query(router, ...)` (reusable per-query logic), plus a new `run_batch(queries, ...)`
  that builds the embedder/router **once** and loops `run_query` over every line.
- Added `route-query-batch` console script (`orchestrator.cli:main_batch`) in `pyproject.toml`,
  reading one query per line from a text file.
- `scripts/falcon-queries.txt` — the same 10 Falcon queries, one per line.
- `scripts/demo-queries.ps1` rewritten to call `route-query-batch` once instead of
  `try-orchestrator.ps1` in a loop.

**Measured (10-query batch, `--delegate`, fast path):**

| Query # | Overall | AI Search | A2A | Notes |
|---|---|---|---|---|
| 1 (cold) | 3571 ms | 3571 ms | 0 ms | clarification — pays full cold start (credential + client init) |
| 2 | 1273 ms | 285 ms | 988 ms | warm |
| 3 | 1167 ms | 310 ms | 857 ms | warm |
| 4 | 1277 ms | 387 ms | 890 ms | warm |
| 5 | 1450 ms | 489 ms | 961 ms | warm |
| 6 (clarify) | 431 ms | 431 ms | 0 ms | warm, no A2A |
| 7 | 1442 ms | 433 ms | 1008 ms | warm |
| 8 | 1099 ms | 346 ms | 752 ms | warm |
| 9 | 1159 ms | 258 ms | 901 ms | warm |
| 10 | 1092 ms | 295 ms | 797 ms | warm |

Steady-state (queries 2–10, excluding the one-time cold start): **AI Search ~260–490 ms**, well
under the earlier ~1.1–1.5 s single-process figure, because the Azure AD token and Azure OpenAI
client are already warm. A2A settles at **~750–1000 ms** and is now the dominant cost per query.

**Decision:** Kept. This is the single biggest lever found in this round — it doesn't change
per-query cost, but it changes the *demo's* perceived cost from "10 × ~2.5 s = 25 s" to
"~3.6 s + 9 × ~1.2 s ≈ 14.5 s", and better reflects a realistic architecture where the
orchestrator is a long-running service, not a fresh CLI process per request.
Single-query usage (`try-orchestrator.ps1`) is unaffected/unchanged — it still pays the full cold
start, which is appropriate for a one-off CLI invocation.

---

## Experiment 7 — Narrow the AI Search `select` fields

**Hypothesis:** Each hybrid search call returns the full `embedding` vector (1536 floats) for
every one of the `top=3` candidates, even though the code immediately discards it
(`payload["embedding"] = []`). Excluding it from the response should cut serialization/transfer
time.

**Change:** `registry/store.py` — added an explicit `select=[...]` list to
`AzureSearchCapabilityStore.search()` that includes every field except `embedding`.

**Measured:** No measurable difference in steady-state AI Search time (~260–470 ms before and
after, within run-to-run noise). At `top=3` candidates the embedding payload (~37 KB total) is too
small relative to network/query overhead to matter.

**Decision:** Kept anyway (harmless, slightly smaller payload, clearer intent that the vector
isn't needed post-search) but **not** counted as a real perf win — noted here so we don't
re-attempt it later expecting a different result.

---

## Experiment 8 — Verify the cached Agent Card optimization (`_card_from_document`)

**Background:** `orchestrator/delegation.py` parses the Agent Card JSON already stored in the
search index (`_card_from_document`, via `google.protobuf.json_format.Parse(..., AgentCard())`)
instead of doing a live HTTP fetch to `/.well-known/agent-card.json` before delegating. This was
flagged as unverified in an earlier session.

**Verification:** Confirmed `a2a.types.AgentCard` is a real protobuf-generated message
(`a2a_pb2.AgentCard`, subclass of `google.protobuf.message.Message`), so `Parse()` is a valid,
working code path — not silently failing into the HTTP fallback. Verbose delegation traces never
print the `"[A2A] Falling back to live Agent Card fetch"` line in any of the runs in this journal,
confirming the cached-card path is the one actually being exercised.

**Decision:** Confirmed working, no change needed. This shaves one HTTP round trip
(`GET /.well-known/agent-card.json`) off every delegated query — folded into the current
~750–1000 ms warm A2A time rather than measured in isolation.

---

## Current state (after Experiments 1–8)

Fast path (default, no `--force-reasoning`), warm process (batch mode):

- **AI Search:** ~260–490 ms
- **Reasoning:** 0 ms / 0 tokens (opt-in only)
- **A2A:** ~750–1000 ms
- **Overall (steady state):** ~1.0–1.5 s per delegated query, ~0.3–0.5 s per clarification

Cold path (first query in a process, or any single `try-orchestrator.ps1` invocation): add
~2–3.5 s of one-time Azure AD credential + Azure OpenAI client init.

Router eval suite (`uv run eval-router`) after all changes: **top-1-or-clarification accuracy
1.0, wrong-delegation rate 0.0, clarification precision/recall 1.0** — no regressions from any
performance change.

## Ideas not yet tried / deferred

- **A2A connection reuse across queries.** `delegate()`/`delegate_verbose()` construct a new
  `A2AAgent` (and likely a new underlying HTTP client) per call. In batch mode this means every
  one of the 10 queries pays its own TLS handshake to the Container Apps endpoint. Sharing one
  `httpx.AsyncClient`/`A2AAgent` per target agent across the batch could cut the ~750–1000 ms A2A
  figure further, but requires restructuring `delegate_verbose()`'s call signature — deferred to
  avoid risking the working demo path.
- **Container Apps scale-to-zero / cold instances.** A2A time was consistently ~750–1000 ms across
  all 10 queries (not just the first), suggesting replicas are already warm; not investigated
  further but worth double-checking `minReplicas` in `infra/deploy-agents.ps1` if A2A time ever
  spikes on the first call specifically.
- **Azure AI Search semantic ranker / different `queryType`.** Not attempted — current hybrid
  (lexical + vector) search is already well under 500 ms warm, so there's no evidence a semantic
  reranker would help latency (it would likely add cost/latency, not remove it).
- **Alternate reasoning models for the opt-in path** (gpt-5-nano, gpt-5.1 variants) — not
  benchmarked against gpt-5.4-nano since reasoning is no longer on the default path; only worth
  doing if a future demo wants a faster *default* reasoning-backed router.

---

## Experiment 9 — Fast path vs. forced reasoning, head-to-head

**Question:** what does GPT-5.4-nano reasoning actually cost vs. the default rule-based fast path,
and does it change any outcomes? Ran the same 10-query batch twice: once default (fast path) and
once with `--force-reasoning`.

**Important framing:** the fast path is **not agentic** — it is deterministic re-ranking (AI
Search hybrid score + string-membership ownership/boundary checks in
`_ownership_rerank`), not an LLM judging the candidates. It works here because the Agent Cards
were deliberately authored with sharp `owns`/`does_not_own` vocabulary for this query set — that's
a property of this demo's card design, not a general guarantee. `--force-reasoning` is the actual
agentic path: an LLM call that reasons over the same candidates.

| Metric (warm, steady-state avg across queries 2–10) | Without reasoning | With `--force-reasoning` |
|---|---|---|
| Overall time | **~0.94 s** | **~4.6 s** |
| AI Search time | ~324 ms | ~357 ms |
| Reasoning time | 0 ms | ~3.57 s |
| A2A time | ~615 ms | ~701 ms |
| Tokens per query | **0** | **~484** |
| Router eval accuracy / wrong-delegation rate | 1.0 / 0.0 | 1.0 / 0.0 |

**Outcome check:** across the 10 queries, forced reasoning changed exactly one decision — "What's
the status of Falcon?" went from a clarification (fast path, correctly conservative given generic
phrasing) to a confident pick of `capital-projects` (reasoning). Every other query selected the
same agent both ways.

**Decision:** confirms Experiment 3's choice. Reasoning is ~5x slower and costs real tokens for a
query set where card design already disambiguates almost everything; it earns its cost only on
genuinely ambiguous phrasing. Keep it opt-in, and use this table as the demo's honest answer to
"is this actually agentic or just retrieval?" — by default, it's retrieval + rules; reasoning is
the escalation path, verified here to behave sensibly when invoked.
