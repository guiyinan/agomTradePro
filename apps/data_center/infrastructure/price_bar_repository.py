"""Canonical OHLCV price bar persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import PriceBarModel

from .publication_fact_evidence import publication_fact_reference_for_dataset
from .published_fact_versions import (
    latest_fact_revisions,
    latest_versioned_rows_for_assets,
    upsert_publication_safe_facts,
)

_NATURAL_KEY = ("asset_code", "bar_date", "freq", "adjustment", "source")


class PriceBarRepository:
    """ORM-backed repository for OHLCV price bars."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the fixed transaction identity used by this repository."""

        return "django:default"

    @staticmethod
    def _from_model(m: PriceBarModel) -> PriceBar:
        return PriceBar(
            asset_code=m.asset_code,
            bar_date=m.bar_date,
            freq=m.freq,
            adjustment=PriceAdjustment(m.adjustment),
            open=float(m.open),
            high=float(m.high),
            low=float(m.low),
            close=float(m.close),
            volume=float(m.volume) if m.volume is not None else None,
            amount=float(m.amount) if m.amount is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
            ingested_run_id=str(m.ingested_run_id) if m.ingested_run_id else "",
        )

    def get_bars(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
        fact_pks: Sequence[str] | None = None,
    ) -> list[PriceBar]:
        """Return latest revisions or the exact rows pinned by a publication."""
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = PriceBarModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            else:
                qs = latest_fact_revisions(PriceBarModel, _NATURAL_KEY).filter(asset_code=candidate)
            if start:
                qs = qs.filter(bar_date__gte=start)
            if end:
                qs = qs.filter(bar_date__lte=end)
            rows = list(qs.order_by("-bar_date")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(
        self,
        asset_code: str,
        fact_pks: Sequence[str] | None = None,
    ) -> PriceBar | None:
        """Return the latest source bar within the optional frozen member scope."""
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = PriceBarModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            m = qs.order_by("-bar_date", "-revision_number", "-pk").first()
            if m is not None:
                return self._from_model(m)
        return None

    def list_asset_codes(self, as_of: date | None = None) -> list[str]:
        """Return assets with canonical price facts through ``as_of``."""

        queryset = PriceBarModel.objects.all()
        if as_of is not None:
            queryset = queryset.filter(bar_date__lte=as_of)
        return list(queryset.order_by("asset_code").values_list("asset_code", flat=True).distinct())

    def bulk_upsert(self, bars: list[PriceBar]) -> int:
        """Persist daily corrections without rewriting publication-referenced bars."""
        if not bars:
            return 0
        models = [
            PriceBarModel(
                asset_code=bar.asset_code,
                bar_date=bar.bar_date,
                freq=bar.freq,
                adjustment=bar.adjustment.value,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                amount=bar.amount,
                source=bar.source,
                ingested_run_id=bar.ingested_run_id or None,
            )
            for bar in bars
        ]
        return upsert_publication_safe_facts(
            PriceBarModel,
            models,
            natural_key=_NATURAL_KEY,
            update_fields=(
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "ingested_run_id",
            ),
        )

    def list_publication_candidates(
        self, bars: Sequence[PriceBar]
    ) -> list[PublicationFactReference]:
        """Resolve written bars to exact rows without washing out ``bar_date``."""

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        for bar in bars:
            row = (
                PriceBarModel._default_manager.filter(
                    asset_code=bar.asset_code,
                    bar_date=bar.bar_date,
                    freq=bar.freq,
                    adjustment=bar.adjustment.value,
                    source=bar.source,
                )
                .order_by("-revision_number", "-id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            references.append(_price_bar_publication_reference(row))
        return references

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[PublicationFactReference]:
        """Select the latest daily unadjusted fact for every requested asset."""

        publication_filters = {
            "freq": "1d",
            "adjustment": PriceAdjustment.NONE.value,
        }
        rows = latest_versioned_rows_for_assets(
            PriceBarModel,
            natural_key=_NATURAL_KEY,
            asset_codes=asset_codes,
            observation_field="bar_date",
            asset_order=("-bar_date", "-fetched_at", "-revision_number", "-id"),
            filters=publication_filters,
        )
        return [_price_bar_publication_reference(row) for row in rows]


def _price_bar_publication_reference(row: PriceBarModel) -> PublicationFactReference:
    """Convert one exact price row to immutable publication evidence."""

    return publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.price.bar",
    )


__all__ = ["PriceBarRepository"]
