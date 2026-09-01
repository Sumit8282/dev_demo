"""Release risk score models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

_DRIVER_SCORE_KEYS = (
    "file_count_score",
    "lines_changed_score",
    "failure_rate_score",
)


def _count(value: int, noun: str) -> str:
    """Format a count with its noun, pluralised as needed (e.g. ``3 files``)."""
    return f"{value:,} {noun}" if value == 1 else f"{value:,} {noun}s"


class HighRiskFile(BaseModel):
    filepath: str
    failure_rate: float
    lines_changed: int


class ReleaseRiskScore(BaseModel):
    """Composite risk score for a release PR (0.0 = no risk, 1.0 = maximum risk)."""

    score: float = Field(..., ge=0.0, le=1.0)
    level: str  # LOW | MEDIUM | HIGH
    breakdown: dict[str, float] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    high_risk_files: list[HighRiskFile] = Field(default_factory=list)

    def reason(self) -> str:
        """Plain-language explanation of why the risk level was assigned."""
        level = (self.level or "").upper() or "UNKNOWN"
        has_scored_factor = any(
            (self.breakdown.get(key) or 0) > 0 for key in _DRIVER_SCORE_KEYS
        )
        if (
            not self._has_change_volume()
            and not self.high_risk_files
            and not has_scored_factor
        ):
            return (
                f"Classified as {level} risk. No changed files were reported for this "
                "pull request, so there were no risk factors to measure."
            )

        sentences = [
            f"Classified as {level} risk.",
            self._change_volume_sentence(),
            self._failure_history_sentence(),
        ]

        if self.high_risk_files:
            flagged = ", ".join(
                f"{item.filepath} (failed in {item.failure_rate:.0%} of past releases, "
                f"{_count(item.lines_changed, 'line')} changed)"
                for item in self.high_risk_files
            )
            sentences.append(f"Files with a poor track record: {flagged}.")

        return " ".join(sentence for sentence in sentences if sentence)

    def _metric(self, key: str) -> int:
        try:
            return int(self.metrics.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _has_change_volume(self) -> bool:
        return bool(
            self._metric("files_changed")
            or self._metric("lines_changed")
            or self._metric("lines_added")
            or self._metric("lines_deleted")
        )

    def _change_volume_sentence(self) -> str:
        files_changed = self._metric("files_changed")
        lines_added = self._metric("lines_added")
        lines_deleted = self._metric("lines_deleted")
        lines_changed = self._metric("lines_changed") or lines_added + lines_deleted

        if not files_changed and not lines_changed:
            return "Change volume was not recorded for this pull request."

        sentence = (
            f"This release touches {_count(files_changed, 'file')} and changes "
            f"{_count(lines_changed, 'line')} of code "
            f"({lines_added:,} added, {lines_deleted:,} removed)"
        )

        file_limit = self._metric("file_count_limit")
        lines_limit = self._metric("lines_changed_limit")
        if file_limit and lines_limit:
            sentence += (
                f", compared with the review limits of {_count(file_limit, 'file')} "
                f"and {_count(lines_limit, 'line')} where a change counts as "
                "maximum size"
            )
        return f"{sentence}."

    def _failure_history_sentence(self) -> str:
        failure_rate = self.breakdown.get("failure_rate_score")
        if failure_rate is None:
            failure_rate = self.metrics.get("historical_failure_rate", 0.0)

        if not failure_rate:
            return "None of the changed files have failed in earlier releases."
        return (
            "Weighted across the changed files, this code has failed in "
            f"{failure_rate:.0%} of earlier releases."
        )

    @classmethod
    def from_scorer_result(cls, result: Any) -> ReleaseRiskScore:
        """Build from ``ReleaseRiskScorer`` ``RiskResult`` dataclass."""
        high_risk_files = [
            HighRiskFile(
                filepath=item["filepath"],
                failure_rate=item["failure_rate"],
                lines_changed=item["lines_changed"],
            )
            for item in result.high_risk_files
        ]
        return cls(
            score=result.score,
            level=result.level,
            breakdown=dict(result.breakdown),
            metrics=dict(getattr(result, "metrics", None) or {}),
            high_risk_files=high_risk_files,
        )
