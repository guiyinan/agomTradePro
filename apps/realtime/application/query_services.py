"""Application queries backing realtime SDK contracts."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Protocol, TypedDict

from apps.realtime.domain.rules import daily_market_observation_status
from core.exceptions import DataFetchError
from shared.numeric import safe_float

from .price_polling_service import CachedMonitoredPriceScope, PricePollingUseCase


class SectorPerformanceRepositoryProtocol(Protocol):
    """Minimal persisted-read contract required by the realtime projection."""

    def get_all_sectors(self) -> list[Any]:
        """Return active sector definitions."""

    def get_latest_sector_index(self, sector_code: str) -> Any | None:
        """Return the latest persisted index row for one sector."""


class CachedTopMoversResult(TypedDict):
    """Top-movers projection retaining the complete monitored-asset denominator."""

    results: list[dict[str, Any]]
    count: int
    source: Literal["cached_monitored_prices"]
    scope: Literal["all_monitored_assets"]
    scope_available: bool
    requested: int | None
    qualified: int | None
    unavailable: int | None
    rankable: int | None
    unrankable: int | None
    outcome: Literal["success", "partial", "blocked"]
    is_reliable: bool
    is_stale: bool | None
    must_not_use_for_decision: bool
    blocked_reason: str


def get_cached_top_movers_result(
    *,
    direction: str = "up",
    limit: int = 10,
) -> CachedTopMoversResult:
    """Return ranked cached prices with complete monitored-scope status."""

    monitored: CachedMonitoredPriceScope = PricePollingUseCase().get_cached_monitored_price_scope()
    prices = monitored["prices"]
    reverse = direction == "up"

    requested = monitored["requested"]
    qualified = monitored["qualified"]
    unavailable = monitored["unavailable"]
    counts_resolved = (
        isinstance(requested, int)
        and not isinstance(requested, bool)
        and requested >= 0
        and isinstance(qualified, int)
        and not isinstance(qualified, bool)
        and qualified >= 0
        and isinstance(unavailable, int)
        and not isinstance(unavailable, bool)
        and unavailable >= 0
        and requested == qualified + unavailable
        and qualified == len(prices)
    )
    if not monitored["scope_available"] or not counts_resolved:
        return {
            "results": [],
            "count": 0,
            "source": "cached_monitored_prices",
            "scope": "all_monitored_assets",
            "scope_available": False,
            "requested": None,
            "qualified": None,
            "unavailable": None,
            "rankable": None,
            "unrankable": None,
            "outcome": "blocked",
            "is_reliable": False,
            "is_stale": None,
            "must_not_use_for_decision": True,
            "blocked_reason": "monitored_price_scope_unavailable",
        }

    assert isinstance(requested, int) and not isinstance(requested, bool)
    assert isinstance(qualified, int) and not isinstance(qualified, bool)
    assert isinstance(unavailable, int) and not isinstance(unavailable, bool)

    ranked_prices: list[tuple[float, dict[str, Any]]] = []
    for item in prices:
        raw_change_pct = item.get("change_pct")
        if isinstance(raw_change_pct, bool):
            continue
        change_pct = safe_float(raw_change_pct, default=None)
        if change_pct is not None:
            ranked_prices.append((change_pct, item))

    rankable = len(ranked_prices)
    unrankable = qualified - rankable
    ranked_prices.sort(key=lambda ranked_price: ranked_price[0], reverse=reverse)
    results = [item for _, item in ranked_prices[:limit]]

    if requested == 0:
        outcome: Literal["success", "partial", "blocked"] = "blocked"
        blocked_reason = "monitored_asset_scope_empty"
    elif rankable == 0:
        outcome = "blocked"
        blocked_reason = (
            "monitored_top_movers_change_pct_unavailable"
            if unrankable > 0
            else monitored["blocked_reason"] or "fresh_cached_prices_unavailable"
        )
    elif unavailable > 0:
        outcome = "partial"
        blocked_reason = monitored["blocked_reason"] or "monitored_cached_prices_incomplete"
    elif unrankable > 0:
        outcome = "partial"
        blocked_reason = "monitored_top_movers_change_pct_unavailable"
    else:
        outcome = "success"
        blocked_reason = ""
    is_reliable = outcome == "success"
    return {
        "results": results,
        "count": len(results),
        "source": "cached_monitored_prices",
        "scope": "all_monitored_assets",
        "scope_available": True,
        "requested": requested,
        "qualified": qualified,
        "unavailable": unavailable,
        "rankable": rankable,
        "unrankable": unrankable,
        "outcome": outcome,
        "is_reliable": is_reliable,
        "is_stale": monitored["is_stale"],
        "must_not_use_for_decision": not is_reliable,
        "blocked_reason": blocked_reason,
    }


def list_cached_top_movers_payloads(
    *,
    direction: str = "up",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return only a fully fresh, complete, and rankable legacy Top Movers list.

    Raises:
        DataFetchError: If the monitored denominator, cached prices, or ranking
            change percentages are partial, blocked, or unknown.
    """

    result = get_cached_top_movers_result(direction=direction, limit=limit)
    requested = result["requested"]
    qualified = result["qualified"]
    unavailable = result["unavailable"]
    rankable = result["rankable"]
    unrankable = result["unrankable"]
    if (
        result["scope_available"] is not True
        or result["outcome"] != "success"
        or result["is_reliable"] is not True
        or result["is_stale"] is not False
        or result["must_not_use_for_decision"] is not False
        or not isinstance(requested, int)
        or isinstance(requested, bool)
        or requested <= 0
        or not isinstance(qualified, int)
        or isinstance(qualified, bool)
        or qualified != requested
        or not isinstance(unavailable, int)
        or isinstance(unavailable, bool)
        or unavailable != 0
        or not isinstance(rankable, int)
        or isinstance(rankable, bool)
        or rankable != qualified
        or not isinstance(unrankable, int)
        or isinstance(unrankable, bool)
        or unrankable != 0
        or result["blocked_reason"] != ""
    ):
        raise DataFetchError(
            message="Top Movers list requires a complete fresh-price and rankability scope.",
            code="MONITORED_TOP_MOVERS_NOT_DECISION_USABLE",
            details={
                "outcome": result["outcome"],
                "requested": requested,
                "qualified": qualified,
                "unavailable": unavailable,
                "rankable": rankable,
                "unrankable": unrankable,
                "blocked_reason": result["blocked_reason"],
            },
        )
    return result["results"]


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
