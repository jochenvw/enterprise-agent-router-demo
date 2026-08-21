import argparse
import os

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from agent_framework.a2a import A2AExecutor
from starlette.applications import Starlette

from agents.deterministic_agent import DeterministicDomainAgent
from agents.models import load_agent
from shared.telemetry import configure_telemetry


def create_app(agent_id: str, port: int | None = None) -> Starlette:
    definition = load_agent(agent_id)
    selected_port = port or definition.port
    public_base_url = os.getenv("PUBLIC_BASE_URL", f"http://localhost:{selected_port}").rstrip("/")
    endpoint = f"{public_base_url}/a2a"
    skills = [
        AgentSkill(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            tags=[*skill.owns, *(f"not:{boundary}" for boundary in skill.does_not_own)],
            examples=skill.examples,
        )
        for skill in definition.skills
    ]
    card = AgentCard(
        name=definition.name,
        description=definition.description,
        version=definition.version,
        documentation_url=f"https://demo.local/agents/{definition.id}",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[AgentInterface(url=endpoint, protocol_binding="JSONRPC")],
        skills=skills,
    )
    handler = DefaultRequestHandler(
        agent_executor=A2AExecutor(DeterministicDomainAgent(definition), stream=False),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    return Starlette(
        routes=[
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, "/a2a"),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", required=True)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    definition = load_agent(args.agent)
    port = args.port or definition.port
    configure_telemetry(f"agent-{definition.id}")
    uvicorn.run(create_app(definition.id, port), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
