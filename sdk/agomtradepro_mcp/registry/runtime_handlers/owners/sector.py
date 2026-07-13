"""sector runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_sector_read_rotation_ranking(
    regime: str | None = None,
    lookback_days: int = 20,
    level: str = "SW1",
    top_n: int = 10,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.sector.get_rotation_ranking(
        regime=regime,
        lookback_days=lookback_days,
        level=level,
        top_n=top_n,
    )


def _fallback_sector_read_score(sector_name: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    score = client.sector.get_sector_score(sector_name)
    if not isinstance(score, dict):
        raise ValueError("sector.read.score returned an invalid payload")
    return {"score": score}


def _fallback_sector_compute_analysis(
    sector_name: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
    return client.sector.analyze_sector(sector_name, parsed_date)


def _fallback_sector_compute_comparison(
    sector_names: list[str],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.sector.compare_sectors(list(sector_names))


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "sector_read_rotation_ranking": _fallback_sector_read_rotation_ranking,
    "sector_read_score": _fallback_sector_read_score,
    "sector_compute_analysis": _fallback_sector_compute_analysis,
    "sector_compute_comparison": _fallback_sector_compute_comparison,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
