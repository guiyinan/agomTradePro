"""Application queries backing realtime SDK contracts."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from apps.realtime.domain.rules import daily_market_observation_status

from .price_polling_service import PricePollingUseCase


class SectorPerformanceRepositoryProtocol(Protocol):
    """Minimal persisted-read contract required by the realtime projection."""

    def get_all_sectors(self) -> list[Any]:
        """Return active sector definitions."""

    def get_latest_sector_index(self, sector_code: str) -> Any | None:
        """Return the latest persisted index row for one sector."""


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


def list_sector_performance_payloads(
    repository: SectorPerformanceRepositoryProtocol,
) -> list[dict[str, Any]]:
    """Return the latest persisted index performance for active sectors."""

    results: list[dict[str, Any]] = []
    for sector in repository.get_all_sectors():
        latest = repository.get_latest_sector_index(sector.sector_code)
        if latest is None:
            continue
        is_stale, staleness_days = daily_market_observation_status(
            latest.trade_date,
            as_of_date=date.today(),
        )
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
                "observed_at": latest.trade_date.isoformat(),
                "freshness_status": "stale" if is_stale else "fresh",
                "staleness_days": staleness_days,
                "is_stale": is_stale,
                "must_not_use_for_decision": is_stale,
                "blocked_reason": "sector_price_stale" if is_stale else "",
            }
        )
    return sorted(
        results,
        key=lambda item: float(item.get("change_percent") or 0.0),
        reverse=True,
    )
