"""Application-level query helpers for cross-app alpha access."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from apps.alpha.application.repository_provider import (
    get_alpha_score_cache_repository,
    get_qlib_model_registry_repository,
)


def get_alpha_ic_trends(days: int) -> list[dict[str, Any]]:
    """Return chart-ready IC/ICIR trend rows for the last N days."""

    if days <= 0:
        return []

    rows = get_qlib_model_registry_repository().list_recent_metric_rows(days)
    row_by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        created_at = row.get("created_at")
        if created_at is None:
            continue
        row_by_date[created_at.date().isoformat()] = row

    trends: list[dict[str, Any]] = []
    base_date = date.today()
    for offset in range(days - 1, -1, -1):
        check_date = (base_date - timedelta(days=offset)).isoformat()
        row = row_by_date.get(check_date)
        trends.append(
            {
                "date": check_date,
                "ic": round(float(row["ic"]), 4) if row and row.get("ic") is not None else None,
                "icir": round(float(row["icir"]), 4)
                if row and row.get("icir") is not None
                else None,
                "rank_ic": round(float(row["rank_ic"]), 4)
                if row and row.get("rank_ic") is not None
                else None,
            }
        )
    return trends


def list_recent_alpha_score_cache_payloads(limit: int = 100) -> list[dict[str, Any]]:
    """Return recent alpha score cache rows in cache-warmup payload shape."""

    rows = get_alpha_score_cache_repository().list_recent_caches(limit=limit)
    return [
        {
            "universe_id": row.universe_id,
            "provider": row.provider_source,
            "asof_date": str(row.asof_date),
            "status": row.status,
        }
        for row in rows
    ]


def normalize_alpha_cached_code(raw_code: object) -> str | None:
    """Normalize one alpha cache code through the alpha application boundary."""

    normalized = get_alpha_score_cache_repository().normalize_cached_code(raw_code)
    return normalized or None


def collect_alpha_cache_codes(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    extra_codes: Iterable[str] = (),
) -> list[str]:
    """Collect canonical asset codes from alpha cached score payloads."""

    return get_alpha_score_cache_repository().collect_cache_codes(
        start_date=start_date,
        end_date=end_date,
        extra_codes=extra_codes,
    )


def get_alpha_cache_earliest_trade_date():
    """Return the earliest intended trade date present in alpha score cache."""

    return get_alpha_score_cache_repository().get_earliest_trade_date()
