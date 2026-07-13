"""Application queries backing realtime SDK contracts."""

from __future__ import annotations

from typing import Any

from apps.sector.application.repository_provider import get_sector_repository

from .price_polling_service import PricePollingUseCase


def list_cached_top_movers_payloads(
    *,
    direction: str = "up",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return sorted cached monitored prices without polling or cache mutation."""

    prices = PricePollingUseCase().get_cached_monitored_prices()
    reverse = direction == "up"

    def _change_percent(item: dict[str, Any]) -> float:
        try:
            return float(item.get("change_pct") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return sorted(prices, key=_change_percent, reverse=reverse)[:limit]


def list_sector_performance_payloads() -> list[dict[str, Any]]:
    """Return the latest persisted index performance for active sectors."""

    repository = get_sector_repository()
    results: list[dict[str, Any]] = []
    for sector in repository.get_all_sectors():
        latest = repository.get_latest_sector_index(sector.sector_code)
        if latest is None:
            continue
        results.append(
            {
                "sector_code": sector.sector_code,
                "name": sector.sector_name,
                "level": sector.level,
                "trade_date": latest.trade_date.isoformat(),
                "close": latest.close,
                "change_percent": latest.change_pct,
                "volume": latest.volume,
                "amount": latest.amount,
            }
        )
    return sorted(
        results,
        key=lambda item: float(item.get("change_percent") or 0.0),
        reverse=True,
    )
