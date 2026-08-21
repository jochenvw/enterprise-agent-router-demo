from pydantic import BaseModel, Field


class CapabilityDocument(BaseModel):
    id: str
    agent_id: str
    agent_name: str
    skill_id: str
    skill_name: str
    description: str
    examples: list[str] = Field(default_factory=list)
    owns: list[str] = Field(default_factory=list)
    does_not_own: list[str] = Field(default_factory=list)
    endpoint: str
    base_url: str
    agent_card_json: str
    embedding: list[float] = Field(default_factory=list)
    search_score: float | None = None

    @property
    def searchable_text(self) -> str:
        return " ".join(
            [
                self.agent_name,
                self.skill_name,
                self.description,
                *self.examples,
                *self.owns,
                self.agent_card_json,
            ]
        )
