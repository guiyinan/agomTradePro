"""Safety boundaries for forecast-ledger application use cases."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from apps.signal.application.forecast_use_cases import (
    FinalizeForecastOutcomeUseCase,
    RecordForecastEvaluationUseCase,
    RecordForecastLedgerEntryUseCase,
)


class _ForecastRepository:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None
        self.evaluated: dict[str, Any] | None = None
        self.finalized: dict[str, Any] | None = None

    def create_entry(self, **kwargs: Any) -> Any:
        self.created = kwargs
        return SimpleNamespace(entry_id=kwargs.get("entry_id", "generated"), status="open")

    def record_evaluation(self, **kwargs: Any) -> Any:
        self.evaluated = kwargs
        return SimpleNamespace(
            evaluation_id="evaluation-1",
            triggered=kwargs["triggered"],
            status_transition="",
        )

    def finalize_outcome(self, **kwargs: Any) -> Any:
        self.finalized = kwargs
        return SimpleNamespace(
            entry_id=kwargs["entry_id"],
            outcome_type=kwargs["outcome_type"],
            hit=None,
            brier_score=None,
        )


def _entry_payload() -> dict[str, Any]:
    published_at = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "entry_id": "forecast-1",
        "published_at": published_at,
        "direction": "LONG",
        "asset_code": "000001.SZ",
        "horizon_end": published_at + timedelta(days=30),
        "benchmark_asset": "000300.SH",
        "probability": 0.8,
        "invalidation_rule_version": "rule-v1",
        "decision_snapshot_id": "decision-v1",
        "pit_manifest_id": "manifest-v1",
        "source": "strategy",
    }


@pytest.mark.parametrize("probability", [True, float("nan"), float("inf"), -0.1, 1.1])
def test_forecast_entry_rejects_invalid_probability_before_repository(
    probability: object,
) -> None:
    repository = _ForecastRepository()

    with pytest.raises(ValueError, match="probability"):
        RecordForecastLedgerEntryUseCase(repository).execute(
            **{**_entry_payload(), "probability": probability}
        )

    assert repository.created is None


def test_forecast_entry_normalizes_codes_and_rejects_unknown_fields() -> None:
    repository = _ForecastRepository()
    payload = _entry_payload()
    payload["asset_code"] = " 000001.sz "
    payload["benchmark_asset"] = " 000300.sh "

    RecordForecastLedgerEntryUseCase(repository).execute(**payload)

    assert repository.created is not None
    assert repository.created["asset_code"] == "000001.SZ"
    assert repository.created["benchmark_asset"] == "000300.SH"
    with pytest.raises(ValueError, match="unsupported forecast fields"):
        RecordForecastLedgerEntryUseCase(repository).execute(**{**payload, "unexpected": "value"})


@pytest.mark.parametrize("data_version_ids", [[True], [0], [-1], [1, 1]])
def test_forecast_evaluation_rejects_invalid_data_versions(
    data_version_ids: list[Any],
) -> None:
    repository = _ForecastRepository()

    with pytest.raises(ValueError, match="data_version_ids"):
        RecordForecastEvaluationUseCase(repository).execute(
            entry_id="forecast-1",
            checked_at=datetime(2026, 1, 2, tzinfo=UTC),
            data_version_ids=data_version_ids,
            conditions=[],
        )

    assert repository.evaluated is None


def test_forecast_evaluation_requires_boolean_triggered_value() -> None:
    repository = _ForecastRepository()

    with pytest.raises(ValueError, match="triggered must be boolean"):
        RecordForecastEvaluationUseCase(repository).execute(
            entry_id="forecast-1",
            checked_at=datetime(2026, 1, 2, tzinfo=UTC),
            data_version_ids=[1],
            conditions=[{"triggered": "yes"}],
        )

    assert repository.evaluated is None


def test_forecast_evaluation_rejects_oversized_combined_conditions() -> None:
    repository = _ForecastRepository()

    with pytest.raises(ValueError, match="conditions exceeds"):
        RecordForecastEvaluationUseCase(repository).execute(
            entry_id="forecast-1",
            checked_at=datetime(2026, 1, 2, tzinfo=UTC),
            data_version_ids=[1],
            conditions=[
                {"name": "first", "detail": "x" * 40_000},
                {"name": "second", "detail": "y" * 40_000},
            ],
        )

    assert repository.evaluated is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("neutral_band", float("nan")),
        ("neutral_band", float("inf")),
        ("asset_return", float("nan")),
        ("benchmark_return", float("-inf")),
    ],
)
def test_forecast_outcome_rejects_nonfinite_values(field: str, value: float) -> None:
    repository = _ForecastRepository()
    payload: dict[str, Any] = {
        "entry_id": "forecast-1",
        "finalized_at": datetime(2026, 2, 1, tzinfo=UTC),
        "outcome_type": "expired",
        "asset_return": 0.1,
        "benchmark_return": 0.04,
        "neutral_band": 0.01,
    }
    payload[field] = value

    with pytest.raises(ValueError, match=field):
        FinalizeForecastOutcomeUseCase(repository).execute(**payload)

    assert repository.finalized is None


def test_forecast_outcome_rejects_oversized_evidence() -> None:
    repository = _ForecastRepository()

    with pytest.raises(ValueError, match="evidence exceeds"):
        FinalizeForecastOutcomeUseCase(repository).execute(
            entry_id="forecast-1",
            finalized_at=datetime(2026, 2, 1, tzinfo=UTC),
            outcome_type="expired",
            asset_return=0.1,
            benchmark_return=0.04,
            neutral_band=0.01,
            evidence={"payload": "x" * 70_000},
        )

    assert repository.finalized is None
