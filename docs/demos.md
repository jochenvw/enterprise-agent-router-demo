# Demo Scenarios

Concrete commands to run against the live Azure deployment, showing the router's
capability discovery, ambiguity handling, and (for multi-hop) genuine reasoning.

Prerequisite: Azure infra deployed and agents indexed (see
[`docs/infra-deployment.md`](infra-deployment.md)).

## 1. Single-hop routing (deterministic fast path)

Straightforward, single-fact questions. The router retrieves candidates from Azure
AI Search (hybrid lexical + vector), applies a deterministic ownership rerank, and
delegates via A2A to the winning agent — no LLM judgment required.

```powershell
.\scripts\try-orchestrator.ps1 -Query "What is the EAC for Falcon?"
.\scripts\try-orchestrator.ps1 -Query "What's the latest price for Falcon's compressor?"
.\scripts\try-orchestrator.ps1 -Query "Why has the project cost gone up?"
```

Each shows: full ranked candidate list with scores → selected agent → A2A request/response
→ performance summary (overall / AI Search / reasoning / A2A time, tokens).

## 2. Deliberate ambiguity (clarification path)

Agent Cards were authored with overlapping enterprise vocabulary on purpose, so some
queries are genuinely ambiguous across agents. The router asks for clarification
instead of guessing.

```powershell
.\scripts\try-orchestrator.ps1 -Query "What's the status of the project?"
.\scripts\try-orchestrator.ps1 -Query "Compare the Falcon compressor price with the Falcon estimate at completion."
```

The second one is a good "trap" query: "estimate at completion" legitimately overlaps
Project Controls (EAC) and Capital Projects (mechanical completion) — clarification here
is correct behavior, not a bug.

## 3. Forced reasoning path (opt-in)

Bypasses the deterministic rerank and has an LLM (GPT-5.4-nano) judge candidates directly —
useful to show the more expensive, fully agentic alternative and its latency/cost tradeoff.

```powershell
.\scripts\try-orchestrator.ps1 -Query "What is the EAC for Falcon?" -ForceReasoning
```

Compare its `[Reasoning tokens]` and timing against the default fast path for the same query.

## 4. Multi-hop contrast/compare (genuinely agentic)

Compound queries that require pulling one fact from one agent and a different fact from
another agent, then synthesizing a combined answer. This is the one case where an LLM is
required end-to-end: to decompose the query into independent sub-questions, and to
synthesize the two independent answers into one coherent response.

```powershell
.\scripts\try-orchestrator.ps1 -Query "Contrast the Falcon compressor price with Falcon's cost variance."
.\scripts\try-orchestrator.ps1 -Query "Compare Falcon's funding approval with its cost variance."
.\scripts\try-orchestrator.ps1 -Query "Contrast Falcon's cost variance with its funding approval."
```

Output shows: `[Decompose]` (query split into 2 sub-questions) → per-hop `[Hop]`/`[A2A]` trace
against two different specialist agents → `[Synthesize]` (combined answer) → performance
summary. Typical cost: ~13s overall, ~450-670 reasoning tokens.

## 5. Batch/regression run

Fires a fixed set of similarly-phrased queries and shows how they route to different agents,
useful for demonstrating the router isn't just keyword-matching a single obvious term.

```powershell
.\scripts\demo-queries.ps1
```

## 6. Full evaluation suite

Regression check across all labeled single-hop cases (expects agent selection or a correct
clarification).

```powershell
uv run eval-router
```

Expected: `top_1_or_clarification_accuracy: 1.0`, `wrong_delegation_rate: 0.0`.

## Related docs

- [`docs/infra-deployment.md`](infra-deployment.md) — deployment and cleanup
- [`docs/performance.md`](performance.md) — performance repro and headline numbers
- [`docs/perf-journal.md`](perf-journal.md) — full experiment log
