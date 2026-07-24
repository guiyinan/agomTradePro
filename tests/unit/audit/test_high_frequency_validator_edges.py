"""Deterministic validation contracts for the high-frequency indicator command."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from apps.audit.management.commands import validate_high_frequency_indicators as module


class _Query(list[SimpleNamespace]):
    def order_by(self, *args: str) -> _Query:
        return self

    def count(self) -> int:
        return len(self)

    def exists(self) -> bool:
        return bool(self)


class _MacroManager:
    def __init__(self, rows: dict[str, list[SimpleNamespace]]) -> None:
        self.rows = rows

    def filter(self, **kwargs: object) -> _Query:
        return _Query(self.rows.get(str(kwargs.get("indicator_code")), []))


class _RegimeManager:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def filter(self, **kwargs: object) -> _Query:
        return _Query(self.rows)


def test_validator_checks_availability_correlation_event_study_and_report(monkeypatch) -> None:
    """Available data produces an auditable correlation and inversion-event report."""
    start = date(2026, 1, 1)
    days = [start + timedelta(days=index) for index in range(120)]
    macro_rows = {
        code: [
            SimpleNamespace(
                reporting_period=day,
                value=(-1.0 if 20 <= index < 30 else float(index % 4)),
            )
            for index, day in enumerate(days)
        ]
        for code in module.IndicatorValidator.HIGH_FREQ_INDICATORS
    }
    regimes = [
        SimpleNamespace(
            observed_at=day,
            dominant_regime=(
                "Deflation" if index >= 25 else ("Recovery", "Overheat", "Stagflation")[index % 3]
            ),
        )
        for index, day in enumerate(days)
    ]
    monkeypatch.setattr(
        module,
        "MacroFactModel",
        SimpleNamespace(_default_manager=_MacroManager(macro_rows)),
    )
    monkeypatch.setattr(
        module,
        "RegimeLog",
        SimpleNamespace(_default_manager=_RegimeManager(regimes)),
    )
    monkeypatch.setattr(module.stats, "pearsonr", lambda left, right: (0.5, 0.01))

    validator = module.IndicatorValidator(
        start,
        days[-1],
        {"min_data_points": 100, "max_p_value": 0.05},
    )
    availability = validator.check_data_availability()
    assert all(result["status"] == "OK" for result in availability.values())
    correlated = validator.calculate_correlation_with_regime()
    assert all(result["correlation_significant"] for result in correlated.values())
    event_study = validator.event_study_term_spread()
    assert event_study["status"] == "OK"
    assert event_study["total_inversions"] == 1
    assert event_study["events"][0]["recession_occurred"] is True

    report = validator.generate_validation_report()
    assert report["approved_indicators"] == len(validator.HIGH_FREQ_INDICATORS)
    assert report["overall_recommendation"] == "建议进入 Phase 1 开发阶段"
    assert report["avg_f1_score"] is not None


def test_validator_reports_missing_insufficient_and_error_inputs(monkeypatch) -> None:
    """Missing and failing providers are classified without fabricating approval."""
    start = date(2026, 1, 1)
    validator = module.IndicatorValidator(start, start, {"min_data_points": 2})
    monkeypatch.setattr(
        module,
        "MacroFactModel",
        SimpleNamespace(_default_manager=_MacroManager({})),
    )
    availability = validator.check_data_availability()
    assert all(result["status"] == "NO_DATA" for result in availability.values())
    assert validator.event_study_term_spread()["status"] == "INSUFFICIENT_DATA"

    monkeypatch.setattr(
        module,
        "RegimeLog",
        SimpleNamespace(_default_manager=_RegimeManager([])),
    )
    assert validator.calculate_correlation_with_regime() == {}
    report = validator.generate_validation_report()
    assert report["approved_indicators"] == 0
    assert report["rejected_indicators"] == len(validator.HIGH_FREQ_INDICATORS)
    assert report["overall_recommendation"] == "建议重新评估指标选择或数据源"
