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


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "sector_read_rotation_ranking": _fallback_sector_read_rotation_ranking,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
