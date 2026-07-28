from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from apps.audit.infrastructure.models import (
    AttributionReport,
    ExperienceSummary,
    LossAnalysis,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.backtest.infrastructure.models import BacktestResultModel


def _create_backtest() -> BacktestResultModel:
    return BacktestResultModel._default_manager.create(
        name="Attribution repository integrity",
        status="completed",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        initial_capital=100_000,
        final_capital=110_000,
        total_return=0.1,
        annualized_return=0.1,
        max_drawdown=-0.05,
        sharpe_ratio=1.0,
        equity_curve=[],
        regime_history=[],
        trades=[],
    )


def _valid_report_kwargs(backtest_id: int) -> dict[str, object]:
    return {
        "backtest_id": backtest_id,
        "period_start": date(2025, 1, 1),
        "period_end": date(2025, 12, 31),
        "regime_timing_pnl": 0.0,
        "asset_selection_pnl": 0.0,
        "interaction_pnl": 0.0,
        "total_pnl": 0.0,
        "regime_accuracy": 0.0,
        "regime_predicted": "Recovery",
        "regime_actual": "EXTRAPOLATED:Recovery:2024-12-31",
        "attribution_method": "heuristic",
    }


@pytest.mark.django_db
def test_database_health_probe_returns_no_connection_name_or_path() -> None:
    payload = DjangoAuditRepository().get_database_health()

    assert payload["database"] == "reachable"
    assert payload["engine"] in {"sqlite", "postgresql"}
    assert "://" not in str(payload)
    assert "test_" not in str(payload)


@pytest.mark.django_db
def test_zero_attribution_values_remain_real_zeroes() -> None:
    backtest = _create_backtest()
    repository = DjangoAuditRepository()
    report_id = repository.save_attribution_report(**cast(Any, _valid_report_kwargs(backtest.pk)))

    payload = repository.get_attribution_report(report_id)

    assert payload is not None
    assert payload["regime_timing_pnl"] == 0.0
    assert payload["asset_selection_pnl"] == 0.0
    assert payload["interaction_pnl"] == 0.0
    assert payload["total_pnl"] == 0.0
    assert payload["regime_accuracy"] == 0.0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("backtest_id", True, "backtest_id"),
        ("backtest_id", 0, "backtest_id"),
        ("period_end", date(2024, 12, 31), "period_start"),
        ("regime_timing_pnl", float("nan"), "regime_timing_pnl"),
        ("asset_selection_pnl", float("inf"), "asset_selection_pnl"),
        ("interaction_pnl", float("-inf"), "interaction_pnl"),
        ("total_pnl", float("nan"), "total_pnl"),
        ("regime_accuracy", -0.1, "regime_accuracy"),
        ("regime_accuracy", 1.1, "regime_accuracy"),
        ("regime_predicted", "../Recovery", "regime_predicted"),
        ("regime_actual", "bad regime", "regime_actual"),
        ("regime_actual", "A" * 65, "regime_actual"),
        ("attribution_method", "guess", "attribution_method"),
    ],
)
def test_invalid_attribution_evidence_is_rejected_before_insert(
    field: str,
    value: object,
    message: str,
) -> None:
    backtest = _create_backtest()
    kwargs = _valid_report_kwargs(backtest.pk)
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        DjangoAuditRepository().save_attribution_report(**cast(Any, kwargs))

    assert AttributionReport._default_manager.count() == 0


@pytest.mark.django_db
def test_corrupted_historical_report_is_excluded_from_all_payload_queries() -> None:
    backtest = _create_backtest()
    valid = AttributionReport._default_manager.create(
        backtest=backtest,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        regime_timing_pnl=0.01,
        asset_selection_pnl=0.02,
        interaction_pnl=0.0,
        total_pnl=0.03,
        regime_accuracy=0.8,
        regime_predicted="Recovery",
        regime_actual="Recovery",
    )
    corrupted = AttributionReport._default_manager.create(
        backtest=backtest,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        regime_timing_pnl=float("inf"),
        asset_selection_pnl=0.0,
        interaction_pnl=0.0,
        total_pnl=0.0,
        regime_accuracy=0.8,
        regime_predicted="Recovery",
        regime_actual="Recovery",
    )
    repository = DjangoAuditRepository()

    assert repository.get_attribution_report(corrupted.pk) is None
    assert [row["id"] for row in repository.get_reports_by_backtest(backtest.pk)] == [valid.pk]
    assert [
        row["id"]
        for row in repository.get_reports_by_date_range(
            date(2025, 1, 1),
            date(2025, 12, 31),
        )
    ] == [valid.pk]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("report_id", 0, "report_id"),
        ("loss_source", "OTHER", "loss_source"),
        ("impact", float("nan"), "impact"),
        ("impact_percentage", -0.1, "impact_percentage"),
        ("description", "", "description"),
    ],
)
def test_invalid_loss_evidence_is_rejected_before_insert(
    field: str,
    value: object,
    message: str,
) -> None:
    backtest = _create_backtest()
    report = AttributionReport._default_manager.create(
        backtest=backtest,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        regime_timing_pnl=0.0,
        asset_selection_pnl=0.0,
        interaction_pnl=0.0,
        total_pnl=0.0,
        regime_accuracy=0.5,
        regime_predicted="Recovery",
    )
    kwargs: dict[str, object] = {
        "report_id": report.pk,
        "loss_source": "REGIME_ERROR",
        "impact": -0.1,
        "impact_percentage": 10.0,
        "description": "Regime mismatch",
        "improvement_suggestion": "Tighten the invalidation rule.",
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        DjangoAuditRepository().save_loss_analysis(**cast(Any, kwargs))

    assert LossAnalysis._default_manager.count() == 0


@pytest.mark.django_db
def test_corrupted_historical_loss_metric_is_excluded() -> None:
    backtest = _create_backtest()
    report = AttributionReport._default_manager.create(
        backtest=backtest,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        regime_timing_pnl=0.0,
        asset_selection_pnl=0.0,
        interaction_pnl=0.0,
        total_pnl=0.0,
        regime_accuracy=0.5,
        regime_predicted="Recovery",
    )
    valid = LossAnalysis._default_manager.create(
        report=report,
        loss_source="REGIME_ERROR",
        impact=-0.1,
        impact_percentage=10.0,
        description="Valid",
    )
    LossAnalysis._default_manager.create(
        report=report,
        loss_source="TIMING_ERROR",
        impact=float("inf"),
        impact_percentage=20.0,
        description="Corrupted",
    )

    payloads = DjangoAuditRepository().get_loss_analyses(report.pk)

    assert [payload["id"] for payload in payloads] == [valid.pk]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("report_id", 0, "report_id"),
        ("lesson", "", "lesson"),
        ("recommendation", "", "recommendation"),
        ("priority", "URGENT", "priority"),
    ],
)
def test_invalid_experience_evidence_is_rejected_before_insert(
    field: str,
    value: object,
    message: str,
) -> None:
    backtest = _create_backtest()
    report = AttributionReport._default_manager.create(
        backtest=backtest,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        regime_timing_pnl=0.0,
        asset_selection_pnl=0.0,
        interaction_pnl=0.0,
        total_pnl=0.0,
        regime_accuracy=0.5,
        regime_predicted="Recovery",
    )
    kwargs: dict[str, object] = {
        "report_id": report.pk,
        "lesson": "Respect the regime gate.",
        "recommendation": "Require stronger invalidation evidence.",
        "priority": "HIGH",
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        DjangoAuditRepository().save_experience_summary(**cast(Any, kwargs))

    assert ExperienceSummary._default_manager.count() == 0


@pytest.mark.django_db
def test_lookup_scopes_and_record_limit_fail_closed() -> None:
    repository = DjangoAuditRepository()

    assert repository.get_attribution_report(0) is None
    assert repository.get_attribution_report_record(True) is None
    assert repository.get_reports_by_backtest(-1) == []
    assert repository.get_loss_analyses(0) == []
    assert repository.get_experience_summaries(0) == []
    with pytest.raises(ValueError, match="limit"):
        repository.list_attribution_report_records(limit=501)
