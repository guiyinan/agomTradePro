"""Application orchestration for complete forecast evaluation trails."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class ForecastEvaluationGateway(Protocol):
    def create_entry(self, **kwargs: Any) -> Any: ...
    def record_evaluation(self, **kwargs: Any) -> Any: ...
    def finalize_outcome(self, **kwargs: Any) -> Any: ...


class RecordForecastLedgerEntryUseCase:
    """Freeze all fields needed to score a signal at publication time."""

    def __init__(self, repository: ForecastEvaluationGateway):
        self._repository = repository

    def execute(self, **payload: Any) -> Any:
        if payload["published_at"].tzinfo is None or payload["horizon_end"].tzinfo is None:
            raise ValueError("forecast timestamps must be timezone-aware")
        probability = float(payload["probability"])
        if probability < 0 or probability > 1:
            raise ValueError("probability must be within [0, 1]")
        if payload["horizon_end"] <= payload["published_at"]:
            raise ValueError("horizon_end must be after published_at")
        for field in ("decision_snapshot_id", "pit_manifest_id", "invalidation_rule_version"):
            if not payload.get(field):
                raise ValueError(f"{field} is required")
        return self._repository.create_entry(**payload)


class RecordForecastEvaluationUseCase:
    """Append every scheduled check idempotently, including missing-data checks."""

    def __init__(self, repository: ForecastEvaluationGateway):
        self._repository = repository

    def execute(
        self,
        *,
        entry_id: str,
        checked_at: datetime,
        data_version_ids: list[int],
        conditions: list[dict[str, Any]],
        missing_reason: str = "",
    ) -> Any:
        if checked_at.tzinfo is None:
            raise ValueError("checked_at must be timezone-aware")
        if not data_version_ids and not missing_reason:
            raise ValueError("data_version_ids or an explicit missing_reason is required")
        triggered = any(bool(item.get("triggered")) for item in conditions)
        return self._repository.record_evaluation(
            entry_id=entry_id,
            checked_at=checked_at,
            data_version_ids=data_version_ids,
            conditions=conditions,
            triggered=triggered,
            missing_reason=missing_reason,
        )


class FinalizeForecastOutcomeUseCase:
    """Score finalized LONG/SHORT/NEUTRAL forecasts against their benchmark."""

    def __init__(self, repository: ForecastEvaluationGateway):
        self._repository = repository

    def execute(
        self,
        *,
        entry_id: str,
        finalized_at: datetime,
        outcome_type: str,
        asset_return: float | None,
        benchmark_return: float | None,
        neutral_band: float,
        evidence: dict[str, Any] | None = None,
    ) -> Any:
        if finalized_at.tzinfo is None:
            raise ValueError("finalized_at must be timezone-aware")
        if neutral_band < 0:
            raise ValueError("neutral_band must be non-negative")
        if outcome_type not in {"expired", "invalidated", "exited", "data_insufficient"}:
            raise ValueError("unsupported forecast outcome_type")
        return self._repository.finalize_outcome(
            entry_id=entry_id,
            finalized_at=finalized_at,
            outcome_type=outcome_type,
            asset_return=asset_return,
            benchmark_return=benchmark_return,
            neutral_band=neutral_band,
            evidence=evidence or {},
        )
