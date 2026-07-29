"""Validation summary persistence for Audit.

Owns ORM persistence for threshold validation summary records.
"""

from __future__ import annotations

from datetime import date

from .models import ValidationSummaryModel
from .validation_repository_values import MAX_RECENT_VALIDATIONS as _MAX_RECENT_VALIDATIONS
from .validation_repository_values import ValidationSummaryPayload
from .validation_repository_values import bounded_int as _bounded_int
from .validation_repository_values import bounded_text as _bounded_text
from .validation_repository_values import normalize_run_id as _normalize_run_id
from .validation_repository_values import optional_positive_id as _optional_positive_id
from .validation_repository_values import optional_score as _optional_score
from .validation_repository_values import require_plain_date as _require_plain_date
from .validation_repository_values import require_run_id as _require_run_id
from .validation_repository_values import serialize_full_summary as _serialize_full_summary
from .validation_repository_values import serialize_recent_summary as _serialize_recent_summary
from .validation_repository_values import strict_bool as _strict_bool
from .validation_repository_values import validated_counts as _validated_counts
from .validation_repository_values import validated_date_range as _validated_date_range
from .validation_repository_values import validation_status as _validation_status

__all__ = ["ValidationRepositoryMixin"]


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
