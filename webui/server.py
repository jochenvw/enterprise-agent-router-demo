import argparse
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from agents.models import AgentDefinition, load_agent
from orchestrator.delegation import delegate
from orchestrator.multihop import SubQueryResult, decompose_query, synthesize_answer
from orchestrator.reasoning import reason_over_candidates
from orchestrator.router import CapabilityRouter
from registry.embeddings import create_embedder
from registry.store import create_store
from shared.telemetry import configure_telemetry

AGENT_IDS = (
    "capital-projects",
    "project-controls",
    "procurement",
    "investment-planning",
    "consulting",
)
REPO_ROOT = Path(__file__).resolve().parent.parent


def _agent_card(definition: AgentDefinition) -> dict[str, object]:
    return {
        "id": definition.id,
        "name": definition.name,
        "description": definition.description,
        "owns": sorted({phrase for skill in definition.skills for phrase in skill.owns}),
        "boundaries": sorted({phrase for skill in definition.skills for phrase in skill.does_not_own}),
        "examples": [example for skill in definition.skills for example in skill.examples][:3],
        "endpoint": f"http://localhost:{definition.port}/a2a",
        "card_url": f"/cards/{definition.id}",
        "live_card_url": f"http://localhost:{definition.port}/.well-known/agent-card.json",
    }


def load_agent_cards() -> list[dict[str, object]]:
    return [_agent_card(load_agent(agent_id)) for agent_id in AGENT_IDS]


def reasoning_available() -> bool:
    return bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_REASONING_DEPLOYMENT"))


def load_reasoning_config() -> None:
    outputs_path = REPO_ROOT / "infra" / ".deployment-outputs.json"
    if os.getenv("AZURE_OPENAI_ENDPOINT") or not outputs_path.exists():
        return

    outputs = json.loads(outputs_path.read_text(encoding="utf-8"))
    endpoint = outputs.get("openaiEndpoint", {}).get("value")
    if endpoint:
        os.environ["AZURE_OPENAI_ENDPOINT"] = endpoint
        os.environ.setdefault("AZURE_OPENAI_REASONING_DEPLOYMENT", "gpt-5.4-nano")
        os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-10-21")


async def homepage(_: Request) -> FileResponse:
    return FileResponse(Path(__file__).with_name("index.html"))


async def card_page(_: Request) -> FileResponse:
    return FileResponse(Path(__file__).with_name("card.html"))


async def agents(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "agents": load_agent_cards(),
            "reasoning_available": reasoning_available(),
        }
    )


async def agent_card(request: Request) -> JSONResponse:
    agent_id = request.path_params["agent_id"]
    if agent_id not in AGENT_IDS:
        return JSONResponse({"error": f"Unknown agent: {agent_id}"}, status_code=404)

    definition = load_agent(agent_id)
    url = f"http://localhost:{definition.port}/.well-known/agent-card.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
    return JSONResponse(response.json())


def _answer_text(raw_answer: str) -> str:
    try:
        return str(json.loads(raw_answer).get("answer", raw_answer))
    except json.JSONDecodeError:
        return raw_answer


async def _single_hop(router: CapabilityRouter, user_query: str, use_reasoning: bool) -> dict:
    started = time.perf_counter()
    decision = router.route(user_query)
    routing_ms = (time.perf_counter() - started) * 1000

    reasoning_ms = 0.0
    reasoning_tokens = 0
    reasoning_summary = None
    if use_reasoning:
        reasoning = reason_over_candidates(user_query, decision.candidates)
        reasoning_ms = reasoning.elapsed_ms
        reasoning_tokens = reasoning.total_tokens
        reasoning_summary = reasoning.reason
        selected = next(
            (
                candidate
                for candidate in decision.candidates
                if candidate.document.agent_id == reasoning.selected_agent_id
            ),
            None,
        )
        if reasoning.clarification_required:
            decision.outcome = "clarify"
            decision.selected = None
            decision.clarification = reasoning.reason or decision.clarification
        elif selected:
            decision.outcome = "delegate"
            decision.selected = selected
            decision.clarification = None

    answer = None
    a2a_ms = 0.0
    if decision.selected:
        a2a_started = time.perf_counter()
        answer = _answer_text(await delegate(decision.selected.document, user_query))
        a2a_ms = (time.perf_counter() - a2a_started) * 1000

    return {
        "outcome": decision.outcome,
        "answer": answer,
        "clarification": decision.clarification,
        "selected_agents": [decision.selected.document.agent_id] if decision.selected else [],
        "reasoning": reasoning_summary,
        "candidates": [
            {
                "agent": candidate.document.agent_id,
                "skill": candidate.document.skill_id,
                "score": round(candidate.score, 4),
            }
            for candidate in decision.candidates
        ],
        "telemetry": {
            "routing_ms": round(routing_ms, 1),
            "reasoning_ms": round(reasoning_ms, 1),
            "a2a_ms": round(a2a_ms, 1),
            "total_ms": round(routing_ms + reasoning_ms + a2a_ms, 1),
            "reasoning_tokens": reasoning_tokens,
            "path": "reasoned routing" if use_reasoning else "deterministic fast path",
        },
    }


async def _multi_hop(router: CapabilityRouter, user_query: str) -> dict:
    sub_queries, decompose_ms, decompose_in, decompose_out = decompose_query(user_query)
    results: list[SubQueryResult] = []
    routing_ms = 0.0
    a2a_ms = 0.0

    for sub_query in sub_queries:
        routing_started = time.perf_counter()
        decision = router.route(sub_query)
        routing_ms += (time.perf_counter() - routing_started) * 1000
        if not decision.selected:
            results.append(SubQueryResult(sub_query, None, None, decision.clarification))
            continue

        a2a_started = time.perf_counter()
        answer = _answer_text(await delegate(decision.selected.document, sub_query))
        a2a_ms += (time.perf_counter() - a2a_started) * 1000
        results.append(SubQueryResult(sub_query, decision.selected.document.agent_id, answer))

    combined, synthesize_ms, synthesize_in, synthesize_out = synthesize_answer(user_query, results)
    reasoning_ms = decompose_ms + synthesize_ms
    reasoning_tokens = decompose_in + decompose_out + synthesize_in + synthesize_out
    selected_agents = list(dict.fromkeys(result.agent_id for result in results if result.agent_id))

    return {
        "outcome": "multi-hop",
        "answer": combined,
        "clarification": None,
        "selected_agents": selected_agents,
        "reasoning": f"Decomposed into {len(sub_queries)} specialist questions.",
        "hops": [
            {
                "query": result.sub_query,
                "agent": result.agent_id,
                "answer": result.answer,
                "clarification": result.clarification,
            }
            for result in results
        ],
        "telemetry": {
            "routing_ms": round(routing_ms, 1),
            "reasoning_ms": round(reasoning_ms, 1),
            "a2a_ms": round(a2a_ms, 1),
            "total_ms": round(routing_ms + reasoning_ms + a2a_ms, 1),
            "reasoning_tokens": reasoning_tokens,
            "path": "multi-step decomposition and synthesis",
        },
    }


async def query(request: Request) -> JSONResponse:
    payload = await request.json()
    user_query = str(payload.get("query", "")).strip()
    if not user_query:
        return JSONResponse({"error": "Query is required."}, status_code=400)

    mode = str(payload.get("mode", "fast"))
    if mode not in {"fast", "reasoned", "multi-hop"}:
        return JSONResponse({"error": f"Unsupported routing mode: {mode}"}, status_code=400)
    if mode != "fast" and not reasoning_available():
        return JSONResponse(
            {"error": ("This mode requires AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_REASONING_DEPLOYMENT.")},
            status_code=503,
        )

    router: CapabilityRouter = request.app.state.router
    result = (
        await _multi_hop(router, user_query)
        if mode == "multi-hop"
        else await _single_hop(router, user_query, use_reasoning=mode == "reasoned")
    )
    return JSONResponse(result)


@asynccontextmanager
async def lifespan(application: Starlette) -> AsyncIterator[None]:
    load_reasoning_config()
    embedder = create_embedder()
    application.state.router = CapabilityRouter(create_store(embedder.dimensions), embedder)
    yield


app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/cards/{agent_id}", card_page),
        Route("/api/agents", agents),
        Route("/api/agent-card/{agent_id}", agent_card),
        Route("/api/query", query, methods=["POST"]),
    ],
    lifespan=lifespan,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    configure_telemetry("router-webui")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
