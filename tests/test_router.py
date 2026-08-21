from pathlib import Path

from orchestrator.router import CapabilityRouter
from registry.embeddings import HashingEmbedder
from registry.models import CapabilityDocument
from registry.store import LocalCapabilityStore


def build_index(path: Path) -> CapabilityRouter:
    embedder = HashingEmbedder()
    documents = [
        CapabilityDocument(
            id="project-controls:cost",
            agent_id="project-controls",
            agent_name="Project Controls Agent",
            skill_id="cost",
            skill_name="Cost performance",
            description="Estimate at completion, baseline, earned value and cost variance.",
            examples=["What is the EAC for Falcon?", "Why is Falcon over budget?"],
            owns=["eac", "estimate at completion", "cost variance"],
            does_not_own=["funding approval"],
            endpoint="http://localhost:8002/a2a",
            base_url="http://localhost:8002",
            agent_card_json="{}",
        ),
        CapabilityDocument(
            id="investment-planning:funding",
            agent_id="investment-planning",
            agent_name="Investment Planning Agent",
            skill_id="funding",
            skill_name="Portfolio funding",
            description="Funding approval, allocation and business cases.",
            examples=["Has funding been approved for Falcon?"],
            owns=["funding", "allocation", "portfolio"],
            does_not_own=["cost variance"],
            endpoint="http://localhost:8004/a2a",
            base_url="http://localhost:8004",
            agent_card_json="{}",
        ),
    ]
    for document in documents:
        document.embedding = embedder.embed(document.searchable_text)
    store = LocalCapabilityStore(path)
    store.replace(documents)
    return CapabilityRouter(store, embedder)


def test_routes_specific_query(tmp_path: Path) -> None:
    decision = build_index(tmp_path / "index.json").route("What is the EAC for Falcon?")
    assert decision.outcome == "delegate"
    assert decision.selected is not None
    assert decision.selected.document.agent_id == "project-controls"


def test_clarifies_generic_status(tmp_path: Path) -> None:
    decision = build_index(tmp_path / "index.json").route("What's the status of Falcon?")
    assert decision.outcome == "clarify"

