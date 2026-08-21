import time

import httpx
from a2a.client import A2ACardResolver
from a2a.types import AgentCard
from agent_framework.a2a import A2AAgent
from google.protobuf.json_format import Parse

from registry.models import CapabilityDocument
from shared.telemetry import tracer


def _card_from_document(document: CapabilityDocument) -> AgentCard | None:
    if not document.agent_card_json:
        return None
    try:
        return Parse(document.agent_card_json, AgentCard())
    except Exception:
        return None


async def delegate(document: CapabilityDocument, query: str) -> str:
    with tracer().start_as_current_span("a2a.delegate") as span:
        span.set_attribute("agent.selected", document.agent_id)
        card = _card_from_document(document)
        if card is None:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resolver = A2ACardResolver(httpx_client=client, base_url=document.base_url)
                card = await resolver.get_agent_card()
        async with A2AAgent(
            name=card.name,
            description=card.description,
            agent_card=card,
            url=document.base_url,
        ) as agent:
            response = await agent.run(query)
            return response.text


async def delegate_verbose(document: CapabilityDocument, query: str) -> str:
    start = time.perf_counter()
    print("\n[A2A] Loading selected Agent Card from Azure AI Search payload")
    card = _card_from_document(document)
    if card is None:
        print(f"[A2A] Falling back to live Agent Card fetch: {document.base_url}/.well-known/agent-card.json")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resolver = A2ACardResolver(httpx_client=client, base_url=document.base_url)
            card = await resolver.get_agent_card()

    print(f"[A2A] Agent: {card.name}")
    print(f"[A2A] Endpoint: {document.endpoint}")
    print(f"[A2A] Question: {query}")
    with tracer().start_as_current_span("a2a.delegate") as span:
        span.set_attribute("agent.selected", document.agent_id)
        async with A2AAgent(
            name=card.name,
            description=card.description,
            agent_card=card,
            url=document.base_url,
        ) as agent:
            response = await agent.run(query)
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(f"[A2A] Response: {response.text}")
            print(f"[A2A] Completed in {elapsed_ms:.0f} ms")
            return response.text
