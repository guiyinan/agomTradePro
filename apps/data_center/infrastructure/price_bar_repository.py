"""Canonical OHLCV price bar persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure._repository_helpers import (
    _build_asset_code_candidates,
    _resolve_asset_code_candidates,
)
from apps.data_center.infrastructure.models import AssetAliasModel, AssetMasterModel, PriceBarModel

from .publication_fact_evidence import publication_fact_reference_for_dataset
from .published_fact_versions import (
    latest_fact_revisions,
    latest_versioned_rows_for_assets,
    upsert_publication_safe_facts,
)

_NATURAL_KEY = ("asset_code", "bar_date", "freq", "adjustment", "source")
_TARGET_SESSION_PRICE_FREQUENCIES: tuple[str, ...] = (
    "1d",
    "60m",
    "30m",
    "15m",
    "5m",
    "1m",
)


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

    def get_bars_for_assets(
        self,
        asset_codes: Sequence[str],
        start: date | None = None,
        end: date | None = None,
        limit: int = 5000,
    ) -> dict[str, tuple[PriceBar, ...]]:
        """Read one bounded reference window for many assets with batched ORM lookups."""

        normalized_codes = tuple(sorted(set(asset_codes)))
        if not normalized_codes:
            return {}
        if limit <= 0:
            return dict.fromkeys(normalized_codes, ())
        assets_by_candidate: dict[str, set[str]] = {}
        bare_codes_by_base: dict[str, list[str]] = {}
        for code in normalized_codes:
            candidates = _build_asset_code_candidates(code)
            for candidate in candidates:
                assets_by_candidate.setdefault(candidate, set()).add(code)
            normalized_code = code.strip().upper()
            if normalized_code and "." not in normalized_code:
                base_code = normalized_code.split(".", 1)[0]
                bare_codes_by_base.setdefault(base_code, []).append(code)
        if assets_by_candidate:
            candidate_codes = tuple(sorted(assets_by_candidate))
            aliases = AssetAliasModel.objects.filter(alias_code__in=candidate_codes).values_list(
                "alias_code", "asset__code"
            )
            for alias_code, canonical_code in aliases:
                for asset_code in assets_by_candidate.get(alias_code, ()):
                    assets_by_candidate.setdefault(canonical_code, set()).add(asset_code)
        if bare_codes_by_base:
            matching_codes: dict[str, list[str]] = {
                base_code: [] for base_code in bare_codes_by_base
            }
            for canonical_code in AssetMasterModel.objects.values_list("code", flat=True):
                if "." not in canonical_code:
                    continue
                base_code = canonical_code.split(".", 1)[0]
                requested_codes = bare_codes_by_base.get(base_code)
                if requested_codes is None or len(matching_codes[base_code]) >= 5:
                    continue
                matching_codes[base_code].append(canonical_code)
                for asset_code in requested_codes:
                    assets_by_candidate.setdefault(canonical_code, set()).add(asset_code)
        queryset = latest_fact_revisions(PriceBarModel, _NATURAL_KEY).filter(
            asset_code__in=tuple(sorted(assets_by_candidate))
        )
        if start is not None:
            queryset = queryset.filter(bar_date__gte=start)
        if end is not None:
            queryset = queryset.filter(bar_date__lte=end)
        grouped: dict[str, list[PriceBar]] = {code: [] for code in normalized_codes}
        for model in queryset.order_by("asset_code", "-bar_date", "-revision_number", "-pk"):
            bar = self._from_model(model)
            for code in assets_by_candidate.get(model.asset_code, ()):
                grouped[code].append(bar)
        # ``limit`` is per requested asset, matching the prior per-code resolver contract.
        return {code: tuple(bars[:limit]) for code, bars in grouped.items()}

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

    def list_asset_codes_with_observation_on_date(
        self,
        asset_codes: tuple[str, ...],
        observation_date: date,
    ) -> tuple[str, ...]:
        """Return requested assets with any persisted price bar on one date."""

        if not asset_codes:
            return ()
        rows = PriceBarModel._default_manager.filter(
            asset_code__in=asset_codes,
            bar_date=observation_date,
            freq__in=_TARGET_SESSION_PRICE_FREQUENCIES,
        ).values_list("asset_code", flat=True)
        return tuple(sorted({str(asset_code) for asset_code in rows}))


def _price_bar_publication_reference(row: PriceBarModel) -> PublicationFactReference:
    """Convert one exact price row to immutable publication evidence."""

    return publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.price.bar",
    )


__all__ = ["PriceBarRepository"]
