"""Canonical financial statement fact persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from django.db.models import OuterRef, Subquery

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.financial_availability_repository import (
    FinancialAvailabilityRepositoryMixin,
)
from apps.data_center.infrastructure.models import FinancialFactModel

from .publication_fact_evidence import publication_fact_reference_for_dataset


class FinancialFactRepository(FinancialAvailabilityRepositoryMixin):
    """ORM-backed repository for financial statement facts."""

    @staticmethod
    def _from_model(m: FinancialFactModel) -> FinancialFact:
        return FinancialFact(
            asset_code=m.asset_code,
            period_end=m.period_end,
            period_type=FinancialPeriodType(m.period_type),
            metric_code=m.metric_code,
            value=float(m.value),
            unit=m.unit,
            source=m.source,
            report_date=m.report_date,
            available_at=m.available_at,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def get_facts(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        limit: int = 20,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
    ) -> list[FinancialFact]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = FinancialFactModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            if period_type:
                qs = qs.filter(period_type=period_type.value)
            if end is not None:
                qs = qs.filter(period_end__lte=end)
            rows = list(qs.order_by("-period_end")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(
        self, asset_code: str, period_type: FinancialPeriodType | None = None
    ) -> FinancialFact | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = FinancialFactModel.objects.filter(asset_code=candidate)
            if period_type:
                qs = qs.filter(period_type=period_type.value)
            m = qs.order_by("-period_end").first()
            if m is not None:
                return self._from_model(m)
        return None

    def bulk_upsert(self, facts: list[FinancialFact]) -> int:
        if not facts:
            return 0
        models = [
            FinancialFactModel(
                asset_code=fact.asset_code,
                period_end=fact.period_end,
                period_type=fact.period_type.value,
                metric_code=fact.metric_code,
                value=fact.value,
                unit=fact.unit,
                source=fact.source,
                report_date=fact.report_date,
                available_at=fact.available_at,
                extra=fact.extra,
            )
            for fact in facts
        ]
        FinancialFactModel._default_manager.bulk_create(
            models,
            batch_size=1_000,
            update_conflicts=True,
            update_fields=["value", "unit", "report_date", "available_at", "extra"],
            unique_fields=["asset_code", "period_end", "period_type", "metric_code", "source"],
        )
        return len(models)

    def list_publication_candidates(
        self, facts: Sequence[FinancialFact]
    ) -> list[PublicationFactReference]:
        """Resolve financial rows and require source-provided ``available_at``."""

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        for fact in facts:
            row = (
                FinancialFactModel._default_manager.filter(
                    asset_code=fact.asset_code,
                    period_end=fact.period_end,
                    period_type=fact.period_type.value,
                    metric_code=fact.metric_code,
                    source=fact.source,
                )
                .order_by("id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            if row.available_at is None:
                # A financial statement without an explicit source-availability
                # boundary is not safe for a publication snapshot.  In
                # particular, never substitute period_end or fetched_at here.
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            references.append(_financial_publication_reference(row))
        return references

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[PublicationFactReference]:
        """Select every metric from each asset's latest evidence-safe period."""

        if not asset_codes:
            return []
        latest_available_period = (
            FinancialFactModel._default_manager.filter(
                asset_code=OuterRef("asset_code"),
                available_at__isnull=False,
            )
            .order_by("-period_end")
            .values("period_end")[:1]
        )
        latest_metric_row = (
            FinancialFactModel._default_manager.filter(
                asset_code=OuterRef("asset_code"),
                period_end=OuterRef("period_end"),
                period_type=OuterRef("period_type"),
                metric_code=OuterRef("metric_code"),
                available_at__isnull=False,
            )
            .order_by("-available_at", "-revision_number", "-fetched_at", "-id")
            .values("id")[:1]
        )
        rows = FinancialFactModel._default_manager.filter(
            asset_code__in=asset_codes,
            available_at__isnull=False,
            period_end=Subquery(latest_available_period),
            pk=Subquery(latest_metric_row),
        ).order_by("asset_code", "period_type", "metric_code")
        return [_financial_publication_reference(row) for row in rows]


def _financial_publication_reference(
    row: FinancialFactModel,
) -> PublicationFactReference:
    """Convert one evidence-safe financial row to a publication reference."""

    if row.available_at is None:
        raise ValueError("financial publication candidate requires available_at")
    return publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.financial.fact",
    )


__all__ = ["FinancialFactRepository"]
