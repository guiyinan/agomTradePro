"""High-frequency Regime use-case branch contracts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.regime.application.use_cases import (
    CalculateTermSpreadRequest,
    CalculateTermSpreadUseCase,
    HighFrequencySignalRequest,
    HighFrequencySignalUseCase,
    ResolveSignalConflictRequest,
    ResolveSignalConflictUseCase,
)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        get_spread_threshold_bp=lambda _default: 100.0,
        get_us_yield_threshold=lambda _default: 4.5,
        get_daily_persist_days=lambda _default: 10,
        get_conflict_confidence_boost=lambda _default: 0.2,
    )


def test_term_spread_uses_latest_fallback_and_reports_no_data() -> None:
    repository = MagicMock()
    repository.get_by_code_and_date.return_value = None
    repository.get_latest_observation.side_effect = [
        SimpleNamespace(value=3.0),
        SimpleNamespace(value=2.0),
    ]
    use_case = CalculateTermSpreadUseCase(repository)

    result = use_case.execute(CalculateTermSpreadRequest(as_of_date=date(2026, 7, 1)))
    assert result.success is True
    assert result.spread_value == 100.0
    assert result.curve_shape == "STEEP"

    repository.get_latest_observation.side_effect = [None, None]
    missing = use_case.execute(CalculateTermSpreadRequest(as_of_date=date(2026, 7, 1)))
    assert missing.success is False
    assert missing.curve_shape == "NO_DATA"


@pytest.mark.parametrize(
    ("long_yield", "short_yield", "shape", "inverted"),
    [
        (2.0, 3.0, "INVERTED", True),
        (3.00001, 3.0, "FLAT", False),
        (3.01, 3.0, "NORMAL", False),
        (4.0, 2.0, "STEEP", False),
    ],
)
def test_term_spread_classifies_curve_shapes(
    long_yield: float,
    short_yield: float,
    shape: str,
    inverted: bool,
) -> None:
    repository = MagicMock()
    repository.get_by_code_and_date.side_effect = [
        SimpleNamespace(value=long_yield),
        SimpleNamespace(value=short_yield),
    ]
    result = CalculateTermSpreadUseCase(repository).execute(
        CalculateTermSpreadRequest(as_of_date=date(2026, 7, 1))
    )
    assert result.curve_shape == shape
    assert result.is_inverted is inverted
    if inverted:
        assert result.inversion_severity > 0


def test_term_spread_isolates_repository_errors() -> None:
    repository = MagicMock()
    repository.get_by_code_and_date.side_effect = RuntimeError("db down")
    result = CalculateTermSpreadUseCase(repository).execute(
        CalculateTermSpreadRequest(as_of_date=date(2026, 7, 1))
    )
    assert result.success is False
    assert result.curve_shape == "ERROR"
    assert result.error == "db down"


def test_high_frequency_signal_aggregates_three_indicators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_case = HighFrequencySignalUseCase(MagicMock(), _config())
    monkeypatch.setattr(
        use_case,
        "_evaluate_term_spread",
        lambda _date: {
            "success": True,
            "spread_value": 150,
            "is_inverted": False,
            "signal": "BULLISH",
        },
    )
    monkeypatch.setattr(
        use_case,
        "_evaluate_nhci",
        lambda _date, _days: {
            "success": True,
            "current_value": 120,
            "change_pct": 10,
            "signal": "BULLISH",
            "score": 1.0,
        },
    )
    monkeypatch.setattr(
        use_case,
        "_evaluate_us_bond",
        lambda _date: {
            "success": True,
            "value": 2.5,
            "signal": "BULLISH",
            "score": 1.0,
        },
    )

    result = use_case.execute(HighFrequencySignalRequest(as_of_date=date(2026, 7, 1)))

    assert result.success is True
    assert result.signal_direction == "BULLISH"
    assert result.signal_strength == 1.0
    assert result.confidence == pytest.approx(0.9)
    assert len(result.contributing_indicators) == 3


def test_high_frequency_signal_handles_inversion_neutral_and_no_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_case = HighFrequencySignalUseCase(MagicMock(), _config())
    monkeypatch.setattr(
        use_case,
        "_evaluate_term_spread",
        lambda _date: {
            "success": True,
            "spread_value": -20,
            "is_inverted": True,
            "signal": "BEARISH",
        },
    )
    monkeypatch.setattr(
        use_case,
        "_evaluate_nhci",
        lambda _date, _days: {"success": False},
    )
    monkeypatch.setattr(
        use_case,
        "_evaluate_us_bond",
        lambda _date: {"success": False},
    )
    bearish = use_case.execute(HighFrequencySignalRequest(as_of_date=date(2026, 7, 1)))
    assert bearish.signal_direction == "BEARISH"
    assert bearish.warning_signals == ["YIELD_CURVE_INVERTED"]
    assert bearish.confidence == 0.3

    monkeypatch.setattr(
        use_case,
        "_evaluate_term_spread",
        lambda _date: {"success": False},
    )
    no_data = use_case.execute(HighFrequencySignalRequest(as_of_date=date(2026, 7, 1)))
    assert no_data.success is False
    assert no_data.error == "No high-frequency indicators available"


def test_high_frequency_signal_isolates_unexpected_recoverable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_case = HighFrequencySignalUseCase(MagicMock(), _config())
    monkeypatch.setattr(
        use_case,
        "_evaluate_term_spread",
        lambda _date: (_ for _ in ()).throw(RuntimeError("evaluation down")),
    )
    result = use_case.execute(HighFrequencySignalRequest(as_of_date=date(2026, 7, 1)))
    assert result.success is False
    assert result.error == "evaluation down"


@pytest.mark.parametrize(
    ("value", "signal"),
    [
        (-1.0, "BEARISH"),
        (150.0, "BULLISH"),
        (50.0, "NEUTRAL"),
    ],
)
def test_term_spread_evaluator_classifies_values(value: float, signal: str) -> None:
    repository = MagicMock()
    repository.get_latest_observation.return_value = SimpleNamespace(value=value)
    use_case = HighFrequencySignalUseCase(repository, _config())
    result = use_case._evaluate_term_spread(date(2026, 7, 1))
    assert result["signal"] == signal


def test_term_spread_evaluator_handles_missing_and_error() -> None:
    repository = MagicMock()
    repository.get_latest_observation.return_value = None
    use_case = HighFrequencySignalUseCase(repository, _config())
    assert use_case._evaluate_term_spread(date(2026, 7, 1)) == {"success": False}
    repository.get_latest_observation.side_effect = RuntimeError("db down")
    assert use_case._evaluate_term_spread(date(2026, 7, 1)) == {"success": False}


@pytest.mark.parametrize(
    ("current", "past", "signal", "score"),
    [
        (110.0, 100.0, "BULLISH", 1.0),
        (90.0, 100.0, "BEARISH", -1.0),
        (102.0, 100.0, "NEUTRAL", 0.4),
    ],
)
def test_nhci_evaluator_classifies_momentum(
    current: float,
    past: float,
    signal: str,
    score: float,
) -> None:
    repository = MagicMock()
    repository.get_latest_observation.side_effect = [
        SimpleNamespace(value=current),
        SimpleNamespace(value=past),
    ]
    result = HighFrequencySignalUseCase(repository, _config())._evaluate_nhci(
        date(2026, 7, 1),
        30,
    )
    assert result["signal"] == signal
    assert result["score"] == pytest.approx(score)


def test_nhci_evaluator_handles_missing_current_past_and_error() -> None:
    repository = MagicMock()
    use_case = HighFrequencySignalUseCase(repository, _config())
    repository.get_latest_observation.return_value = None
    assert use_case._evaluate_nhci(date(2026, 7, 1), 30) == {"success": False}
    repository.get_latest_observation.side_effect = [SimpleNamespace(value=100), None]
    assert use_case._evaluate_nhci(date(2026, 7, 1), 30) == {"success": False}
    repository.get_latest_observation.side_effect = RuntimeError("db down")
    assert use_case._evaluate_nhci(date(2026, 7, 1), 30) == {"success": False}


@pytest.mark.parametrize(
    ("yield_value", "signal", "score"),
    [
        (5.0, "BEARISH", -1.0),
        (2.5, "BULLISH", 1.0),
        (3.75, "NEUTRAL", 0.0),
    ],
)
def test_us_bond_evaluator_classifies_yield_pressure(
    yield_value: float,
    signal: str,
    score: float,
) -> None:
    repository = MagicMock()
    repository.get_latest_observation.return_value = SimpleNamespace(value=yield_value)
    result = HighFrequencySignalUseCase(repository, _config())._evaluate_us_bond(
        date(2026, 7, 1)
    )
    assert result["signal"] == signal
    assert result["score"] == pytest.approx(score)


def test_us_bond_evaluator_handles_missing_and_error() -> None:
    repository = MagicMock()
    repository.get_latest_observation.return_value = None
    use_case = HighFrequencySignalUseCase(repository, _config())
    assert use_case._evaluate_us_bond(date(2026, 7, 1)) == {"success": False}
    repository.get_latest_observation.side_effect = RuntimeError("db down")
    assert use_case._evaluate_us_bond(date(2026, 7, 1)) == {"success": False}


def test_signal_conflict_weekly_and_monthly_default_paths() -> None:
    use_case = ResolveSignalConflictUseCase(_config())
    weekly = use_case.execute(
        ResolveSignalConflictRequest(
            daily_signal="BULLISH",
            daily_confidence=0.7,
            daily_duration_days=2,
            monthly_signal="BEARISH",
            monthly_confidence=0.8,
            weekly_signal="BULLISH",
        )
    )
    assert weekly.source == "DAILY_WEEKLY_CONSISTENT"

    default = use_case.execute(
        ResolveSignalConflictRequest(
            daily_signal="BULLISH",
            daily_confidence=0.7,
            daily_duration_days=2,
            monthly_signal="BEARISH",
            monthly_confidence=0.3,
        )
    )
    assert default.source == "MONTHLY_DEFAULT"
    assert default.final_confidence == 0.4
