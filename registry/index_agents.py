import argparse
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml
from a2a.client import A2ACardResolver
from google.protobuf.json_format import MessageToJson

from registry.embeddings import create_embedder
from registry.models import CapabilityDocument
from registry.store import create_store
from shared.telemetry import configure_telemetry, tracer


async def discover(base_url: str, client: httpx.AsyncClient) -> tuple[object, str]:
    resolver = A2ACardResolver(httpx_client=client, base_url=base_url)
    card = await resolver.get_agent_card()
    return card, MessageToJson(card)


async def build_documents(urls: list[str]) -> list[CapabilityDocument]:
    embedder = create_embedder()
    documents: list[CapabilityDocument] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for base_url in urls:
            with tracer().start_as_current_span("router.index.discover"):
                card, card_json = await discover(base_url, client)
            documentation_path = urlparse(card.documentation_url).path
            agent_id = documentation_path.rstrip("/").split("/")[-1]
            if not agent_id:
                agent_id = re.sub(r"[^a-z0-9]+", "-", card.name.lower()).strip("-")
                agent_id = agent_id.removesuffix("-agent")
            interface = card.supported_interfaces[0]
            owns: list[str] = []
            does_not_own: list[str] = []
            examples: list[str] = []
            skill_descriptions: list[str] = []
            for skill in card.skills:
                tags = skill.tags or []
                owns.extend(tag for tag in tags if not tag.startswith("not:"))
                does_not_own.extend(tag.removeprefix("not:") for tag in tags if tag.startswith("not:"))
                examples.extend(skill.examples or [])
                skill_descriptions.append(f"{skill.name}: {skill.description}")
            document = CapabilityDocument(
                id=agent_id,
                agent_id=agent_id,
                agent_name=card.name,
                skill_id="agent-card",
                skill_name="A2A Agent Card",
                description=f"{card.description}\n\nSkills:\n" + "\n".join(skill_descriptions),
                examples=examples,
                owns=sorted(set(owns)),
                does_not_own=sorted(set(does_not_own)),
                endpoint=interface.url,
                base_url=base_url,
                agent_card_json=card_json,
            )
            document.embedding = embedder.embed(document.searchable_text)
            documents.append(document)
    return documents


async def run(config_path: Path) -> int:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    documents = await build_documents(config["agents"])
    dimensions = len(documents[0].embedding)
    with tracer().start_as_current_span("router.index.upsert"):
        create_store(dimensions).replace(documents)
    print(json.dumps({"agents": len(config["agents"]), "capabilities": len(documents)}))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("agents.yaml"),
    )
    args = parser.parse_args()
    configure_telemetry("agent-indexer")
    raise SystemExit(asyncio.run(run(args.config)))


if __name__ == "__main__":
    main()
