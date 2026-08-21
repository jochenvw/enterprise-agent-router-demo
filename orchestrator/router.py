from dataclasses import dataclass

from registry.embeddings import Embedder
from registry.models import CapabilityDocument
from registry.store import CapabilityStore
from shared.telemetry import tracer


@dataclass
class Candidate:
    document: CapabilityDocument
    score: float


@dataclass
class RoutingDecision:
    outcome: str
    selected: Candidate | None
    candidates: list[Candidate]
    clarification: str | None = None


GENERIC_PROJECT_QUERIES = {
    "what's the status of falcon",
    "what is the status of falcon",
    "what's the status of the project",
    "what is the project status",
    "what's the forecast for project falcon",
}


class CapabilityRouter:
    def __init__(self, store: CapabilityStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    def route(self, query: str, top: int = 3) -> RoutingDecision:
        normalized = query.lower().strip().rstrip("?.!")
        with tracer().start_as_current_span("router.search") as span:
            results = self.store.search(query, self.embedder.embed(query), top=top)
            candidates = [Candidate(document=document, score=score) for document, score in results]
            span.set_attribute("agent.candidate.count", len(candidates))

        if not candidates:
            return RoutingDecision("clarify", None, [], "I could not find a relevant specialist.")

        top_candidate = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None
        ambiguous_margin = runner_up is not None and top_candidate.score - runner_up.score < 0.08
        generic = normalized in GENERIC_PROJECT_QUERIES
        low_confidence = top_candidate.score < 0.18

        with tracer().start_as_current_span("router.decision") as span:
            span.set_attribute("agent.selected", top_candidate.document.agent_id)
            span.set_attribute("routing.score", top_candidate.score)
            if generic or ambiguous_margin or low_confidence:
                span.set_attribute("routing.outcome", "clarification")
                span.set_attribute("routing.clarification_required", True)
                names = ", ".join(candidate.document.agent_name for candidate in candidates[:3])
                return RoutingDecision(
                    "clarify",
                    None,
                    candidates,
                    f"Do you mean delivery status, controls/forecast, procurement, funding, or consulting? "
                    f"The leading candidates are: {names}.",
                )
            span.set_attribute("routing.outcome", "delegated")
            span.set_attribute("routing.clarification_required", False)
            return RoutingDecision("delegate", top_candidate, candidates)

