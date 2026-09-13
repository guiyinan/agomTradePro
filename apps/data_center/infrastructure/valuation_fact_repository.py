"""Canonical valuation fact persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from django.db.models import F, Max, OuterRef, Subquery

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import ValuationFact
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import ValuationFactModel

from .publication_fact_evidence import publication_fact_reference_for_dataset


class ValuationFactRepository:
    """ORM-backed repository for daily valuation multiples."""

    @staticmethod
    def _from_model(m: ValuationFactModel) -> ValuationFact:
        return ValuationFact(
            asset_code=m.asset_code,
            val_date=m.val_date,
            pe_ttm=float(m.pe_ttm) if m.pe_ttm is not None else None,
            pe_static=float(m.pe_static) if m.pe_static is not None else None,
            pb=float(m.pb) if m.pb is not None else None,
            ps_ttm=float(m.ps_ttm) if m.ps_ttm is not None else None,
            market_cap=float(m.market_cap) if m.market_cap is not None else None,
            float_market_cap=float(m.float_market_cap) if m.float_market_cap is not None else None,
            dv_ratio=float(m.dv_ratio) if m.dv_ratio is not None else None,
            source=m.source,
            observed_at=m.observed_at,
            available_at=m.available_at,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
            source_record_id=m.source_record_id,
            raw_payload_hash=m.raw_payload_hash,
        )

    def get_series(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
    ) -> list[ValuationFact]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = ValuationFactModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            if start:
                qs = qs.filter(val_date__gte=start)
            if end:
                qs = qs.filter(val_date__lte=end)
            rows = list(qs.order_by("-val_date"))
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(self, asset_code: str) -> ValuationFact | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            m = (
                ValuationFactModel.objects.filter(asset_code=candidate)
                .order_by("-val_date")
                .first()
            )
            if m is not None:
                return self._from_model(m)
        return None

    def get_latest_date(self) -> date | None:
        """Return the newest canonical valuation date across all assets."""

        value = ValuationFactModel._default_manager.aggregate(latest=Max("val_date"))["latest"]
        return value if isinstance(value, date) else None

    def list_by_date(self, as_of_date: date) -> list[ValuationFact]:
        """Return canonical valuation facts for one date in deterministic order."""

        rows = ValuationFactModel._default_manager.filter(val_date=as_of_date).order_by(
            "asset_code"
        )
        return [self._from_model(row) for row in rows]

    def list_asset_codes(self, as_of: date | None = None) -> list[str]:
        """Return assets with canonical valuation facts through ``as_of``."""

        queryset = ValuationFactModel.objects.all()
        if as_of is not None:
            queryset = queryset.filter(val_date__lte=as_of)
        return list(queryset.order_by("asset_code").values_list("asset_code", flat=True).distinct())

    def bulk_upsert(self, facts: list[ValuationFact]) -> int:
        """Upsert facts by natural key while refreshing values and provenance."""

        if not facts:
            return 0
        models = [
            ValuationFactModel(
                asset_code=fact.asset_code,
                val_date=fact.val_date,
                pe_ttm=fact.pe_ttm,
                pe_static=fact.pe_static,
                pb=fact.pb,
                ps_ttm=fact.ps_ttm,
                market_cap=fact.market_cap,
                float_market_cap=fact.float_market_cap,
                dv_ratio=fact.dv_ratio,
                source=fact.source,
                observed_at=fact.observed_at,
                available_at=fact.available_at,
                fetched_at=fact.fetched_at,
                extra=fact.extra,
                source_record_id=fact.source_record_id,
                raw_payload_hash=fact.raw_payload_hash,
            )
            for fact in facts
        ]
        ValuationFactModel._default_manager.bulk_create(
            models,
            batch_size=1_000,
            update_conflicts=True,
            update_fields=[
                "pe_ttm",
                "pe_static",
                "pb",
                "ps_ttm",
                "market_cap",
                "float_market_cap",
                "dv_ratio",
                "observed_at",
                "available_at",
                "fetched_at",
                "extra",
                "source_record_id",
                "raw_payload_hash",
            ],
            unique_fields=["asset_code", "val_date", "source"],
        )
        return len(models)

    def list_publication_candidates(
        self, facts: Sequence[ValuationFact]
    ) -> list[PublicationFactReference]:
        """Resolve exact valuation rows without substituting fetch time.

        ``observed_at`` is required source evidence. Missing observation time
        is rejected instead of being fabricated from ``val_date`` or
        ``fetched_at``; ``available_at`` remains an independent safety field.
        """

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        now = datetime.now(UTC)
        for fact in facts:
            row = (
                ValuationFactModel._default_manager.filter(
                    asset_code=fact.asset_code,
                    val_date=fact.val_date,
                    source=fact.source,
                )
                .order_by("id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            references.append(_valuation_publication_reference(row, now=now))
        return references

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[PublicationFactReference]:
        """Select the latest deterministic valuation fact for every asset."""

        if not asset_codes:
            return []
        latest_row = (
            ValuationFactModel._default_manager.filter(asset_code=OuterRef("asset_code"))
            .order_by(
                F("val_date").desc(),
                F("observed_at").desc(nulls_last=True),
                F("available_at").desc(nulls_last=True),
                F("fetched_at").desc(),
                F("revision_number").desc(),
                F("id").desc(),
            )
            .values("id")[:1]
        )
        rows = ValuationFactModel._default_manager.filter(
            asset_code__in=asset_codes,
            pk=Subquery(latest_row),
        ).order_by("asset_code")
        now = datetime.now(UTC)
        return [_valuation_publication_reference(row, now=now) for row in rows]


def _valuation_publication_reference(
    row: ValuationFactModel,
    *,
    now: datetime,
) -> PublicationFactReference:
    """Convert one exact valuation row to immutable publication evidence."""

    if row.available_at is not None:
        if row.available_at.tzinfo is None or row.available_at.utcoffset() is None:
            raise ValueError("valuation available_at must be timezone-aware")
        if row.available_at > now:
            raise ValueError("valuation available_at cannot be in the future")
    if row.observed_at is None:
        raise ValueError("valuation publication candidate requires observed_at")
    if row.observed_at.tzinfo is None or row.observed_at.utcoffset() is None:
        raise ValueError("valuation observed_at must be timezone-aware")
    if row.observed_at > now:
        raise ValueError("valuation observed_at cannot be in the future")
    if row.fetched_at.tzinfo is None or row.fetched_at.utcoffset() is None:
        raise ValueError("valuation fetched_at must be timezone-aware")
    if row.fetched_at < row.observed_at:
        raise ValueError("valuation fetched_at cannot precede observed_at")
    return publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.valuation.fact",
    )


__all__ = ["ValuationFactRepository"]
