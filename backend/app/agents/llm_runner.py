"""Helpers for invoking LangChain LLM agents with structured output."""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from deepagents import create_deep_agent
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from app.services.llm_service import resolve_chat_model

logger = logging.getLogger(__name__)

ResponseT = TypeVar("ResponseT", bound=BaseModel)


def create_langchain_agent(
    *,
    settings: Any = None,
    tools: list,
    system_prompt: str,
    name: str,
    response_format: type[BaseModel] | None = None,
    llm: BaseChatModel | None = None,
) -> Any | None:
    """Build a LangChain agent, or ``None`` when no chat model is configured."""
    model = llm or resolve_chat_model(settings)
    if model is None:
        return None
    kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "system_prompt": system_prompt,
        "name": name,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    return create_agent(**kwargs)


def create_qa_deep_agent(
    *,
    settings: Any = None,
    tools: list,
    system_prompt: str,
    name: str,
    response_format: type[BaseModel] | None = None,
    llm: BaseChatModel | None = None,
) -> Any | None:
    """Build a QA Deep Agent, or ``None`` when no chat model is configured."""
    model = llm or resolve_chat_model(settings)
    if model is None:
        return None
    kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "system_prompt": system_prompt,
        "name": name,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    return create_deep_agent(**kwargs)


async def invoke_langchain_agent(agent: Any, *, user_message: str) -> str:
    """Invoke a LangChain agent and return the final assistant text summary."""
    try:
        result = await agent.ainvoke({"messages": [HumanMessage(content=user_message)]})
    except Exception:
        logger.exception("[LLM] Orchestrator agent invocation failed")
        return ""

    messages = result.get("messages") if isinstance(result, dict) else None
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                content = message.content
                if isinstance(content, str) and content.strip():
                    return content.strip()
                if isinstance(content, list):
                    parts = [block.get("text", "") for block in content if isinstance(block, dict)]
                    text = "\n".join(part for part in parts if part).strip()
                    if text:
                        return text
    return ""


async def invoke_structured_agent(
    agent: Any,
    *,
    user_message: str,
    response_model: type[ResponseT],
) -> ResponseT | None:
    """Invoke a LangChain agent and parse its structured response."""
    try:
        result = await agent.ainvoke({"messages": [HumanMessage(content=user_message)]})
    except Exception:
        logger.exception("[LLM] Agent invocation failed")
        return None

    structured = _extract_structured_response(result)
    if structured is None:
        logger.warning("[LLM] Agent returned no structured response")
        return None

    if isinstance(structured, response_model):
        return structured

    if isinstance(structured, dict):
        try:
            return response_model.model_validate(structured)
        except Exception:
            logger.exception("[LLM] Failed to parse structured response")
            return None

    logger.warning("[LLM] Unexpected structured response type: %s", type(structured))
    return None


def _extract_structured_response(result: Any) -> Any:
    if isinstance(result, dict):
        if "structured_response" in result:
            return result["structured_response"]
        if "output" in result and isinstance(result["output"], dict):
            return result["output"].get("structured_response")
    return getattr(result, "structured_response", None)
