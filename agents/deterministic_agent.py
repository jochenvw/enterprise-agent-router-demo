import asyncio
import json
from collections.abc import AsyncIterable, Awaitable
from typing import Any, Literal, overload

from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    AgentSession,
    BaseAgent,
    Content,
    Message,
    normalize_messages,
)

from agents.models import AgentDefinition

FALCON_DATA = {
    "capital-projects": {
        "status": "Sanctioned and in execution; compressor installation is the next milestone.",
        "milestone": "Mechanical completion is planned for 15 November 2026.",
        "capex": "The sanctioned CAPEX is EUR 48.0 million.",
    },
    "project-controls": {
        "eac": "The estimate at completion is EUR 52.4 million.",
        "variance": "The project is EUR 4.4 million above baseline, mainly due to schedule delay and rework.",
        "schedule": "The current schedule variance is 18 days behind the approved baseline.",
    },
    "procurement": {
        "price": "The latest Falcon compressor price is EUR 8.6 million from Siemens Energy.",
        "order": "Purchase order PO-10482 is confirmed; delivery is expected on 28 September 2026.",
        "vendor": "Siemens Energy is the awarded compressor vendor.",
    },
    "investment-planning": {
        "funding": "Falcon funding was approved at EUR 48.0 million in the 2026 capital plan.",
        "portfolio": "Falcon is ranked third in the Growth and Reliability portfolio.",
        "business_case": "The approved business case has an expected NPV of EUR 31.2 million.",
    },
    "consulting": {
        "spend": "Falcon consulting spend is EUR 1.15 million against a EUR 1.30 million SOW ceiling.",
        "status": (
            "The delivery assurance engagement is active and its final review is due 30 September 2026."
        ),
        "supplier": "Northstar Advisory owns the current Falcon delivery assurance SOW.",
    },
}


class DeterministicDomainAgent(BaseAgent):
    def __init__(self, definition: AgentDefinition) -> None:
        super().__init__(name=definition.name, description=definition.description)
        self.definition = definition

    @overload
    def run(
        self,
        messages: str | Message | list[str] | list[Message] | None = None,
        *,
        stream: Literal[False] = False,
        session: AgentSession | None = None,
        **kwargs: Any,
    ) -> Awaitable[AgentResponse]: ...

    @overload
    def run(
        self,
        messages: str | Message | list[str] | list[Message] | None = None,
        *,
        stream: Literal[True],
        session: AgentSession | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[AgentResponseUpdate]: ...

    def run(
        self,
        messages: str | Message | list[str] | list[Message] | None = None,
        *,
        stream: bool = False,
        session: AgentSession | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[AgentResponseUpdate] | Awaitable[AgentResponse]:
        if stream:
            return self._run_stream(messages)
        return self._run(messages)

    async def _run(
        self, messages: str | Message | list[str] | list[Message] | None
    ) -> AgentResponse:
        text = self._answer(messages)
        return AgentResponse(messages=[Message(role="assistant", contents=[Content.from_text(text=text)])])

    async def _run_stream(
        self, messages: str | Message | list[str] | list[Message] | None
    ) -> AsyncIterable[AgentResponseUpdate]:
        for token in self._answer(messages).split():
            yield AgentResponseUpdate(
                role="assistant",
                contents=[Content.from_text(text=f"{token} ")],
            )
            await asyncio.sleep(0)

    def _answer(self, messages: str | Message | list[str] | list[Message] | None) -> str:
        normalized = normalize_messages(messages)
        query = normalized[-1].text.lower() if normalized and normalized[-1].text else ""
        data = FALCON_DATA[self.definition.id]

        key_groups = {
            "eac": ("eac", "estimate at completion", "forecast"),
            "variance": ("variance", "over budget", "cost gone up", "cost increase"),
            "schedule": ("schedule", "baseline", "earned value"),
            "price": ("price", "paid", "quote"),
            "order": ("purchase order", "delivery", "equipment", "material"),
            "vendor": ("vendor", "supplier", "siemens"),
            "funding": ("funding", "funded", "approved", "allocation", "budget"),
            "portfolio": ("portfolio", "rank", "priority"),
            "business_case": ("business case", "npv", "investment case"),
            "spend": ("consultant", "consulting", "advisory", "spend", "sow"),
            "status": ("status", "progress", "latest"),
            "milestone": ("milestone", "completion"),
            "capex": ("capex", "sanctioned cost"),
            "supplier": ("northstar",),
        }
        for key, phrases in key_groups.items():
            if key in data and any(phrase in query for phrase in phrases):
                return json.dumps(
                    {"agent": self.definition.id, "project": "Falcon", "answer": data[key]},
                    ensure_ascii=True,
                )

        supported = "; ".join(data.values())
        return json.dumps(
            {
                "agent": self.definition.id,
                "project": "Falcon",
                "answer": f"I only support my declared demo scenarios. Available facts: {supported}",
            },
            ensure_ascii=True,
        )
