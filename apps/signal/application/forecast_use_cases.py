"""Application orchestration for complete forecast evaluation trails."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

_ENTRY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_ASSET_CODE_PATTERN = re.compile(r"^[A-Z0-9._-]+$")
_ENTRY_DIRECTIONS = frozenset({"LONG", "SHORT", "NEUTRAL"})
_OUTCOME_TYPES = frozenset({"expired", "invalidated", "exited", "data_insufficient"})
_MAX_DATA_VERSION_IDS = 1000
_MAX_CONDITIONS = 500
_MAX_JSON_BYTES = 65_536


class ForecastEvaluationGateway(Protocol):
    """Persistence boundary for the append-only forecast ledger."""

    def create_entry(self, **kwargs: Any) -> Any: ...

    def record_evaluation(
        self,
        *,
        entry_id: str,
        checked_at: datetime,
        data_version_ids: list[int],
        conditions: list[dict[str, Any]],
        triggered: bool,
        missing_reason: str,
    ) -> Any: ...

    def finalize_outcome(
        self,
        *,
        entry_id: str,
        finalized_at: datetime,
        outcome_type: str,
        asset_return: float | None,
        benchmark_return: float | None,
        neutral_band: float,
        evidence: dict[str, Any],
    ) -> Any: ...


def _bounded_text(
    value: object,
    field: str,
    *,
    maximum: int,
    allow_blank: bool = False,
) -> str:
    """Normalize one bounded text field."""

    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized and not allow_blank:
        raise ValueError(f"{field} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _aware_datetime(value: object, field: str) -> datetime:
    """Require one timezone-aware datetime."""

    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _finite_float(value: object, field: str) -> float:
    """Require a finite non-boolean numeric value."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be finite")
    return normalized


def _validate_json_size(value: object, field: str) -> None:
    """Require JSON-compatible content within the shared byte limit."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain JSON-compatible values") from exc
    if len(encoded) > _MAX_JSON_BYTES:
        raise ValueError(f"{field} exceeds {_MAX_JSON_BYTES} bytes")


def _json_object(value: object, field: str) -> dict[str, Any]:
    """Validate a bounded JSON object and return a plain dictionary."""

    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    normalized = dict(value)
    _validate_json_size(normalized, field)
    return normalized


def _entry_id(value: object) -> str:
    """Normalize a forecast entry identifier."""

    normalized = _bounded_text(value, "entry_id", maximum=64)
    if _ENTRY_ID_PATTERN.fullmatch(normalized) is None:
        raise ValueError("entry_id contains unsupported characters")
    return normalized


class RecordForecastLedgerEntryUseCase:
    """Freeze all fields needed to score a signal at publication time."""

    def __init__(self, repository: ForecastEvaluationGateway) -> None:
        self._repository = repository

    def execute(self, **payload: Any) -> Any:
        """Validate and freeze one forecast publication."""

        required_fields = {
            "published_at",
            "direction",
            "asset_code",
            "horizon_end",
            "benchmark_asset",
            "probability",
            "invalidation_rule_version",
            "decision_snapshot_id",
            "pit_manifest_id",
            "source",
        }
        optional_fields = {
            "entry_id",
            "signal_id",
            "strategy_version",
            "model_version",
            "prompt_version",
            "regime",
        }
        unknown_fields = set(payload) - required_fields - optional_fields
        if unknown_fields:
            raise ValueError(f"unsupported forecast fields: {', '.join(sorted(unknown_fields))}")
        missing_fields = required_fields - set(payload)
        if missing_fields:
            raise ValueError(f"missing forecast fields: {', '.join(sorted(missing_fields))}")

        published_at = _aware_datetime(payload["published_at"], "published_at")
        horizon_end = _aware_datetime(payload["horizon_end"], "horizon_end")
        if horizon_end <= published_at:
            raise ValueError("horizon_end must be after published_at")

        probability = _finite_float(payload["probability"], "probability")
        if not 0 <= probability <= 1:
            raise ValueError("probability must be within [0, 1]")

        direction = _bounded_text(payload["direction"], "direction", maximum=10).upper()
        if direction not in _ENTRY_DIRECTIONS:
            raise ValueError("direction must be LONG, SHORT, or NEUTRAL")
        asset_code = _bounded_text(payload["asset_code"], "asset_code", maximum=32).upper()
        benchmark_asset = _bounded_text(
            payload["benchmark_asset"], "benchmark_asset", maximum=32
        ).upper()
        if _ASSET_CODE_PATTERN.fullmatch(asset_code) is None:
            raise ValueError("asset_code contains unsupported characters")
        if _ASSET_CODE_PATTERN.fullmatch(benchmark_asset) is None:
            raise ValueError("benchmark_asset contains unsupported characters")

        signal_id = payload.get("signal_id")
        if signal_id is not None and (
            isinstance(signal_id, bool) or not isinstance(signal_id, int) or signal_id <= 0
        ):
            raise ValueError("signal_id must be a positive integer")

        normalized: dict[str, Any] = {
            "published_at": published_at,
            "direction": direction,
            "asset_code": asset_code,
            "horizon_end": horizon_end,
            "benchmark_asset": benchmark_asset,
            "probability": probability,
            "invalidation_rule_version": _bounded_text(
                payload["invalidation_rule_version"],
                "invalidation_rule_version",
                maximum=64,
            ),
            "decision_snapshot_id": _bounded_text(
                payload["decision_snapshot_id"],
                "decision_snapshot_id",
                maximum=64,
            ),
            "pit_manifest_id": _bounded_text(
                payload["pit_manifest_id"],
                "pit_manifest_id",
                maximum=64,
            ),
            "strategy_version": _bounded_text(
                payload.get("strategy_version", ""),
                "strategy_version",
                maximum=64,
                allow_blank=True,
            ),
            "model_version": _bounded_text(
                payload.get("model_version", ""),
                "model_version",
                maximum=64,
                allow_blank=True,
            ),
            "prompt_version": _bounded_text(
                payload.get("prompt_version", ""),
                "prompt_version",
                maximum=64,
                allow_blank=True,
            ),
            "source": _bounded_text(payload["source"], "source", maximum=64),
            "regime": _bounded_text(
                payload.get("regime", ""),
                "regime",
                maximum=32,
                allow_blank=True,
            ),
        }
        if "entry_id" in payload:
            normalized["entry_id"] = _entry_id(payload["entry_id"])
        if signal_id is not None:
            normalized["signal_id"] = signal_id
        return self._repository.create_entry(**normalized)


class RecordForecastEvaluationUseCase:
    """Append every scheduled check idempotently, including missing-data checks."""

    def __init__(self, repository: ForecastEvaluationGateway) -> None:
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
        """Validate and append one scheduled forecast evaluation."""

        normalized_entry_id = _entry_id(entry_id)
        normalized_checked_at = _aware_datetime(checked_at, "checked_at")
        if len(data_version_ids) > _MAX_DATA_VERSION_IDS:
            raise ValueError(f"data_version_ids exceeds {_MAX_DATA_VERSION_IDS} items")
        if any(
            isinstance(version_id, bool) or not isinstance(version_id, int) or version_id <= 0
            for version_id in data_version_ids
        ):
            raise ValueError("data_version_ids must contain positive integers")
        if len(set(data_version_ids)) != len(data_version_ids):
            raise ValueError("data_version_ids must not contain duplicates")
        if len(conditions) > _MAX_CONDITIONS:
            raise ValueError(f"conditions exceeds {_MAX_CONDITIONS} items")
        normalized_conditions = [
            _json_object(condition, f"conditions[{index}]")
            for index, condition in enumerate(conditions)
        ]
        _validate_json_size(normalized_conditions, "conditions")
        for index, condition in enumerate(normalized_conditions):
            if "triggered" in condition and not isinstance(condition["triggered"], bool):
                raise ValueError(f"conditions[{index}].triggered must be boolean")
        normalized_missing_reason = _bounded_text(
            missing_reason,
            "missing_reason",
            maximum=2000,
            allow_blank=True,
        )
        if not data_version_ids and not normalized_missing_reason:
            raise ValueError("data_version_ids or an explicit missing_reason is required")
        triggered = any(condition.get("triggered") is True for condition in normalized_conditions)
        return self._repository.record_evaluation(
            entry_id=normalized_entry_id,
            checked_at=normalized_checked_at,
            data_version_ids=list(data_version_ids),
            conditions=normalized_conditions,
            triggered=triggered,
            missing_reason=normalized_missing_reason,
        )


class FinalizeForecastOutcomeUseCase:
    """Score finalized LONG/SHORT/NEUTRAL forecasts against their benchmark."""

    def __init__(self, repository: ForecastEvaluationGateway) -> None:
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
        """Validate and persist one immutable forecast outcome."""

        normalized_entry_id = _entry_id(entry_id)
        normalized_finalized_at = _aware_datetime(finalized_at, "finalized_at")
        normalized_neutral_band = _finite_float(neutral_band, "neutral_band")
        if normalized_neutral_band < 0:
            raise ValueError("neutral_band must be non-negative")
        normalized_outcome_type = _bounded_text(outcome_type, "outcome_type", maximum=24)
        if normalized_outcome_type not in _OUTCOME_TYPES:
            raise ValueError("unsupported forecast outcome_type")
        normalized_asset_return = (
            None if asset_return is None else _finite_float(asset_return, "asset_return")
        )
        normalized_benchmark_return = (
            None
            if benchmark_return is None
            else _finite_float(benchmark_return, "benchmark_return")
        )
        normalized_evidence = _json_object(evidence or {}, "evidence")
        return self._repository.finalize_outcome(
            entry_id=normalized_entry_id,
            finalized_at=normalized_finalized_at,
            outcome_type=normalized_outcome_type,
            asset_return=normalized_asset_return,
            benchmark_return=normalized_benchmark_return,
            neutral_band=normalized_neutral_band,
            evidence=normalized_evidence,
        )
