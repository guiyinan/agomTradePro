"""Attribution report persistence for Audit.

Owns ORM persistence for attribution reports, loss analyses, and experience
summaries, plus the lightweight database health probe.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime

from apps.audit.domain.interfaces import (
    AttributionReportRecord,
    ExperienceSummaryRecord,
    LossAnalysisRecord,
)

from .models import AttributionReport, ExperienceSummary, LossAnalysis

__all__ = ["AttributionRepositoryMixin"]


_ATTRIBUTION_METHODS = frozenset({"heuristic", "brinson"})
_LOSS_SOURCES = frozenset(
    {
        "REGIME_ERROR",
        "TIMING_ERROR",
        "ASSET_SELECTION_ERROR",
        "EXECUTION_ERROR",
        "TRANSACTION_COST",
        "POLICY_MISJUDGMENT",
        "EXTERNAL_SHOCK",
    }
)
_EXPERIENCE_PRIORITIES = frozenset({"HIGH", "MEDIUM", "LOW"})
_REGIME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


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
        return _serialize_valid_reports(self, reports)

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
        return _serialize_valid_reports(self, reports)

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

        regime_timing = _persisted_finite_float(report.regime_timing_pnl)
        asset_selection = _persisted_finite_float(report.asset_selection_pnl)
        interaction = _persisted_finite_float(report.interaction_pnl)
        total = _persisted_finite_float(report.total_pnl)
        accuracy = _persisted_finite_float(report.regime_accuracy)
        if (
            regime_timing is None
            or asset_selection is None
            or interaction is None
            or total is None
            or accuracy is None
            or not 0.0 <= accuracy <= 1.0
            or report.period_start > report.period_end
            or report.attribution_method not in _ATTRIBUTION_METHODS
            or not _is_regime_token(report.regime_predicted, maximum=20)
            or (
                report.regime_actual is not None
                and not _is_regime_token(report.regime_actual, maximum=64)
            )
        ):
            return None
        return {
            "id": report.id,
            "backtest_id": report.backtest_id,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "attribution_method": report.attribution_method,
            "attribution_method_display": report.get_attribution_method_display(),
            "regime_timing_pnl": regime_timing,
            "asset_selection_pnl": asset_selection,
            "interaction_pnl": interaction,
            "total_pnl": total,
            "regime_accuracy": accuracy,
            "regime_predicted": report.regime_predicted,
            "regime_actual": report.regime_actual,
            "created_at": report.created_at.isoformat(),
        }


def _serialize_valid_reports(
    repository: AttributionRepositoryMixin,
    reports: object,
) -> list[AttributionReportRecord]:
    """Serialize an iterable of ORM reports while isolating corrupted rows."""

    payloads: list[AttributionReportRecord] = []
    if not hasattr(reports, "__iter__"):
        return payloads
    for report in reports:
        if not isinstance(report, AttributionReport):
            continue
        payload = repository._serialize_report(report)
        if payload is not None:
            payloads.append(payload)
    return payloads


def _validated_date_range(start: object, end: object) -> tuple[date, date]:
    """Return an ordered pair of plain dates."""

    normalized_start = _plain_date(start, label="period_start")
    normalized_end = _plain_date(end, label="period_end")
    if normalized_start > normalized_end:
        raise ValueError("period_start must not be after period_end")
    return normalized_start, normalized_end


def _plain_date(value: object, *, label: str) -> date:
    """Return a date while rejecting datetime and dynamic impostors."""

    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"{label} must be a date")
    return value


def _positive_id(value: object, *, label: str) -> int:
    """Return one strict positive integer ID."""

    return _bounded_int(value, label=label, minimum=1, maximum=2**63 - 1)


def _optional_positive_id(value: object) -> int | None:
    """Return a positive integer or None for invalid lookup input."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _bounded_int(value: object, *, label: str, minimum: int, maximum: int) -> int:
    """Return a strict bounded integer."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return value


def _finite_float(value: object, *, label: str) -> float:
    """Return a finite real number without accepting bool."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{label} must be finite")
    return normalized


def _persisted_finite_float(value: object) -> float | None:
    """Return a finite persisted number or None for corrupted evidence."""

    try:
        return _finite_float(value, label="persisted_value")
    except ValueError:
        return None


def _unit_interval(value: object, *, label: str) -> float:
    """Return a finite number in the closed unit interval."""

    normalized = _finite_float(value, label=label)
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{label} must be between 0 and 1")
    return normalized


def _choice(value: object, *, choices: frozenset[str], label: str) -> str:
    """Return one normalized governed choice."""

    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if normalized not in choices:
        raise ValueError(f"{label} is not supported")
    return normalized


def _regime_token(value: object, *, label: str, maximum: int) -> str:
    """Return a bounded regime/audit status token."""

    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not _is_regime_token(normalized, maximum=maximum):
        raise ValueError(f"{label} has an invalid format")
    return normalized


def _is_regime_token(value: object, *, maximum: int) -> bool:
    """Return whether a persisted regime token is structurally safe."""

    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and _REGIME_PATTERN.fullmatch(value) is not None
    )


def _bounded_text(
    value: object,
    *,
    label: str,
    maximum: int,
    allow_empty: bool,
) -> str:
    """Return bounded text without NUL characters."""

    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if (not allow_empty and not normalized) or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError(f"{label} exceeds the supported text boundary")
    return normalized


def _saved_id(value: object, *, label: str) -> int:
    """Return the positive ID assigned by Django after insertion."""

    return _positive_id(value, label=label)
