"""Application-level query helpers for cross-app equity access."""

from __future__ import annotations

from typing import Any

from apps.equity.application.repository_provider import (
    get_equity_valuation_repair_repository,
)


def get_valuation_repair_snapshot_map(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Return valuation repair snapshots keyed by upper security code."""
    normalized_codes = [code for code in stock_codes if code]
    if not normalized_codes:
        return {}
    return get_equity_valuation_repair_repository().get_snapshot_map(normalized_codes)
