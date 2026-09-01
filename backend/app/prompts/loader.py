"""Load agent prompts from the prompts directory."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache
def load_prompt(name: str) -> str:
    """Load a prompt file by name (without extension).

    Looks for ``{name}.md`` then ``{name}.txt`` under ``app/prompts/``.
    """
    for extension in (".md", ".txt"):
        path = PROMPTS_DIR / f"{name}{extension}"
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(
        f"Prompt '{name}' not found in {PROMPTS_DIR}. "
        f"Expected {name}.md or {name}.txt"
    )


def format_prompt(name: str, **kwargs: object) -> str:
    """Load and format a prompt template with keyword placeholders."""
    template = load_prompt(name)
    return template.format(**kwargs)
