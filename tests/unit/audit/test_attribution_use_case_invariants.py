"""Truthfulness invariants for attribution application orchestration."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from apps.audit.application.attribution_use_cases import (
    GenerateAttributionReportUseCase,
    RegimeHistoryRecord,
)


def _use_case() -> GenerateAttributionReportUseCase:
    return GenerateAttributionReportUseCase(
        audit_repository=Mock(),
        backtest_repository=Mock(),
    )


def _backtest_record(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 1,
        "name": "native-json",
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 2),
        "initial_capital": 100.0,
        "total_return": 0.1,
        "sharpe_ratio": 1.0,
        "max_drawdown": 0.0,
        "annualized_return": 0.1,
        "equity_curve": [
            {"date": "2026-01-01", "value": 100.0},
            {"date": "2026-01-02", "value": 110.0},
        ],
        "trades": [],
        "regime_history": [
            {
                "date": "2026-01-02",
                "regime": "Recovery",
                "confidence": 0.8,
            }
        ],
        "status": "completed",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_native_jsonfield_evidence_is_not_discarded() -> None:
    """Current JSONField lists must survive the legacy text compatibility path."""

    data = _use_case()._backtest_model_to_dict(_backtest_record())

    assert data["equity_curve"] == [
        (date(2026, 1, 1), 100.0),
        (date(2026, 1, 2), 110.0),
    ]
    assert data["regime_history"] == [
        {
            "date": date(2026, 1, 2),
            "regime": "Recovery",
            "dominant_regime": "Recovery",
            "confidence": 0.8,
        }
    ]


def test_regime_accuracy_uses_normalized_case_and_real_returns() -> None:
    """Canonical regime names must not fall through to the neutral fallback."""

    history: list[RegimeHistoryRecord] = [
        {
            "date": date(2026, 1, 2),
            "regime": "Recovery",
            "dominant_regime": "Recovery",
            "confidence": 0.8,
        },
        {
            "date": date(2026, 1, 3),
            "regime": "STAGFLATION",
            "dominant_regime": "STAGFLATION",
            "confidence": 0.7,
        },
    ]
    curve = [
        (date(2026, 1, 1), 100.0),
        (date(2026, 1, 2), 110.0),
        (date(2026, 1, 3), 99.0),
    ]

    assert _use_case()._calculate_regime_accuracy(history, curve) == 1.0


def test_equity_normalization_rejects_nonfinite_values() -> None:
    """Malformed persisted numbers cannot poison attribution calculations."""

    data = _use_case()._backtest_model_to_dict(
        _backtest_record(
            equity_curve=[
                [1767225600000, 100.0],
                ["2026-01-02", float("nan")],
                ["2026-01-03", float("inf")],
            ]
        )
    )

    assert data["equity_curve"] == [(date(2026, 1, 1), 100.0)]
