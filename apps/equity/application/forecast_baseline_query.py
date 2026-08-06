"""Read-only application contracts for exact forecast-baseline trial records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.equity.domain.forecast_baseline import ForecastBaselineTrialResult

from .forecast_baseline_materialize import VersionRef


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class ExactForecastBaselineTrialRecord:
    """Typed Equity owner row restored from its complete immutable ancestry."""

    result: ForecastBaselineTrialResult
    recorded_at: datetime
    owner_record_key: int

    def __post_init__(self) -> None:
        _require_aware(self.recorded_at, "forecast baseline trial recorded_at")
        if self.result.owner != "equity":
            raise ValueError("forecast baseline trial owner must be equity")
        if self.recorded_at < self.result.evaluated_at:
            raise ValueError("forecast baseline trial receipt predates evaluation")
        if isinstance(self.owner_record_key, bool) or self.owner_record_key < 1:
            raise ValueError("forecast baseline trial owner_record_key must be positive")


class ExactForecastBaselineTrialQuery(Protocol):
    """Resolve one exact typed owner record at a knowledge-time boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Identify the owner database for opaque record bindings."""
        ...

    def get_exact(
        self,
        trial_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> ExactForecastBaselineTrialRecord | None: ...


__all__ = [
    "ExactForecastBaselineTrialQuery",
    "ExactForecastBaselineTrialRecord",
]
