import json
import os
import time
from dataclasses import dataclass

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from orchestrator.router import Candidate


@dataclass
class ReasoningResult:
    selected_agent_id: str | None
    clarification_required: bool
    reason: str
    elapsed_ms: float
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def reason_over_candidates(query: str, candidates: list[Candidate]) -> ReasoningResult:
    deployment = os.getenv("AZURE_OPENAI_REASONING_DEPLOYMENT")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not deployment or not endpoint:
        return ReasoningResult(
            selected_agent_id=candidates[0].document.agent_id if candidates else None,
            clarification_required=False,
            reason="Reasoning model not configured; used top ranked search candidate.",
            elapsed_ms=0.0,
            input_tokens=0,
            output_tokens=0,
        )

    candidate_payload = [
        {
            "agent_id": candidate.document.agent_id,
            "agent_name": candidate.document.agent_name,
            "routing_score": round(candidate.score, 4),
            "owns": candidate.document.owns,
            "not": candidate.document.does_not_own,
            "examples": candidate.document.examples[:3],
        }
        for candidate in candidates
    ]
    prompt = (
        "Route query to one agent, or clarify if ambiguous. Use 'owns' and 'not'. "
        "Return JSON: selected_agent_id, clarification_required, reason. "
        f"Query: {query}. Candidates: {json.dumps(candidate_payload, ensure_ascii=True)}"
    )

    start = time.perf_counter()
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
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {
                "role": "system",
                "content": "Return only valid JSON. Do not add prose outside JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=100,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    content = response.choices[0].message.content or "{}"
    payload = json.loads(content)
    usage = response.usage
    return ReasoningResult(
        selected_agent_id=payload.get("selected_agent_id"),
        clarification_required=bool(payload.get("clarification_required", False)),
        reason=str(payload.get("reason", "")),
        elapsed_ms=elapsed_ms,
        input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
    )
