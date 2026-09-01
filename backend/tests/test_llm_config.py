"""LLM configuration tests."""

from app.config import Settings


def test_llm_enabled_requires_credentials():
    settings = Settings(
        USE_LLM_AGENTS=True,
        LLM_PROVIDER="openai",
        LLM_MODEL="gpt-4o",
        LLM_API_KEY="",
    )
    assert settings.llm_enabled is False


def test_llm_enabled_when_fully_configured():
    settings = Settings(
        USE_LLM_AGENTS=True,
        LLM_PROVIDER="openai",
        LLM_MODEL="gpt-4o",
        LLM_API_KEY="test-key",
    )
    assert settings.llm_enabled is True


def test_llm_disabled_by_flag():
    settings = Settings(
        USE_LLM_AGENTS=False,
        LLM_PROVIDER="openai",
        LLM_MODEL="gpt-4o",
        LLM_API_KEY="test-key",
    )
    assert settings.llm_enabled is False
