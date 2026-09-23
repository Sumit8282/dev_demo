"""Select the in-app QA agent or the Barko adapter from QA_WORKFLOW."""

from __future__ import annotations

from typing import Any, Protocol

from app.agents.barko_qa_agent import BarkoQAAgent
from app.agents.qa_agent import QAAgent
from app.config import Settings, get_settings
from app.models.validation import QAValidationResult


class QAValidator(Protocol):
    async def validate_async(self, **kwargs: Any) -> QAValidationResult:
        ...


def create_qa_agent(settings: Settings | None = None) -> QAValidator:
    settings = settings or get_settings()
    if settings.qa_workflow == "barko_agent":
        return BarkoQAAgent(settings)
    return QAAgent(settings=settings)
