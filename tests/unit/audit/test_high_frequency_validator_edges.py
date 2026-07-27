"""Deterministic validation contracts for the high-frequency indicator command."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

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
    indicator_codes = ("CN_TERM_SPREAD_10Y1Y", "CN_BOND_10Y", "VIX_INDEX")
    macro_rows = {
        code: [
            SimpleNamespace(
                reporting_period=day,
                value=(-1.0 if 20 <= index < 30 else float(index % 4)),
            )
            for index, day in enumerate(days)
        ]
        for code in indicator_codes
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
    monkeypatch.setattr(module, "_pearsonr", lambda left, right: (0.5, 0.01))

    validator = module.IndicatorValidator(
        start,
        days[-1],
        indicator_codes,
        module.ValidationThresholds(
            min_data_points=100,
            min_correlation=0.3,
            max_p_value=0.05,
            min_years=0.0,
        ),
        term_spread_indicator="CN_TERM_SPREAD_10Y1Y",
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
    assert report["approved_indicators"] == len(indicator_codes)
    assert report["overall_recommendation"] == "建议进入 Phase 1 开发阶段"
    assert report["avg_f1_score"] is None
    assert report["avg_stability_score"] is None


def test_validator_reports_missing_insufficient_and_error_inputs(monkeypatch) -> None:
    """Missing and failing providers are classified without fabricating approval."""
    start = date(2026, 1, 1)
    indicator_codes = ("CN_TERM_SPREAD_10Y1Y", "VIX_INDEX")
    validator = module.IndicatorValidator(
        start,
        start,
        indicator_codes,
        module.ValidationThresholds(min_data_points=2, min_years=0.0),
        term_spread_indicator="CN_TERM_SPREAD_10Y1Y",
    )
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
    correlated = validator.calculate_correlation_with_regime()
    assert all(result["status"] == "NO_DATA" for result in correlated.values())
    report = validator.generate_validation_report()
    assert report["approved_indicators"] == 0
    assert report["rejected_indicators"] == len(indicator_codes)
    assert report["overall_recommendation"] == "建议重新评估指标选择或数据源"


def test_validator_never_approves_missing_or_below_threshold_correlation(monkeypatch) -> None:
    """Availability alone cannot approve an indicator, and min_correlation is enforced."""

    start = date(2026, 1, 1)
    days = [start + timedelta(days=index) for index in range(20)]
    rows = {
        "TEST_DAILY": [
            SimpleNamespace(reporting_period=day, value=float(index % 3))
            for index, day in enumerate(days)
        ]
    }
    monkeypatch.setattr(
        module,
        "MacroFactModel",
        SimpleNamespace(_default_manager=_MacroManager(rows)),
    )
    monkeypatch.setattr(
        module,
        "RegimeLog",
        SimpleNamespace(
            _default_manager=_RegimeManager(
                [SimpleNamespace(observed_at=day, dominant_regime="Recovery") for day in days]
            )
        ),
    )
    validator = module.IndicatorValidator(
        start,
        days[-1],
        ("TEST_DAILY",),
        module.ValidationThresholds(
            min_data_points=10,
            min_correlation=0.3,
            max_p_value=0.05,
            min_years=0.0,
        ),
    )
    validator.check_data_availability()

    missing_report = validator.generate_validation_report()
    assert missing_report["approved_indicators"] == 0
    assert missing_report["pending_indicators"] == 1

    monkeypatch.setattr(module, "_pearsonr", lambda left, right: (0.2, 0.01))
    validator.calculate_correlation_with_regime()
    below_threshold_report = validator.generate_validation_report()
    assert below_threshold_report["approved_indicators"] == 0
    assert below_threshold_report["pending_indicators"] == 1


def test_command_resolves_governed_catalog_and_surfaces_save_failure(monkeypatch) -> None:
    """Default scope comes from Data Center governance and persistence never fails silently."""

    class _CatalogQuery(list[tuple[str, dict[str, object]]]):
        def values_list(self, *fields: str) -> _CatalogQuery:
            assert fields == ("code", "extra")
            return self

    class _CatalogManager:
        def filter(self, **kwargs: object) -> _CatalogQuery:
            assert kwargs == {
                "is_active": True,
                "default_period_type__in": ("D", "W"),
            }
            return _CatalogQuery(
                [
                    ("ACTIVE_DAILY", {}),
                    ("UNSUPPORTED", {"governance_sync_supported": False}),
                ]
            )

    monkeypatch.setattr(
        module,
        "IndicatorCatalogModel",
        SimpleNamespace(_default_manager=_CatalogManager()),
    )
    assert module.Command._resolve_indicator_codes(None) == ("ACTIVE_DAILY",)
    assert module.Command._resolve_indicator_codes(" A, B, A ") == ("A", "B")
    assert not hasattr(module.IndicatorValidator, "HIGH_FREQ_INDICATORS")

    command = module.Command()
    report = {
        "validation_run_id": "run-1",
        "total_indicators": 1,
        "approved_indicators": 0,
        "rejected_indicators": 0,
        "pending_indicators": 1,
        "avg_f1_score": None,
        "avg_stability_score": None,
        "overall_recommendation": "pending",
        "detailed_results": {},
    }
    monkeypatch.setattr(
        module,
        "ValidationSummaryModel",
        SimpleNamespace(
            _default_manager=SimpleNamespace(
                create=lambda **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("token=should-not-appear")
                )
            )
        ),
    )
    with pytest.raises(CommandError, match="RuntimeError") as exc_info:
        command._save_report(report, date(2026, 1, 1), date(2026, 1, 31))
    assert "should-not-appear" not in str(exc_info.value)
