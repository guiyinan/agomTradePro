"""Application contract for refreshing official event evidence before plan assembly."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from core.exceptions import AgomTradeProException


class RebalanceJourneyOfficialEventRefresher(Protocol):
    """Refresh official disclosure captures for one exact set of portfolio identities."""

    def refresh(
        self,
        *,
        asset_identities: tuple[PortfolioRiskAssetIdentity, ...],
        request_scope: RebalanceJourneyEventRequestScope,
        as_of: datetime,
    ) -> tuple[PortfolioRiskAssetIdentity, ...]:
        """Acknowledge exact refresh identities; durable proof is verified separately."""
        ...


def refresh_official_event_identities(
    refresher: RebalanceJourneyOfficialEventRefresher,
    *,
    asset_identities: tuple[PortfolioRiskAssetIdentity, ...],
    request_scope: RebalanceJourneyEventRequestScope,
    as_of: datetime,
) -> None:
    """Run the injected capture and require an exact complete identity acknowledgement."""

    if (
        type(request_scope) is not RebalanceJourneyEventRequestScope
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
        or type(asset_identities) is not tuple
        or not asset_identities
        or any(type(identity) is not PortfolioRiskAssetIdentity for identity in asset_identities)
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REQUEST_SCOPE_INVALID")
    try:
        refreshed_identities = refresher.refresh(
            asset_identities=asset_identities,
            request_scope=request_scope,
            as_of=as_of,
        )
    except RebalanceJourneyUnavailable:
        raise
    except (
        AgomTradeProException,
        ArithmeticError,
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_FAILED") from error
    if (
        type(refreshed_identities) is not tuple
        or any(
            type(identity) is not PortfolioRiskAssetIdentity for identity in refreshed_identities
        )
        or refreshed_identities != asset_identities
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_INCOMPLETE")


__all__ = ("RebalanceJourneyOfficialEventRefresher", "refresh_official_event_identities")
