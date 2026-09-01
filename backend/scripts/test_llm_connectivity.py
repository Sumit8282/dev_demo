"""Verify LLM connectivity via LiteLLM proxy."""

from __future__ import annotations

import asyncio
import sys

from _bootstrap import BACKEND_ROOT  # noqa: F401

from app.config import get_settings
from app.services.llm_service import get_llm


async def main() -> int:
    settings = get_settings()

    print("LLM configuration")
    print(f"  provider : {settings.llm_provider or '(not set)'}")
    print(f"  model    : {settings.llm_model or '(not set)'}")
    print(f"  base_url : {settings.llm_base_url or '(not set)'}")
    print(f"  enabled  : {settings.llm_enabled}")

    if not settings.llm_enabled:
        print("\nFAIL: LLM is not fully configured.")
        return 1

    llm = get_llm(settings)
    if llm is None:
        print("\nFAIL: get_llm() returned None.")
        return 1

    print("\nCalling LLM...")
    try:
        response = await llm.ainvoke("Reply with exactly: LLM_OK")
        content = getattr(response, "content", str(response))
        print(f"Response: {content}")
        print("\nPASS: LLM connectivity OK")
        return 0
    except Exception as exc:
        print(f"\nFAIL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
