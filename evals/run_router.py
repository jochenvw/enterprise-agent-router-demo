import json
from pathlib import Path

import yaml

from orchestrator.router import CapabilityRouter
from registry.embeddings import create_embedder
from registry.store import create_store


def main() -> None:
    embedder = create_embedder()
    router = CapabilityRouter(create_store(embedder.dimensions), embedder)
    cases = yaml.safe_load(Path(__file__).with_name("router.yaml").read_text(encoding="utf-8"))
    correct = 0
    wrong_delegations = 0
    clarification_tp = 0
    clarification_fp = 0
    clarification_fn = 0
    details = []

    for case in cases:
        decision = router.route(case["query"])
        expected_clarification = case.get("clarification_required", False)
        actual_clarification = decision.outcome == "clarify"
        selected = decision.selected.document.agent_id if decision.selected else None
        passed = (
            actual_clarification
            if expected_clarification
            else not actual_clarification and selected == case["expected_agent"]
        )
        correct += int(passed)
        wrong_delegations += int(
            not expected_clarification
            and not actual_clarification
            and selected != case["expected_agent"]
        )
        clarification_tp += int(expected_clarification and actual_clarification)
        clarification_fp += int(not expected_clarification and actual_clarification)
        clarification_fn += int(expected_clarification and not actual_clarification)
        details.append(
            {
                "query": case["query"],
                "passed": passed,
                "selected": selected,
                "clarified": actual_clarification,
            }
        )

    precision = clarification_tp / max(clarification_tp + clarification_fp, 1)
    recall = clarification_tp / max(clarification_tp + clarification_fn, 1)
    output = {
        "cases": len(cases),
        "top_1_or_clarification_accuracy": correct / len(cases),
        "wrong_delegation_rate": wrong_delegations / len(cases),
        "clarification_precision": precision,
        "clarification_recall": recall,
        "details": details,
    }
    print(json.dumps(output, indent=2))
    raise SystemExit(0 if correct == len(cases) else 1)


if __name__ == "__main__":
    main()

