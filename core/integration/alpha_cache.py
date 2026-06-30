"""Alpha cache bridges used by data_center services."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from apps.alpha.application.query_services import (
    collect_alpha_cache_codes as _collect_alpha_cache_codes,
)
from apps.alpha.application.query_services import (
    get_alpha_cache_earliest_trade_date as _get_alpha_cache_earliest_trade_date,
)
from apps.alpha.application.query_services import (
    normalize_alpha_cached_code as _normalize_alpha_cached_code,
)


def normalize_alpha_cached_code(raw_code: str) -> str | None:
    """Normalize one alpha cached code through the owning alpha parser."""

    return _normalize_alpha_cached_code(raw_code)


def collect_alpha_cache_codes(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    extra_codes: Iterable[str] = (),
) -> list[str]:
    """Collect canonical asset codes from alpha cached score payloads."""

    return _collect_alpha_cache_codes(
        start_date=start_date,
        end_date=end_date,
        extra_codes=extra_codes,
    )


def get_alpha_cache_earliest_trade_date():
    """Return the earliest intended trade date present in alpha score cache."""

    return _get_alpha_cache_earliest_trade_date()
