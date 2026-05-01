"""Application-level query helpers for cross-app alpha access."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.alpha.application.repository_provider import get_qlib_model_registry_repository


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
