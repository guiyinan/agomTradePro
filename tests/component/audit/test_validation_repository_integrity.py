from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from apps.audit.infrastructure.models import ValidationSummaryModel
from apps.audit.infrastructure.repositories import DjangoAuditRepository


def _valid_summary_kwargs() -> dict[str, object]:
    return {
        "validation_run_id": "validation-zero-scores",
        "run_date": date(2026, 7, 28),
        "evaluation_period_start": date(2025, 1, 1),
        "evaluation_period_end": date(2025, 12, 31),
        "total_indicators": 1,
        "approved_indicators": 0,
        "rejected_indicators": 0,
        "pending_indicators": 1,
        "avg_f1_score": 0.0,
        "avg_stability_score": 0.0,
        "overall_recommendation": "Insufficient predictive power.",
        "status": "completed",
        "is_shadow_mode": False,
        "error_message": "",
    }


@pytest.mark.django_db
def test_zero_validation_scores_remain_zero_in_every_summary_projection() -> None:
    repository = DjangoAuditRepository()
    run_id = repository.save_validation_summary_record(**_valid_summary_kwargs())
    summary = ValidationSummaryModel._default_manager.get(validation_run_id=run_id)

    payloads = [
        repository.get_validation_summary(run_id),
        repository.get_validation_summary_by_id(summary.pk),
        repository.get_validation_summary_by_run_id(run_id),
        repository.get_recent_validations(limit=1)[0],
    ]

    for payload in payloads:
        assert payload is not None
        assert payload["avg_f1_score"] == 0.0
        assert payload["avg_stability_score"] == 0.0


@pytest.mark.django_db
def test_nonfinite_legacy_score_is_not_published() -> None:
    summary = ValidationSummaryModel._default_manager.create(
        validation_run_id="validation-legacy-inf",
        evaluation_period_start=date(2025, 1, 1),
        evaluation_period_end=date(2025, 12, 31),
        total_indicators=1,
        pending_indicators=1,
        avg_f1_score=float("inf"),
        avg_stability_score=0.5,
        status="completed",
    )

    payload = DjangoAuditRepository().get_validation_summary_by_id(summary.pk)

    assert payload is not None
    assert payload["avg_f1_score"] is None
    assert payload["avg_stability_score"] == 0.5


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("validation_run_id", "../invalid", "validation_run_id"),
        ("evaluation_period_end", date(2024, 12, 31), "evaluation_period_start"),
        ("total_indicators", -1, "total_indicators"),
        ("approved_indicators", 2, "exceed"),
        ("pending_indicators", 0, "must equal"),
        ("avg_f1_score", float("nan"), "avg_f1_score"),
        ("avg_stability_score", 1.1, "avg_stability_score"),
        ("status", "approved", "status"),
        ("is_shadow_mode", 1, "is_shadow_mode"),
    ],
)
def test_invalid_summary_evidence_is_rejected_before_insert(
    field: str,
    value: object,
    message: str,
) -> None:
    repository = DjangoAuditRepository()
    kwargs = _valid_summary_kwargs()
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        repository.save_validation_summary_record(**cast(Any, kwargs))

    assert ValidationSummaryModel._default_manager.count() == 0


@pytest.mark.django_db
def test_completed_status_update_requires_counts_to_reconcile() -> None:
    repository = DjangoAuditRepository()
    repository.create_validation_summary_record(
        validation_run_id="validation-update-counts",
        evaluation_period_start=date(2025, 1, 1),
        evaluation_period_end=date(2025, 12, 31),
        total_indicators=2,
    )

    with pytest.raises(ValueError, match="must equal"):
        repository.update_validation_summary_status(
            validation_run_id="validation-update-counts",
            status="completed",
            approved_indicators=1,
        )

    summary = ValidationSummaryModel._default_manager.get(
        validation_run_id="validation-update-counts"
    )
    assert summary.status == "in_progress"
    assert summary.approved_indicators == 0


@pytest.mark.django_db
@pytest.mark.parametrize("limit", [0, -1, 101, True])
def test_recent_validation_limit_is_strictly_bounded(limit: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        DjangoAuditRepository().get_recent_validations(limit=cast(int, limit))
