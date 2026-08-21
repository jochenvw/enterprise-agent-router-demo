from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SkillDefinition(BaseModel):
    id: str
    name: str
    description: str
    examples: list[str] = Field(default_factory=list)
    owns: list[str] = Field(default_factory=list)
    does_not_own: list[str] = Field(default_factory=list)


class AgentDefinition(BaseModel):
    id: str
    name: str
    description: str
    version: str = "1.0.0"
    port: int
    skills: list[SkillDefinition]


def load_agent(agent_id: str) -> AgentDefinition:
    path = Path(__file__).parent / agent_id / "card.yaml"
    if not path.exists():
        choices = ", ".join(sorted(item.parent.name for item in Path(__file__).glob("*/card.yaml")))
        raise ValueError(f"Unknown agent '{agent_id}'. Expected one of: {choices}")
    return AgentDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

