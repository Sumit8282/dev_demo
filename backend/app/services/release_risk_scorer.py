"""
Release Risk Scorer
-------------------
Calculates a composite risk score for a PR based on:
  - Historical failure rate of each changed file/module
  - Number of files changed
  - Total lines changed (additions + deletions)

Risk Score: 0.0 (no risk) → 1.0 (maximum risk)
Risk Level: LOW (<0.35) | MEDIUM (0.35–0.50) | HIGH (>0.50)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class FileChange:
    """Represents a single changed file in the PR."""
    filepath: str
    lines_added: int
    lines_deleted: int

    @property
    def lines_changed(self) -> int:
        return self.lines_added + self.lines_deleted


@dataclass
class RiskResult:
    """Output of the risk scorer."""
    score: float                        # 0.0 – 1.0
    level: str                          # LOW | MEDIUM | HIGH
    breakdown: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)   # raw counts and scoring limits
    high_risk_files: list = field(default_factory=list)

    def __str__(self) -> str:
        lines = [
            f"Risk Level : {self.level}",
            f"Risk Score : {self.score:.2f}",
            f"Files Changed : {int(self.metrics.get('files_changed', 0))}",
            f"Lines Changed : {int(self.metrics.get('lines_changed', 0))}",
            "Breakdown  :",
            f"  File Count Score     : {self.breakdown.get('file_count_score', 0):.2f}",
            f"  Lines Changed Score  : {self.breakdown.get('lines_changed_score', 0):.2f}",
            f"  Failure Rate Score   : {self.breakdown.get('failure_rate_score', 0):.2f}",
        ]
        if self.high_risk_files:
            lines.append("High-Risk Files :")
            for item in self.high_risk_files:
                lines.append(
                    f"  - {item['filepath']}  (failure rate: {item['failure_rate']:.0%})"
                )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------

class ReleaseRiskScorer:
    """
    Composite risk scorer for a PR.

    Weights (must sum to 1.0):
      - file_count_weight   : penalty for touching many files
      - lines_changed_weight: penalty for large diffs
      - failure_rate_weight : penalty from historical failures

    Thresholds:
      - file_count_max  : file count at which file-count score saturates to 1.0
      - lines_max       : line change count at which lines score saturates to 1.0
      - high_risk_cutoff: failure rate above which a file is flagged as high-risk
    """

    def __init__(
        self,
        file_count_weight: float = 0.25,
        lines_changed_weight: float = 0.35,
        failure_rate_weight: float = 0.40,
        file_count_max: int = 20,
        lines_max: int = 1000,
        high_risk_cutoff: float = 0.5,
    ):
        assert abs(file_count_weight + lines_changed_weight + failure_rate_weight - 1.0) < 1e-6, \
            "Weights must sum to 1.0"

        self.file_count_weight = file_count_weight
        self.lines_changed_weight = lines_changed_weight
        self.failure_rate_weight = failure_rate_weight
        self.file_count_max = file_count_max
        self.lines_max = lines_max
        self.high_risk_cutoff = high_risk_cutoff

    def score(
        self,
        changed_files: list[FileChange],
        historical_failure_rates: Optional[dict[str, float]] = None,
    ) -> RiskResult:
        """
        Parameters
        ----------
        changed_files : list[FileChange]
            Every file touched in the PR.
        historical_failure_rates : dict[str, float], optional
            Maps filepath -> failure rate (0.0-1.0).
            Missing files default to 0.0 (no history = assumed clean).

        Returns
        -------
        RiskResult
        """
        if historical_failure_rates is None:
            historical_failure_rates = {}

        file_count_score = self._file_count_score(len(changed_files))
        lines_changed_score = self._lines_changed_score(changed_files)
        failure_rate_score, high_risk_files = self._failure_rate_score(
            changed_files, historical_failure_rates
        )
        lines_added = sum(f.lines_added for f in changed_files)
        lines_deleted = sum(f.lines_deleted for f in changed_files)

        composite = (
            self.file_count_weight * file_count_score
            + self.lines_changed_weight * lines_changed_score
            + self.failure_rate_weight * failure_rate_score
        )
        composite = round(min(max(composite, 0.0), 1.0), 4)

        return RiskResult(
            score=composite,
            level=self._level(composite),
            breakdown={
                "file_count_score": round(file_count_score, 4),
                "lines_changed_score": round(lines_changed_score, 4),
                "failure_rate_score": round(failure_rate_score, 4),
            },
            metrics={
                "files_changed": len(changed_files),
                "lines_added": lines_added,
                "lines_deleted": lines_deleted,
                "lines_changed": lines_added + lines_deleted,
                "high_risk_file_count": len(high_risk_files),
                "historical_failure_rate": round(failure_rate_score, 4),
                "file_count_limit": self.file_count_max,
                "lines_changed_limit": self.lines_max,
                "file_count_weight": self.file_count_weight,
                "lines_changed_weight": self.lines_changed_weight,
                "failure_rate_weight": self.failure_rate_weight,
            },
            high_risk_files=high_risk_files,
        )

    def _file_count_score(self, count: int) -> float:
        """Linear scale: 0 files -> 0.0, file_count_max+ files -> 1.0."""
        return min(count / self.file_count_max, 1.0)

    def _lines_changed_score(self, changed_files: list[FileChange]) -> float:
        """Linear scale: 0 lines -> 0.0, lines_max+ lines -> 1.0."""
        total = sum(f.lines_changed for f in changed_files)
        return min(total / self.lines_max, 1.0)

    def _failure_rate_score(
        self,
        changed_files: list[FileChange],
        historical_failure_rates: dict[str, float],
    ) -> tuple[float, list[dict]]:
        """
        Weighted average failure rate across all changed files.
        Heavier files (more lines changed) contribute more to the average.
        Files with no history contribute 0.
        """
        if not changed_files:
            return 0.0, []

        total_weight = sum(f.lines_changed for f in changed_files) or len(changed_files)
        weighted_sum = 0.0
        high_risk_files: list[dict] = []

        for fc in changed_files:
            rate = historical_failure_rates.get(fc.filepath, 0.0)
            weight = fc.lines_changed if total_weight else 1
            weighted_sum += rate * weight

            if rate >= self.high_risk_cutoff:
                high_risk_files.append({
                    "filepath": fc.filepath,
                    "failure_rate": rate,
                    "lines_changed": fc.lines_changed,
                })

        return weighted_sum / total_weight, high_risk_files

    def _level(self, score: float) -> str:
        if score < 0.35:
            return "LOW"
        if score < 0.50:
            return "MEDIUM"
        return "HIGH"


def build_file_changes_from_github_metadata(metadata: dict[str, Any] | None) -> list[FileChange]:
    """Convert GitHub validation metadata into scorer file-change records."""
    if not metadata:
        return []

    changed_files = metadata.get("changed_files")
    if isinstance(changed_files, list) and changed_files:
        result: list[FileChange] = []
        for entry in changed_files:
            if not isinstance(entry, dict):
                continue
            filename = entry.get("filename")
            if not isinstance(filename, str) or not filename.strip():
                continue
            result.append(
                FileChange(
                    filepath=filename.strip(),
                    lines_added=int(entry.get("additions") or 0),
                    lines_deleted=int(entry.get("deletions") or 0),
                )
            )
        if result:
            return result

    file_names = metadata.get("changed_file_names")
    if isinstance(file_names, list) and file_names:
        lines_added = int(metadata.get("lines_added") or 0)
        lines_deleted = int(metadata.get("lines_deleted") or 0)
        per_file_added = lines_added // len(file_names) if file_names else 0
        per_file_deleted = lines_deleted // len(file_names) if file_names else 0
        return [
            FileChange(
                filepath=str(name),
                lines_added=per_file_added,
                lines_deleted=per_file_deleted,
            )
            for name in file_names
            if isinstance(name, str) and name.strip()
        ]

    files_changed_count = int(metadata.get("files_changed_count") or 0)
    if files_changed_count <= 0:
        return []

    lines_added = int(metadata.get("lines_added") or 0)
    lines_deleted = int(metadata.get("lines_deleted") or 0)
    return [
        FileChange(
            filepath=f"unknown-file-{index + 1}",
            lines_added=lines_added // files_changed_count,
            lines_deleted=lines_deleted // files_changed_count,
        )
        for index in range(files_changed_count)
    ]


def score_release_from_github_metadata(
    metadata: dict[str, Any] | None,
    historical_failure_rates: dict[str, float] | None = None,
    *,
    scorer: ReleaseRiskScorer | None = None,
) -> RiskResult:
    """Score a release using GitHub PR change metadata from the orchestrator."""
    changed_files = build_file_changes_from_github_metadata(metadata)
    active_scorer = scorer or ReleaseRiskScorer()
    return active_scorer.score(changed_files, historical_failure_rates)
