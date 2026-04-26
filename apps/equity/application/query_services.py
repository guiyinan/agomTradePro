"""Application-level query helpers for cross-app equity access."""

from __future__ import annotations

from typing import Any

from apps.equity.infrastructure.providers import DjangoValuationRepairRepository


def get_valuation_repair_snapshot_map(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Return valuation repair snapshots keyed by upper security code."""
    normalized_codes = [code for code in stock_codes if code]
    if not normalized_codes:
        return {}
    return DjangoValuationRepairRepository().get_snapshot_map(normalized_codes)
