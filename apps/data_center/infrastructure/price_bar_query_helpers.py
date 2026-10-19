"""Bounded multi-asset price-bar lookup helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from apps.data_center.domain.entities import PriceBar
from apps.data_center.infrastructure.models import AssetAliasModel, AssetMasterModel, PriceBarModel
from apps.data_center.infrastructure.published_fact_versions import latest_fact_revisions

_NATURAL_KEY = ("asset_code", "bar_date", "freq", "adjustment", "source")
_TARGET_SESSION_PRICE_FREQUENCIES: tuple[str, ...] = (
    "1d",
    "60m",
    "30m",
    "15m",
    "5m",
    "1m",
)


def _get_bars_for_assets(
    asset_codes: Sequence[str],
    *,
    start: date | None,
    end: date | None,
    limit: int,
    model_mapper: Callable[[PriceBarModel], PriceBar],
    natural_key: tuple[str, ...],
    candidate_builder: Callable[[str], list[str]],
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
        candidates = candidate_builder(code)
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
        matching_codes: dict[str, list[str]] = {base_code: [] for base_code in bare_codes_by_base}
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
    queryset = latest_fact_revisions(PriceBarModel, natural_key).filter(
        asset_code__in=tuple(sorted(assets_by_candidate))
    )
    if start is not None:
        queryset = queryset.filter(bar_date__gte=start)
    if end is not None:
        queryset = queryset.filter(bar_date__lte=end)
    grouped: dict[str, list[PriceBar]] = {code: [] for code in normalized_codes}
    for model in queryset.order_by("asset_code", "-bar_date", "-revision_number", "-pk"):
        bar = model_mapper(model)
        for code in assets_by_candidate.get(model.asset_code, ()):
            grouped[code].append(bar)
    # ``limit`` is per requested asset, matching the prior per-code resolver contract.
    return {code: tuple(bars[:limit]) for code, bars in grouped.items()}


def _list_asset_codes_with_observation_on_date(
    asset_codes: tuple[str, ...],
    observation_date: date,
    target_frequencies: tuple[str, ...],
) -> tuple[str, ...]:
    """Return requested assets with any persisted price bar on one date."""

    if not asset_codes:
        return ()
    rows = PriceBarModel._default_manager.filter(
        asset_code__in=asset_codes,
        bar_date=observation_date,
        freq__in=target_frequencies,
    ).values_list("asset_code", flat=True)
    return tuple(sorted({str(asset_code) for asset_code in rows}))


def _list_asset_codes(as_of: date | None) -> list[str]:
    """Return assets with canonical price facts through the requested date."""

    queryset = PriceBarModel.objects.all()
    if as_of is not None:
        queryset = queryset.filter(bar_date__lte=as_of)
    return list(queryset.order_by("asset_code").values_list("asset_code", flat=True).distinct())
