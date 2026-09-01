"""Persist historical file failure rates for release risk scoring."""

from __future__ import annotations

import json
from pathlib import Path

HISTORY_ROOT = Path(__file__).resolve().parents[2] / "data"
HISTORY_FILE = HISTORY_ROOT / "file_failure_history.json"


class FileFailureHistoryStore:
    """Load per-file historical failure rates (0.0–1.0) from local JSON storage."""

    def __init__(self, history_path: Path | None = None) -> None:
        self.history_path = history_path or HISTORY_FILE

    def get_failure_rates(self, filepaths: list[str] | None = None) -> dict[str, float]:
        """Return failure rates for the given paths, or the full map when paths omitted."""
        all_rates = self._load_all()
        if filepaths is None:
            return all_rates
        return {path: all_rates.get(path, 0.0) for path in filepaths}

    def _load_all(self) -> dict[str, float]:
        if not self.history_path.is_file():
            return {}
        try:
            payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        rates: dict[str, float] = {}
        for key, value in payload.items():
            if not isinstance(key, str):
                continue
            try:
                rate = float(value)
            except (TypeError, ValueError):
                continue
            rates[key] = min(max(rate, 0.0), 1.0)
        return rates
