"""Multi-hop query handling: decompose a compound query ("contrast X with Y") into
independent sub-queries, route + delegate each one separately, then synthesize a single
combined answer.

Unlike single-hop routing (see router.py / _ownership_rerank), this genuinely requires an
LLM: deciding how to split a compound question, and turning two independent agent answers
into one coherent contrast/comparison, is language understanding and generation — not
something a lexical/vector score + string-membership rule can do. See docs/perf-journal.md,
Experiment 10, for measurements and the reasoning-vs-fast-path framing this builds on.
"""

import json
import os
import time
from dataclasses import dataclass, field

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

# Heuristic trigger for compound queries. This part is intentionally NOT an LLM call: cheaply
# detecting "this looks like it needs decomposition" is fine as a keyword check, so the
# (slower, token-costing) LLM call only fires when it is actually likely to be needed.
MULTI_HOP_TRIGGERS = (
    "contrast",
    "compare",
    "versus",
    " vs ",
    " vs. ",
    "compared to",
    "relative to",
    "against the",
)


def looks_multi_hop(query: str) -> bool:
    normalized = f" {query.lower()} "
    return any(trigger in normalized for trigger in MULTI_HOP_TRIGGERS)


@dataclass
class SubQueryResult:
    sub_query: str
    agent_id: str | None
    answer: str | None
    clarification: str | None = None


@dataclass
class MultiHopResult:
    sub_queries: list[str]
    results: list[SubQueryResult] = field(default_factory=list)
    combined_answer: str = ""
    decompose_ms: float = 0.0
    synthesize_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _client() -> tuple[AzureOpenAI, str] | None:
    deployment = os.getenv("AZURE_OPENAI_REASONING_DEPLOYMENT")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not deployment or not endpoint:
        return None
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        max_retries=0,
        timeout=10.0,
    )
    return client, deployment


def decompose_query(query: str) -> tuple[list[str], float, int, int]:
    """Split a compound query into independent sub-queries an agent could each answer."""
    setup = _client()
    if setup is None:
        # No reasoning model configured: fall back to treating it as single-hop.
        return [query], 0.0, 0, 0
    client, deployment = setup
    prompt = (
        "Split this question into the minimum number of independent, self-contained "
        "sub-questions needed to answer it, each answerable by a single specialist agent. "
        "Each sub-question must ask for a single fact only (e.g. one figure or one status), "
        "never ask for a comparison, contrast, or relationship between facts — that synthesis "
        "happens later, not in a sub-question. "
        "If it is already a single simple question, return it unchanged as the only item. "
        "Return JSON: {\"sub_queries\": [\"...\", \"...\"]}. "
        f"Question: {query}"
    )
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": "Return only valid JSON. Do not add prose outside JSON."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=150,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    payload = json.loads(response.choices[0].message.content or "{}")
    sub_queries = [str(item) for item in payload.get("sub_queries", []) if str(item).strip()]
    usage = response.usage
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    return (sub_queries or [query]), elapsed_ms, input_tokens, output_tokens


def synthesize_answer(query: str, results: list[SubQueryResult]) -> tuple[str, float, int, int]:
    """Combine independently-retrieved sub-answers into one coherent response."""
    setup = _client()
    findings = [
        {
            "sub_query": result.sub_query,
            "agent": result.agent_id,
            "answer": result.answer or result.clarification,
        }
        for result in results
    ]
    if setup is None:
        # No reasoning model: best-effort concatenation, clearly not a real synthesis.
        joined = " ".join(f"[{item['agent']}] {item['answer']}" for item in findings)
        return joined, 0.0, 0, 0
    client, deployment = setup
    prompt = (
        "The user asked a compound question that required consulting multiple specialist "
        "agents. Combine their independent answers into one direct, explicitly comparative "
        "response (e.g. state both figures/facts and the relationship between them). Do not "
        "invent facts beyond what is given. "
        f"Original question: {query}. Findings: {json.dumps(findings, ensure_ascii=True)}"
    )
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": "Answer concisely in 2-3 sentences."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=200,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    usage = response.usage
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    text = response.choices[0].message.content or ""
    return text, elapsed_ms, input_tokens, output_tokens
