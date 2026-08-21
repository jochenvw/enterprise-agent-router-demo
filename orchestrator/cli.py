import argparse
import asyncio
import json
import os
import time

from orchestrator.delegation import delegate, delegate_verbose
from orchestrator.multihop import (
    SubQueryResult,
    decompose_query,
    looks_multi_hop,
    synthesize_answer,
)
from orchestrator.reasoning import ReasoningResult, reason_over_candidates
from orchestrator.router import CapabilityRouter
from registry.embeddings import create_embedder
from registry.store import create_store
from shared.telemetry import configure_telemetry


async def run(query: str, should_delegate: bool, verbose: bool, force_reasoning: bool) -> int:
    embedder = create_embedder()
    router = CapabilityRouter(create_store(embedder.dimensions), embedder)
    return await run_query(router, query, should_delegate, verbose, force_reasoning)


async def run_query(
    router: CapabilityRouter,
    query: str,
    should_delegate: bool,
    verbose: bool,
    force_reasoning: bool,
) -> int:
    if should_delegate and looks_multi_hop(query):
        return await run_multi_hop_query(router, query, verbose)
    return await run_single_hop_query(router, query, should_delegate, verbose, force_reasoning)


async def run_multi_hop_query(router: CapabilityRouter, query: str, verbose: bool) -> int:
    """Decompose a compound query, route + delegate each part independently, then
    synthesize one combined answer. This is the genuinely agentic path: no lexical/vector
    score or ownership rule can split "contrast X with Y" or merge two agents' answers."""
    total_start = time.perf_counter()
    if verbose:
        print("=== Agent Routing Demo (multi-hop) ===")
        print(f"Query: {query}")
        print("\n[Decompose] Query looks compound; asking reasoning model to split it...")
    sub_queries, decompose_ms, decompose_in, decompose_out = decompose_query(query)
    if verbose:
        print(f"[Decompose] Completed in {decompose_ms:.0f} ms -> {len(sub_queries)} sub-queries:")
        for index, sub_query in enumerate(sub_queries, start=1):
            print(f"  {index}. {sub_query}")

    results: list[SubQueryResult] = []
    search_ms_total = 0.0
    a2a_ms_total = 0.0
    for sub_query in sub_queries:
        if verbose:
            print(f"\n[Hop] Routing sub-query: {sub_query}")
        search_start = time.perf_counter()
        decision = router.route(sub_query)
        search_ms_total += (time.perf_counter() - search_start) * 1000
        if decision.selected is None:
            if verbose:
                print(f"[Hop] Clarification required: {decision.clarification}")
            results.append(SubQueryResult(sub_query, None, None, decision.clarification))
            continue
        agent_id = decision.selected.document.agent_id
        if verbose:
            print(f"[Hop] Selected {decision.selected.document.agent_name} ({agent_id})")
        a2a_start = time.perf_counter()
        answer = (
            await delegate_verbose(decision.selected.document, sub_query)
            if verbose
            else await delegate(decision.selected.document, sub_query)
        )
        a2a_ms_total += (time.perf_counter() - a2a_start) * 1000
        results.append(SubQueryResult(sub_query, agent_id, answer))

    if verbose:
        print("\n[Synthesize] Combining sub-answers into one response...")
    combined, synth_ms, synth_in, synth_out = synthesize_answer(query, results)
    reasoning_ms = decompose_ms + synth_ms
    input_tokens = decompose_in + synth_in
    output_tokens = decompose_out + synth_out

    if verbose:
        print(f"[Synthesize] Completed in {synth_ms:.0f} ms")
        print(f"\n[Combined answer] {combined}")

    payload = {
        "outcome": "multi-hop",
        "sub_queries": sub_queries,
        "hops": [
            {
                "sub_query": result.sub_query,
                "agent": result.agent_id,
                "answer": result.answer,
                "clarification": result.clarification,
            }
            for result in results
        ],
        "combined_answer": combined,
    }
    if verbose:
        measured_total_ms = (time.perf_counter() - total_start) * 1000
        accounted_total_ms = search_ms_total + reasoning_ms + a2a_ms_total
        print("\n[Performance]")
        print(f"  Overall time: {accounted_total_ms:.0f} ms")
        print(f"  AI Search time (all hops): {search_ms_total:.0f} ms")
        print(f"  Reasoning time (decompose + synthesize): {reasoning_ms:.0f} ms")
        print(f"  A2A time (all hops): {a2a_ms_total:.0f} ms")
        print(f"  Uninstrumented overhead: {max(0.0, measured_total_ms - accounted_total_ms):.0f} ms")
        print("\n[Reasoning tokens]")
        print(f"  Input tokens: {input_tokens}")
        print(f"  Output tokens: {output_tokens}")
        print(f"  Total tokens: {input_tokens + output_tokens}")
        print("\n[Summary]")
    print(json.dumps(payload, indent=2))
    return 0


async def run_single_hop_query(
    router: CapabilityRouter,
    query: str,
    should_delegate: bool,
    verbose: bool,
    force_reasoning: bool,
) -> int:
    total_start = time.perf_counter()
    if verbose:
        mode = "Azure AI Search" if os.getenv("AZURE_SEARCH_ENDPOINT") else "local JSON index"
        embedding_deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "local hashing")
        print("=== Agent Routing Demo ===")
        print(f"Query: {query}")
        print(f"Capability store: {mode}")
        print(f"Embedding deployment: {embedding_deployment}")
        print("\n[Search] Generating query embedding and running hybrid capability lookup...")
    search_start = time.perf_counter()
    decision = router.route(query)
    search_ms = (time.perf_counter() - search_start) * 1000
    reasoning_start = time.perf_counter()
    should_reason = force_reasoning or os.getenv("FORCE_REASONING") == "1"
    if should_reason:
        reasoning = reason_over_candidates(query, decision.candidates)
    else:
        selected_id = decision.selected.document.agent_id if decision.selected else None
        reasoning = ReasoningResult(
            selected_agent_id=selected_id,
            clarification_required=decision.outcome == "clarify",
            reason="GPT reasoning skipped by confidence gate; AI Search + boundary rerank was decisive.",
            elapsed_ms=0.0,
            input_tokens=0,
            output_tokens=0,
        )
    reasoning_ms = (
        reasoning.elapsed_ms if not should_reason else (time.perf_counter() - reasoning_start) * 1000
    )
    if should_reason and decision.candidates:
        reasoned_candidate = next(
            (
                candidate
                for candidate in decision.candidates
                if candidate.document.agent_id == reasoning.selected_agent_id
            ),
            None,
        )
        if reasoning.clarification_required:
            decision.selected = None
            decision.outcome = "clarify"
            decision.clarification = reasoning.reason or decision.clarification
        elif reasoned_candidate:
            decision.selected = reasoned_candidate
            decision.outcome = "delegate"
            decision.clarification = None
    if verbose:
        print(f"[Search] Completed in {search_ms:.0f} ms")
        print("[Search] Ranked candidate Agent Cards:")
        for index, candidate in enumerate(decision.candidates, start=1):
            document = candidate.document
            raw = (
                f"{document.search_score:.4f}"
                if document.search_score is not None
                else "n/a"
            )
            print(
                f"  {index}. {document.agent_name} ({document.agent_id})\n"
                f"     AI Search score: {raw}; final routing score: {candidate.score:.4f}\n"
                f"     Endpoint: {document.endpoint}\n"
                f"     Owns: {', '.join(document.owns)}\n"
                f"     Confusable boundaries: {', '.join(document.does_not_own)}"
            )
        if decision.selected:
            print(
                f"\n[Decision] Selected {decision.selected.document.agent_name} "
                f"with score {decision.selected.score:.4f}."
            )
            print(f"[Reasoning] {reasoning.reason}")
        else:
            print(f"\n[Decision] Clarification required: {decision.clarification}")
            print(f"[Reasoning] {reasoning.reason}")
    payload = {
        "outcome": decision.outcome,
        "selected_agent": decision.selected.document.agent_id if decision.selected else None,
        "clarification": decision.clarification,
        "candidates": [
            {
                "agent": candidate.document.agent_id,
                "skill": candidate.document.skill_id,
                "score": round(candidate.score, 4),
            }
            for candidate in decision.candidates
        ],
    }
    a2a_ms = 0.0
    if should_delegate and decision.selected:
        a2a_start = time.perf_counter()
        payload["response"] = (
            await delegate_verbose(decision.selected.document, query)
            if verbose
            else await delegate(decision.selected.document, query)
        )
        a2a_ms = (time.perf_counter() - a2a_start) * 1000
    if verbose:
        measured_total_ms = (time.perf_counter() - total_start) * 1000
        accounted_total_ms = search_ms + reasoning_ms + a2a_ms
        print("\n[Performance]")
        print(f"  Overall time: {accounted_total_ms:.0f} ms")
        print(f"  AI Search time: {search_ms:.0f} ms")
        print(f"  Reasoning time: {reasoning_ms:.0f} ms")
        print(f"  A2A time: {a2a_ms:.0f} ms")
        print(f"  Uninstrumented overhead: {max(0.0, measured_total_ms - accounted_total_ms):.0f} ms")
        print("\n[Reasoning tokens]")
        print(f"  Input tokens: {reasoning.input_tokens}")
        print(f"  Output tokens: {reasoning.output_tokens}")
        print(f"  Total tokens: {reasoning.total_tokens}")
        print("\n[Summary]")
    print(json.dumps(payload, indent=2))
    return 0


async def run_batch(
    queries: list[str], should_delegate: bool, verbose: bool, force_reasoning: bool
) -> int:
    """Run several queries against a single embedder/router instance.

    Sharing one process amortizes the fixed per-process cold-start cost (Azure AD token
    acquisition + Azure OpenAI client init, roughly 2s) across all queries instead of paying
    it again for every query, as happens when each query spawns a separate CLI process.
    """
    setup_start = time.perf_counter()
    embedder = create_embedder()
    router = CapabilityRouter(create_store(embedder.dimensions), embedder)
    setup_ms = (time.perf_counter() - setup_start) * 1000
    if verbose:
        print(f"[Setup] Embedder + router initialized once in {setup_ms:.0f} ms (shared across batch)\n")
    exit_code = 0
    for query in queries:
        if verbose:
            print("=" * 60)
            print(f"QUERY: {query}")
            print("=" * 60)
        exit_code = await run_query(router, query, should_delegate, verbose, force_reasoning) or exit_code
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--delegate", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--force-reasoning", action="store_true")
    args = parser.parse_args()
    configure_telemetry("orchestration-agent")
    raise SystemExit(asyncio.run(run(args.query, args.delegate, args.verbose, args.force_reasoning)))


def main_batch() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("queries_file", help="Path to a text file with one query per line")
    parser.add_argument("--delegate", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--force-reasoning", action="store_true")
    args = parser.parse_args()
    configure_telemetry("orchestration-agent")
    with open(args.queries_file, encoding="utf-8") as handle:
        queries = [line.strip() for line in handle if line.strip()]
    raise SystemExit(
        asyncio.run(run_batch(queries, args.delegate, args.verbose, args.force_reasoning))
    )


if __name__ == "__main__":
    main()
