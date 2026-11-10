"""Application contract for refreshing official event evidence before plan assembly."""

from __future__ import annotations

from typing import Protocol

from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity


class RebalanceJourneyOfficialEventRefresher(Protocol):
    """Refresh official disclosure captures for one exact set of portfolio identities."""

    def refresh(
        self,
        *,
        asset_identities: tuple[PortfolioRiskAssetIdentity, ...],
    ) -> tuple[PortfolioRiskAssetIdentity, ...]:
        """Return every exact identity whose durable official capture completed."""
        ...


__all__ = ("RebalanceJourneyOfficialEventRefresher",)
