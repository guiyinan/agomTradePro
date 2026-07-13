"""realtime runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_get_realtime_price(asset_code: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.realtime.get_price(asset_code)


def _fallback_get_multiple_realtime_prices(
    asset_codes: list[str],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    prices = client.realtime.get_multiple_prices(asset_codes)
    return {
        "prices": prices,
        "total_count": len(prices),
    }


def _fallback_get_market_summary() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.realtime.get_market_summary()


def _fallback_realtime_read_sector_performance() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    sectors = client.realtime.get_sector_performance()
    if not isinstance(sectors, list):
        raise ValueError("realtime.read.sector_performance returned an invalid payload")
    return {"sectors": sectors, "total_count": len(sectors)}


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_realtime_price": _fallback_get_realtime_price,
    "get_multiple_realtime_prices": _fallback_get_multiple_realtime_prices,
    "get_market_summary": _fallback_get_market_summary,
    "realtime_read_sector_performance": _fallback_realtime_read_sector_performance,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
