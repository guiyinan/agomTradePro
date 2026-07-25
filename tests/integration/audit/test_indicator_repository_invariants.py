"""Persistence invariants for Audit indicator evaluation and weight adjustment."""

from datetime import date

import pytest
from django.db import IntegrityError, transaction

from apps.audit.application.indicator_use_cases import (
    AdjustIndicatorWeightsRequest,
    AdjustIndicatorWeightsUseCase,
)
from apps.audit.infrastructure.models import (
    IndicatorPerformanceModel,
    IndicatorThresholdConfigModel,
    ValidationSummaryModel,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository


@pytest.mark.django_db
def test_performance_query_is_run_scoped_and_preserves_zero_metrics() -> None:
    """Concurrent runs for one period must not mix, and zero is not missing."""

    repository = DjangoAuditRepository()
    common = {
        "indicator_code": "RUN_SCOPED_PMI",
        "evaluation_period_start": date(2026, 1, 1),
        "evaluation_period_end": date(2026, 6, 30),
        "precision": 0.0,
        "recall": 0.0,
        "f1_score": 0.0,
        "stability_score": 0.0,
        "recommended_action": "KEEP",
        "recommended_weight": 0.0,
        "confidence_level": 0.0,
        "decay_rate": 0.0,
    }
    IndicatorPerformanceModel._default_manager.create(
        validation_run_id="run-a",
        **common,
    )
    IndicatorPerformanceModel._default_manager.create(
        validation_run_id="run-b",
        **common,
    )

    reports = repository.get_indicator_performance_reports(
        validation_run_id="run-a",
        limit=None,
    )

    assert len(reports) == 1
    assert reports[0]["validation_run_id"] == "run-a"
    for field in (
        "precision",
        "recall",
        "f1_score",
        "stability_score",
        "recommended_weight",
        "confidence_level",
        "decay_rate",
    ):
        assert reports[0][field] == 0.0


@pytest.mark.django_db
def test_validation_run_rejects_duplicate_indicator_report() -> None:
    """One validation run must contain at most one report per indicator."""

    common = {
        "validation_run_id": "unique-run",
        "indicator_code": "UNIQUE_PMI",
        "evaluation_period_start": date(2026, 1, 1),
        "evaluation_period_end": date(2026, 6, 30),
    }
    IndicatorPerformanceModel._default_manager.create(**common)

    with pytest.raises(IntegrityError), transaction.atomic():
        IndicatorPerformanceModel._default_manager.create(**common)


@pytest.mark.django_db
def test_weight_adjustment_never_falls_back_to_same_period_other_run() -> None:
    """A validation summary without linked reports must fail closed."""

    ValidationSummaryModel._default_manager.create(
        validation_run_id="run-without-reports",
        evaluation_period_start=date(2026, 1, 1),
        evaluation_period_end=date(2026, 6, 30),
        total_indicators=1,
    )
    IndicatorPerformanceModel._default_manager.create(
        validation_run_id="different-run",
        indicator_code="NO_CROSS_RUN",
        evaluation_period_start=date(2026, 1, 1),
        evaluation_period_end=date(2026, 6, 30),
        f1_score=0.8,
        stability_score=0.8,
        recommended_action="KEEP",
        recommended_weight=0.8,
        confidence_level=0.8,
    )

    response = AdjustIndicatorWeightsUseCase(DjangoAuditRepository()).execute(
        AdjustIndicatorWeightsRequest("run-without-reports")
    )

    assert response.success is False
    assert response.adjusted_weights is None
    assert response.error is not None
    assert "批次关联" in response.error


@pytest.mark.django_db
def test_threshold_updates_reject_inactive_out_of_range_and_non_finite_values() -> None:
    """Repository updates cannot bypass active state or configured bounds."""

    config = IndicatorThresholdConfigModel._default_manager.create(
        indicator_code="WEIGHT_GUARD",
        indicator_name="Weight guard",
        level_low=40.0,
        level_high=60.0,
        base_weight=0.5,
        min_weight=0.2,
        max_weight=0.8,
        is_active=True,
    )
    repository = DjangoAuditRepository()

    assert repository.update_threshold_config_weight("WEIGHT_GUARD", float("nan")) is False
    assert repository.update_threshold_config_weight("WEIGHT_GUARD", 0.9) is False
    assert (
        repository.update_threshold_config_levels("WEIGHT_GUARD", level_low=60.0, level_high=40.0)
        is False
    )
    assert repository.update_threshold_config_weight("WEIGHT_GUARD", 0.2) is True

    config.refresh_from_db()
    assert config.base_weight == 0.2
    assert config.level_low == 40.0
    assert config.level_high == 60.0

    config.is_active = False
    config.save(update_fields=["is_active"])
    assert repository.update_threshold_config_weight("WEIGHT_GUARD", 0.4) is False


@pytest.mark.django_db
def test_performance_write_rejects_invalid_dates_counts_and_nan() -> None:
    """Direct repository calls cannot persist malformed evaluation evidence."""

    repository = DjangoAuditRepository()
    valid_arguments = {
        "indicator_code": "WRITE_GUARD",
        "evaluation_period_start": date(2026, 1, 1),
        "evaluation_period_end": date(2026, 6, 30),
    }

    with pytest.raises(ValueError, match="start"):
        repository.save_indicator_performance_record(
            **{
                **valid_arguments,
                "evaluation_period_start": date(2026, 7, 1),
            }
        )
    with pytest.raises(ValueError, match="non-negative"):
        repository.save_indicator_performance_record(
            **valid_arguments,
            analysis_details={"true_positive_count": -1},
        )
    with pytest.raises(ValueError, match="finite"):
        repository.save_indicator_performance_record(
            **valid_arguments,
            f1_score=float("nan"),
        )

    assert (
        IndicatorPerformanceModel._default_manager.filter(indicator_code="WRITE_GUARD").count() == 0
    )
