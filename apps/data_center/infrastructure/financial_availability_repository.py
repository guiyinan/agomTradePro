"""Financial fact availability preview and repair persistence."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Count, DateTimeField, Max, Min, Q
from django.db.models.functions import Cast

from apps.data_center.application.current_fact_remediation import (
    FinancialAvailabilityBackfillPreview,
)
from apps.data_center.infrastructure.models import FinancialFactModel


class FinancialAvailabilityRepositoryMixin:
    """Provide source-date availability preview and repair operations."""

    def preview_availability_backfill(
        self,
        *,
        asset_codes: tuple[str, ...],
        recorded_at: datetime,
    ) -> FinancialAvailabilityBackfillPreview:
        """Summarize source-date availability repair without mutating facts."""

        queryset = FinancialFactModel._default_manager.filter(asset_code__in=asset_codes)
        missing = queryset.filter(available_at__isnull=True)
        eligible = missing.filter(
            report_date__isnull=False,
            report_date__lte=recorded_at.date(),
        )
        aggregate = missing.aggregate(
            missing_row_count=Count("id"),
            eligible_row_count=Count(
                "id",
                filter=Q(
                    report_date__isnull=False,
                    report_date__lte=recorded_at.date(),
                ),
            ),
            unresolved_row_count=Count("id", filter=Q(report_date__isnull=True)),
            future_report_date_count=Count(
                "id",
                filter=Q(report_date__gt=recorded_at.date()),
            ),
            oldest_report_date=Min("report_date"),
            newest_report_date=Max("report_date"),
        )
        return FinancialAvailabilityBackfillPreview(
            missing_row_count=int(aggregate["missing_row_count"] or 0),
            eligible_row_count=int(aggregate["eligible_row_count"] or 0),
            eligible_asset_count=eligible.values("asset_code").distinct().count(),
            unresolved_row_count=int(aggregate["unresolved_row_count"] or 0),
            future_report_date_count=int(aggregate["future_report_date_count"] or 0),
            future_available_at_count=queryset.filter(available_at__gt=recorded_at).count(),
            oldest_report_date=aggregate["oldest_report_date"],
            newest_report_date=aggregate["newest_report_date"],
        )

    def backfill_available_at_from_report_date(
        self,
        *,
        asset_codes: tuple[str, ...],
        recorded_at: datetime,
    ) -> int:
        """Restore only null availability using the persisted source report date."""

        return FinancialFactModel._default_manager.filter(
            asset_code__in=asset_codes,
            available_at__isnull=True,
            report_date__isnull=False,
            report_date__lte=recorded_at.date(),
        ).update(available_at=Cast("report_date", output_field=DateTimeField()))


__all__ = ["FinancialAvailabilityRepositoryMixin"]
