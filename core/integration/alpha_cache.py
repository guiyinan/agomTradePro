"""Alpha cache bridges used by data_center services."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date


def normalize_alpha_cached_code(raw_code: str) -> str | None:
    """Normalize one alpha cached code through the owning alpha parser."""
    from apps.alpha.infrastructure.cache_code_parser import normalize_cached_stock_code

    return normalize_cached_stock_code(raw_code)


def collect_alpha_cache_codes(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    extra_codes: Iterable[str] = (),
) -> list[str]:
    """Collect canonical asset codes from alpha cached score payloads."""
    from apps.alpha.infrastructure.cache_code_parser import (
        collect_cached_score_codes,
        normalize_cached_stock_code,
    )
    from apps.alpha.infrastructure.models import AlphaScoreCacheModel

    queryset = AlphaScoreCacheModel.objects.order_by("intended_trade_date", "id")
    if start_date is not None:
        queryset = queryset.filter(intended_trade_date__gte=start_date)
    if end_date is not None:
        queryset = queryset.filter(intended_trade_date__lte=end_date)

    normalized_codes: list[str] = []
    seen: set[str] = set()
    for cache in queryset:
        for code in collect_cached_score_codes(cache.scores or []):
            if code in seen:
                continue
            seen.add(code)
            normalized_codes.append(code)

    for raw_code in extra_codes:
        normalized = normalize_cached_stock_code(raw_code)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_codes.append(normalized)
    return normalized_codes


def get_alpha_cache_earliest_trade_date():
    """Return the earliest intended trade date present in alpha score cache."""
    from apps.alpha.infrastructure.models import AlphaScoreCacheModel

    return AlphaScoreCacheModel.objects.order_by("intended_trade_date").values_list(
        "intended_trade_date",
        flat=True,
    ).first()
