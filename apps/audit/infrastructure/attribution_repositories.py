"""Audit attribution reports, loss analyses, summaries, and health persistence."""

from __future__ import annotations

from datetime import date

from apps.audit.domain.interfaces import (
    AttributionReportRecord,
    ExperienceSummaryRecord,
    LossAnalysisRecord,
)

from .attribution_repository_validators import ATTRIBUTION_METHODS as _ATTRIBUTION_METHODS
from .attribution_repository_validators import EXPERIENCE_PRIORITIES as _EXPERIENCE_PRIORITIES
from .attribution_repository_validators import LOSS_SOURCES as _LOSS_SOURCES
from .attribution_repository_validators import bounded_int as _bounded_int
from .attribution_repository_validators import bounded_text as _bounded_text
from .attribution_repository_validators import choice as _choice
from .attribution_repository_validators import finite_float as _finite_float
from .attribution_repository_validators import optional_positive_id as _optional_positive_id
from .attribution_repository_validators import persisted_finite_float as _persisted_finite_float
from .attribution_repository_validators import positive_id as _positive_id
from .attribution_repository_validators import regime_token as _regime_token
from .attribution_repository_validators import saved_id as _saved_id
from .attribution_repository_validators import serialize_report
from .attribution_repository_validators import serialize_valid_reports as _serialize_valid_reports
from .attribution_repository_validators import unit_interval as _unit_interval
from .attribution_repository_validators import validated_date_range as _validated_date_range
from .models import AttributionReport, ExperienceSummary, LossAnalysis

__all__ = ["AttributionRepositoryMixin"]


class AttributionRepositoryMixin:
    """Attribution report, loss analysis, and experience summary persistence."""

    def get_database_health(self) -> dict[str, str]:
        """Run a database probe without returning connection names or paths."""

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        return {
            "database": "reachable",
            "engine": str(connection.vendor),
        }

    def save_attribution_report(
        self,
        backtest_id: int,
        period_start: date,
        period_end: date,
        regime_timing_pnl: float,
        asset_selection_pnl: float,
        interaction_pnl: float,
        total_pnl: float,
        regime_accuracy: float,
        regime_predicted: str,
        regime_actual: str | None = None,
        attribution_method: str = "heuristic",
    ) -> int:
        """Persist one finite, date-consistent attribution report."""

        start_date, end_date = _validated_date_range(period_start, period_end)
        normalized_method = _choice(
            attribution_method,
            choices=_ATTRIBUTION_METHODS,
            label="attribution_method",
        )
        report = AttributionReport._default_manager.create(
            backtest_id=_positive_id(backtest_id, label="backtest_id"),
            period_start=start_date,
            period_end=end_date,
            attribution_method=normalized_method,
            regime_timing_pnl=_finite_float(
                regime_timing_pnl,
                label="regime_timing_pnl",
            ),
            asset_selection_pnl=_finite_float(
                asset_selection_pnl,
                label="asset_selection_pnl",
            ),
            interaction_pnl=_finite_float(interaction_pnl, label="interaction_pnl"),
            total_pnl=_finite_float(total_pnl, label="total_pnl"),
            regime_accuracy=_unit_interval(
                regime_accuracy,
                label="regime_accuracy",
            ),
            regime_predicted=_regime_token(
                regime_predicted,
                label="regime_predicted",
                maximum=20,
            ),
            regime_actual=(
                _regime_token(
                    regime_actual,
                    label="regime_actual",
                    maximum=64,
                )
                if regime_actual is not None
                else None
            ),
        )
        return _saved_id(report.id, label="attribution_report_id")

    def save_loss_analysis(
        self,
        report_id: int,
        loss_source: str,
        impact: float,
        impact_percentage: float,
        description: str,
        improvement_suggestion: str = "",
    ) -> int:
        """Persist one finite loss-analysis record for an existing report."""

        percentage = _finite_float(impact_percentage, label="impact_percentage")
        if percentage < 0:
            raise ValueError("impact_percentage must be nonnegative")
        analysis = LossAnalysis._default_manager.create(
            report_id=_positive_id(report_id, label="report_id"),
            loss_source=_choice(
                loss_source,
                choices=_LOSS_SOURCES,
                label="loss_source",
            ),
            impact=_finite_float(impact, label="impact"),
            impact_percentage=percentage,
            description=_bounded_text(
                description,
                label="description",
                maximum=10_000,
                allow_empty=False,
            ),
            improvement_suggestion=_bounded_text(
                improvement_suggestion,
                label="improvement_suggestion",
                maximum=10_000,
                allow_empty=True,
            ),
        )
        return _saved_id(analysis.id, label="loss_analysis_id")

    def save_experience_summary(
        self,
        report_id: int,
        lesson: str,
        recommendation: str,
        priority: str = "MEDIUM",
    ) -> int:
        """Persist one bounded, governed experience summary."""

        summary = ExperienceSummary._default_manager.create(
            report_id=_positive_id(report_id, label="report_id"),
            lesson=_bounded_text(
                lesson,
                label="lesson",
                maximum=10_000,
                allow_empty=False,
            ),
            recommendation=_bounded_text(
                recommendation,
                label="recommendation",
                maximum=10_000,
                allow_empty=False,
            ),
            priority=_choice(
                priority,
                choices=_EXPERIENCE_PRIORITIES,
                label="priority",
            ),
        )
        return _saved_id(summary.id, label="experience_summary_id")

    def get_attribution_report(self, report_id: int) -> AttributionReportRecord | None:
        """Return one safe attribution report projection by positive ID."""

        normalized_id = _optional_positive_id(report_id)
        if normalized_id is None:
            return None
        try:
            report = AttributionReport._default_manager.get(id=normalized_id)
        except AttributionReport.DoesNotExist:
            return None
        return self._serialize_report(report)

    def list_attribution_report_records(
        self,
        attribution_method: str | None = None,
        limit: int | None = None,
    ) -> list[AttributionReport]:
        """Return bounded attribution ORM records for interface query services."""

        queryset = AttributionReport._default_manager.select_related("backtest").order_by(
            "-created_at"
        )
        if attribution_method is not None:
            queryset = queryset.filter(
                attribution_method=_choice(
                    attribution_method,
                    choices=_ATTRIBUTION_METHODS,
                    label="attribution_method",
                )
            )
        if limit is not None:
            queryset = queryset[: _bounded_int(limit, label="limit", minimum=1, maximum=500)]
        return list(queryset)

    def count_attribution_reports(self) -> int:
        """Return the number of attribution reports."""

        return AttributionReport._default_manager.count()

    def get_reported_backtest_ids(self) -> set[int]:
        """Return backtest IDs that already have attribution reports."""

        return set(AttributionReport._default_manager.values_list("backtest_id", flat=True))

    def get_attribution_report_record(
        self,
        report_id: int,
    ) -> AttributionReport | None:
        """Return one attribution ORM record by positive ID."""

        normalized_id = _optional_positive_id(report_id)
        if normalized_id is None:
            return None
        try:
            return AttributionReport._default_manager.select_related("backtest").get(
                id=normalized_id
            )
        except AttributionReport.DoesNotExist:
            return None

    def get_reports_by_backtest(self, backtest_id: int) -> list[AttributionReportRecord]:
        """Return safe reports for one positive backtest ID."""

        normalized_id = _optional_positive_id(backtest_id)
        if normalized_id is None:
            return []
        reports = AttributionReport._default_manager.filter(backtest_id=normalized_id).order_by(
            "-period_end"
        )
        return _serialize_valid_reports(reports)

    def get_reports_by_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[AttributionReportRecord]:
        """Return safe reports fully contained in one valid date range."""

        normalized_start, normalized_end = _validated_date_range(start_date, end_date)
        reports = AttributionReport._default_manager.filter(
            period_start__gte=normalized_start,
            period_end__lte=normalized_end,
        ).order_by("-period_end")
        return _serialize_valid_reports(reports)

    def get_loss_analyses(self, report_id: int) -> list[LossAnalysisRecord]:
        """Return finite loss evidence for one positive report ID."""

        normalized_id = _optional_positive_id(report_id)
        if normalized_id is None:
            return []
        analyses = LossAnalysis._default_manager.filter(report_id=normalized_id).order_by("-impact")
        payloads: list[LossAnalysisRecord] = []
        for analysis in analyses:
            impact = _persisted_finite_float(analysis.impact)
            percentage = _persisted_finite_float(analysis.impact_percentage)
            if impact is None or percentage is None or percentage < 0:
                continue
            payloads.append(
                {
                    "id": analysis.id,
                    "loss_source": analysis.loss_source,
                    "loss_source_display": analysis.get_loss_source_display(),
                    "impact": impact,
                    "impact_percentage": percentage,
                    "description": analysis.description,
                    "improvement_suggestion": analysis.improvement_suggestion,
                }
            )
        return payloads

    def get_loss_analysis_records(self, report_id: int) -> list[LossAnalysis]:
        """Return loss-analysis ORM records for one positive report ID."""

        normalized_id = _optional_positive_id(report_id)
        if normalized_id is None:
            return []
        return list(
            LossAnalysis._default_manager.filter(report_id=normalized_id).order_by("-impact")
        )

    def get_experience_summaries(self, report_id: int) -> list[ExperienceSummaryRecord]:
        """Return experience summaries for one positive report ID."""

        normalized_id = _optional_positive_id(report_id)
        if normalized_id is None:
            return []
        summaries = ExperienceSummary._default_manager.filter(report_id=normalized_id).order_by(
            "-priority", "-created_at"
        )
        return [
            {
                "id": summary.id,
                "lesson": summary.lesson,
                "recommendation": summary.recommendation,
                "priority": summary.priority,
                "is_applied": summary.is_applied,
                "applied_at": (summary.applied_at.isoformat() if summary.applied_at else None),
            }
            for summary in summaries
        ]

    def get_experience_summary_records(
        self,
        report_id: int,
    ) -> list[ExperienceSummary]:
        """Return experience-summary ORM records for one positive report ID."""

        normalized_id = _optional_positive_id(report_id)
        if normalized_id is None:
            return []
        return list(
            ExperienceSummary._default_manager.filter(report_id=normalized_id).order_by(
                "-priority", "-created_at"
            )
        )

    def _serialize_report(
        self,
        report: AttributionReport,
    ) -> AttributionReportRecord | None:
        """Serialize one report, rejecting corrupted persisted numeric evidence."""
        return serialize_report(report)
