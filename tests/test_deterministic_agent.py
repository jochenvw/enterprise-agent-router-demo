import json

import pytest

from agents.deterministic_agent import DeterministicDomainAgent
from agents.models import load_agent


@pytest.mark.asyncio
async def test_project_controls_returns_eac() -> None:
    agent = DeterministicDomainAgent(load_agent("project-controls"))
    response = await agent.run("What is the EAC for Falcon?")
    payload = json.loads(response.text)
    assert payload["agent"] == "project-controls"
    assert "52.4" in payload["answer"]

