"""Validation summary persistence for Audit.

Owns ORM persistence for threshold validation summary records.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import TypeAlias

from .models import ValidationSummaryModel

__all__ = ["ValidationRepositoryMixin"]


ValidationSummaryPayload: TypeAlias = dict[str, object]

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
_VALIDATION_STATUSES = frozenset({"pending", "in_progress", "completed", "failed"})
_MAX_RECENT_VALIDATIONS = 100


class ValidationRepositoryMixin:
    """Threshold validation summary persistence."""

    def get_validation_summary(
        self,
        validation_run_id: str,
    ) -> ValidationSummaryPayload | None:
        """Return one validation summary by its governed run identifier."""

        normalized_run_id = _normalize_run_id(validation_run_id)
        if normalized_run_id is None:
            return None
        try:
            summary = ValidationSummaryModel._default_manager.get(
                validation_run_id=normalized_run_id
            )
        except ValidationSummaryModel.DoesNotExist:
            return None
        return _serialize_full_summary(summary, include_id=False)

    def get_recent_validations(
        self,
        limit: int = 10,
    ) -> list[ValidationSummaryPayload]:
        """Return a bounded list of recent validation summaries."""

        normalized_limit = _bounded_int(
            limit,
            label="limit",
            minimum=1,
            maximum=_MAX_RECENT_VALIDATIONS,
        )
        summaries = ValidationSummaryModel._default_manager.all().order_by("-run_date")[
            :normalized_limit
        ]
        return [_serialize_recent_summary(summary) for summary in summaries]

    def save_validation_summary_record(
        self,
        validation_run_id: str,
        run_date: date,
        evaluation_period_start: date,
        evaluation_period_end: date,
        total_indicators: int = 0,
        approved_indicators: int = 0,
        rejected_indicators: int = 0,
        pending_indicators: int = 0,
        avg_f1_score: float | None = None,
        avg_stability_score: float | None = None,
        overall_recommendation: str = "",
        status: str = "pending",
        is_shadow_mode: bool = True,
        error_message: str = "",
    ) -> str:
        """Persist a complete, internally consistent validation summary."""

        normalized_run_id = _require_run_id(validation_run_id)
        _require_plain_date(run_date, label="run_date")
        start_date, end_date = _validated_date_range(
            evaluation_period_start,
            evaluation_period_end,
        )
        normalized_status = _validation_status(status)
        counts = _validated_counts(
            total=total_indicators,
            approved=approved_indicators,
            rejected=rejected_indicators,
            pending=pending_indicators,
            require_complete=normalized_status == "completed",
        )
        f1_score = _optional_score(avg_f1_score, label="avg_f1_score")
        stability_score = _optional_score(
            avg_stability_score,
            label="avg_stability_score",
        )
        shadow_mode = _strict_bool(is_shadow_mode, label="is_shadow_mode")

        ValidationSummaryModel._default_manager.create(
            validation_run_id=normalized_run_id,
            evaluation_period_start=start_date,
            evaluation_period_end=end_date,
            total_indicators=counts[0],
            approved_indicators=counts[1],
            rejected_indicators=counts[2],
            pending_indicators=counts[3],
            avg_f1_score=f1_score,
            avg_stability_score=stability_score,
            overall_recommendation=_bounded_text(
                overall_recommendation,
                label="overall_recommendation",
                maximum=10_000,
            ),
            status=normalized_status,
            is_shadow_mode=shadow_mode,
            error_message=_bounded_text(
                error_message,
                label="error_message",
                maximum=1_000,
            ),
        )
        return normalized_run_id

    def get_validation_summary_by_id(
        self,
        summary_id: int,
    ) -> ValidationSummaryPayload | None:
        """Return one full validation summary by its positive database ID."""

        normalized_id = _optional_positive_id(summary_id)
        if normalized_id is None:
            return None
        try:
            summary = ValidationSummaryModel._default_manager.get(id=normalized_id)
        except ValidationSummaryModel.DoesNotExist:
            return None
        return _serialize_full_summary(summary, include_id=True)

    def get_validation_summary_record_by_id(
        self,
        summary_id: int,
    ) -> ValidationSummaryModel | None:
        """Return one validation-summary ORM record by positive ID."""

        normalized_id = _optional_positive_id(summary_id)
        if normalized_id is None:
            return None
        try:
            return ValidationSummaryModel._default_manager.get(id=normalized_id)
        except ValidationSummaryModel.DoesNotExist:
            return None

    def get_latest_validation_summary_model(
        self,
        *,
        is_shadow_mode: bool | None = None,
    ) -> ValidationSummaryModel | None:
        """Return the latest validation-summary ORM record."""

        queryset = ValidationSummaryModel._default_manager.all()
        if is_shadow_mode is not None:
            queryset = queryset.filter(
                is_shadow_mode=_strict_bool(
                    is_shadow_mode,
                    label="is_shadow_mode",
                )
            )
        return queryset.order_by("-run_date").first()

    def get_latest_validation_summary_record(self) -> ValidationSummaryPayload | None:
        """Return the minimal latest-validation summary projection."""

        try:
            summary = ValidationSummaryModel._default_manager.all().latest("run_date")
        except ValidationSummaryModel.DoesNotExist:
            return None
        return {
            "id": summary.id,
            "validation_run_id": summary.validation_run_id,
            "run_date": summary.run_date.isoformat(),
            "status": summary.status,
            "is_shadow_mode": summary.is_shadow_mode,
        }

    def create_validation_summary_record(
        self,
        validation_run_id: str,
        evaluation_period_start: date,
        evaluation_period_end: date,
        total_indicators: int = 0,
        status: str = "in_progress",
        is_shadow_mode: bool = True,
        run_date: date | None = None,
    ) -> ValidationSummaryPayload:
        """Create the initial record for one validation run."""

        normalized_run_id = _require_run_id(validation_run_id)
        start_date, end_date = _validated_date_range(
            evaluation_period_start,
            evaluation_period_end,
        )
        if run_date is not None:
            _require_plain_date(run_date, label="run_date")
        summary = ValidationSummaryModel._default_manager.create(
            validation_run_id=normalized_run_id,
            evaluation_period_start=start_date,
            evaluation_period_end=end_date,
            total_indicators=_bounded_int(
                total_indicators,
                label="total_indicators",
                minimum=0,
                maximum=2**31 - 1,
            ),
            status=_validation_status(status),
            is_shadow_mode=_strict_bool(is_shadow_mode, label="is_shadow_mode"),
        )
        return {
            "id": summary.id,
            "validation_run_id": summary.validation_run_id,
            "status": summary.status,
        }

    def update_validation_summary_status(
        self,
        validation_run_id: str,
        status: str,
        approved_indicators: int = 0,
        rejected_indicators: int = 0,
        pending_indicators: int = 0,
        avg_f1_score: float | None = None,
        avg_stability_score: float | None = None,
        overall_recommendation: str = "",
        error_message: str = "",
    ) -> bool:
        """Update one validation run with a consistent status and score summary."""

        normalized_run_id = _normalize_run_id(validation_run_id)
        if normalized_run_id is None:
            return False
        try:
            summary = ValidationSummaryModel._default_manager.get(
                validation_run_id=normalized_run_id
            )
        except ValidationSummaryModel.DoesNotExist:
            return False

        normalized_status = _validation_status(status)
        counts = _validated_counts(
            total=summary.total_indicators,
            approved=approved_indicators,
            rejected=rejected_indicators,
            pending=pending_indicators,
            require_complete=normalized_status == "completed",
        )
        summary.status = normalized_status
        summary.approved_indicators = counts[1]
        summary.rejected_indicators = counts[2]
        summary.pending_indicators = counts[3]
        if avg_f1_score is not None:
            summary.avg_f1_score = _optional_score(
                avg_f1_score,
                label="avg_f1_score",
            )
        if avg_stability_score is not None:
            summary.avg_stability_score = _optional_score(
                avg_stability_score,
                label="avg_stability_score",
            )
        summary.overall_recommendation = _bounded_text(
            overall_recommendation,
            label="overall_recommendation",
            maximum=10_000,
        )
        if error_message:
            summary.error_message = _bounded_text(
                error_message,
                label="error_message",
                maximum=1_000,
            )
        summary.save(
            update_fields=[
                "status",
                "approved_indicators",
                "rejected_indicators",
                "pending_indicators",
                "avg_f1_score",
                "avg_stability_score",
                "overall_recommendation",
                "error_message",
            ]
        )
        return True

    def get_validation_summary_by_run_id(
        self,
        validation_run_id: str,
    ) -> ValidationSummaryPayload | None:
        """Return one full validation summary by governed run identifier."""

        normalized_run_id = _normalize_run_id(validation_run_id)
        if normalized_run_id is None:
            return None
        try:
            summary = ValidationSummaryModel._default_manager.get(
                validation_run_id=normalized_run_id
            )
        except ValidationSummaryModel.DoesNotExist:
            return None
        return _serialize_full_summary(summary, include_id=True)


def _serialize_full_summary(
    summary: ValidationSummaryModel,
    *,
    include_id: bool,
) -> ValidationSummaryPayload:
    """Serialize a full summary without turning legitimate zero scores into null."""

    payload: ValidationSummaryPayload = {
        "validation_run_id": summary.validation_run_id,
        "run_date": summary.run_date.isoformat(),
        "evaluation_period_start": summary.evaluation_period_start.isoformat(),
        "evaluation_period_end": summary.evaluation_period_end.isoformat(),
        "total_indicators": summary.total_indicators,
        "approved_indicators": summary.approved_indicators,
        "rejected_indicators": summary.rejected_indicators,
        "pending_indicators": summary.pending_indicators,
        "avg_f1_score": _persisted_optional_score(summary.avg_f1_score),
        "avg_stability_score": _persisted_optional_score(summary.avg_stability_score),
        "overall_recommendation": summary.overall_recommendation,
        "status": summary.status,
        "is_shadow_mode": summary.is_shadow_mode,
        "error_message": summary.error_message,
    }
    if include_id:
        payload["id"] = summary.id
    return payload


def _serialize_recent_summary(
    summary: ValidationSummaryModel,
) -> ValidationSummaryPayload:
    """Serialize the bounded projection used by recent-validation lists."""

    return {
        "validation_run_id": summary.validation_run_id,
        "run_date": summary.run_date.isoformat(),
        "evaluation_period_start": summary.evaluation_period_start.isoformat(),
        "evaluation_period_end": summary.evaluation_period_end.isoformat(),
        "total_indicators": summary.total_indicators,
        "approved_indicators": summary.approved_indicators,
        "rejected_indicators": summary.rejected_indicators,
        "pending_indicators": summary.pending_indicators,
        "avg_f1_score": _persisted_optional_score(summary.avg_f1_score),
        "avg_stability_score": _persisted_optional_score(summary.avg_stability_score),
        "overall_recommendation": summary.overall_recommendation,
        "status": summary.status,
        "is_shadow_mode": summary.is_shadow_mode,
    }


def _normalize_run_id(value: object) -> str | None:
    """Return a canonical run identifier or None for invalid lookup input."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if _RUN_ID_PATTERN.fullmatch(normalized) is None:
        return None
    return normalized


def _require_run_id(value: object) -> str:
    """Return a canonical run identifier or reject invalid persistence input."""

    normalized = _normalize_run_id(value)
    if normalized is None:
        raise ValueError("validation_run_id has an invalid format")
    return normalized


def _validated_date_range(start: object, end: object) -> tuple[date, date]:
    """Return a plain-date range with start not after end."""

    normalized_start = _require_plain_date(start, label="evaluation_period_start")
    normalized_end = _require_plain_date(end, label="evaluation_period_end")
    if normalized_start > normalized_end:
        raise ValueError("evaluation_period_start must not be after evaluation_period_end")
    if (normalized_end - normalized_start).days > 3_660:
        raise ValueError("evaluation period must not exceed 3660 days")
    return normalized_start, normalized_end


def _require_plain_date(value: object, *, label: str) -> date:
    """Return a date while rejecting datetime and dynamic impostors."""

    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"{label} must be a date")
    return value


def _validated_counts(
    *,
    total: object,
    approved: object,
    rejected: object,
    pending: object,
    require_complete: bool,
) -> tuple[int, int, int, int]:
    """Validate nonnegative counts and their reconciliation to the total."""

    normalized = (
        _bounded_int(total, label="total_indicators", minimum=0, maximum=2**31 - 1),
        _bounded_int(
            approved,
            label="approved_indicators",
            minimum=0,
            maximum=2**31 - 1,
        ),
        _bounded_int(
            rejected,
            label="rejected_indicators",
            minimum=0,
            maximum=2**31 - 1,
        ),
        _bounded_int(
            pending,
            label="pending_indicators",
            minimum=0,
            maximum=2**31 - 1,
        ),
    )
    classified = sum(normalized[1:])
    if classified > normalized[0]:
        raise ValueError("indicator status counts exceed total_indicators")
    if require_complete and classified != normalized[0]:
        raise ValueError("completed validation counts must equal total_indicators")
    return normalized


def _bounded_int(value: object, *, label: str, minimum: int, maximum: int) -> int:
    """Return a strict bounded integer."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return value


def _optional_positive_id(value: object) -> int | None:
    """Return a positive integer ID or None for invalid lookup input."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _optional_score(value: object, *, label: str) -> float | None:
    """Return an optional finite score in the closed unit interval."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{label} must be finite and between 0 and 1")
    return normalized


def _persisted_optional_score(value: object) -> float | None:
    """Return a safe persisted score without publishing NaN or infinity."""

    try:
        return _optional_score(value, label="persisted_score")
    except ValueError:
        return None


def _validation_status(value: object) -> str:
    """Return one supported validation lifecycle status."""

    if not isinstance(value, str):
        raise ValueError("status must be a string")
    normalized = value.strip().lower()
    if normalized not in _VALIDATION_STATUSES:
        raise ValueError("status is not supported")
    return normalized


def _strict_bool(value: object, *, label: str) -> bool:
    """Return a real boolean without accepting truthy substitutes."""

    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def _bounded_text(value: object, *, label: str, maximum: int) -> str:
    """Return bounded text suitable for an Audit summary record."""

    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    if len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} exceeds the supported text boundary")
    return value
