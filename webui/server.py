import argparse
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from agents.models import AgentDefinition, load_agent
from orchestrator.delegation import delegate
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


def _agent_card(definition: AgentDefinition) -> dict[str, object]:
    return {
        "id": definition.id,
        "name": definition.name,
        "description": definition.description,
        "owns": sorted({phrase for skill in definition.skills for phrase in skill.owns}),
        "boundaries": sorted({phrase for skill in definition.skills for phrase in skill.does_not_own}),
        "examples": [example for skill in definition.skills for example in skill.examples][:3],
        "endpoint": f"http://localhost:{definition.port}/a2a",
    }


def load_agent_cards() -> list[dict[str, object]]:
    return [_agent_card(load_agent(agent_id)) for agent_id in AGENT_IDS]


async def homepage(_: Request) -> FileResponse:
    return FileResponse(Path(__file__).with_name("index.html"))


async def agents(_: Request) -> JSONResponse:
    return JSONResponse({"agents": load_agent_cards()})


async def query(request: Request) -> JSONResponse:
    payload = await request.json()
    user_query = str(payload.get("query", "")).strip()
    if not user_query:
        return JSONResponse({"error": "Query is required."}, status_code=400)

    router: CapabilityRouter = request.app.state.router
    started = time.perf_counter()
    decision = router.route(user_query)
    routing_ms = (time.perf_counter() - started) * 1000

    answer = None
    a2a_ms = 0.0
    if decision.selected:
        a2a_started = time.perf_counter()
        raw_answer = await delegate(decision.selected.document, user_query)
        a2a_ms = (time.perf_counter() - a2a_started) * 1000
        try:
            answer = json.loads(raw_answer).get("answer", raw_answer)
        except json.JSONDecodeError:
            answer = raw_answer

    return JSONResponse(
        {
            "outcome": decision.outcome,
            "answer": answer,
            "clarification": decision.clarification,
            "selected_agent": decision.selected.document.agent_id if decision.selected else None,
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
                "a2a_ms": round(a2a_ms, 1),
                "total_ms": round(routing_ms + a2a_ms, 1),
                "reasoning_tokens": 0,
                "path": "deterministic fast path",
            },
        }
    )


@asynccontextmanager
async def lifespan(application: Starlette) -> AsyncIterator[None]:
    embedder = create_embedder()
    application.state.router = CapabilityRouter(create_store(embedder.dimensions), embedder)
    yield


app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/api/agents", agents),
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
