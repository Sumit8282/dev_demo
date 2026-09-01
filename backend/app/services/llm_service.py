"""Optional LLM abstraction for agent reasoning."""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def resolve_chat_model(settings: Settings | None = None) -> BaseChatModel | None:
    """Return a chat model when settings are a real configured ``Settings`` instance."""
    if settings is not None and not isinstance(settings, Settings):
        return None
    try:
        resolved = settings or get_settings()
        if not resolved.llm_enabled:
            return None
        return get_llm(resolved)
    except Exception:
        logger.warning("[LLM] Unable to resolve chat model", exc_info=True)
        return None


def get_llm(settings: Settings | None = None) -> BaseChatModel | None:
    """Return configured LLM or None when not configured."""
    settings = settings or get_settings()
    provider = settings.llm_provider.strip().lower()
    model = settings.llm_model.strip()
    api_key = settings.llm_api_key.get_secret_value().strip()
    base_url = settings.llm_base_url.strip()

    if not provider or not model or not api_key:
        return None

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs: dict = {"model": model, "api_key": api_key, "max_tokens": 8192}
        if base_url:
            kwargs["base_url"] = base_url.rstrip("/")
        return ChatOpenAI(**kwargs)

    if provider in {"anthropic", "claude"}:
        from langchain_anthropic import ChatAnthropic

        kwargs = {"model": model, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url.rstrip("/")
        return ChatAnthropic(**kwargs)

    raise ValueError(f"Unsupported LLM provider: {provider}")
