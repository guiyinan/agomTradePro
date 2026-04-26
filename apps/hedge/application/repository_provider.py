"""Repository providers for hedge application consumers."""

from __future__ import annotations

from apps.hedge.infrastructure.providers import (
    CorrelationHistoryRepository,
    HedgeAlertRepository,
    HedgePairRepository,
    HedgePortfolioRepository,
)
from apps.hedge.infrastructure.services import HedgeIntegrationService


def get_hedge_pair_repository() -> HedgePairRepository:
    """Return the hedge pair repository."""

    return HedgePairRepository()


def get_hedge_correlation_repository() -> CorrelationHistoryRepository:
    """Return the hedge correlation repository."""

    return CorrelationHistoryRepository()


def get_hedge_portfolio_repository() -> HedgePortfolioRepository:
    """Return the hedge portfolio repository."""

    return HedgePortfolioRepository()


def get_hedge_alert_repository() -> HedgeAlertRepository:
    """Return the hedge alert repository."""

    return HedgeAlertRepository()


def get_hedge_integration_service() -> HedgeIntegrationService:
    """Return the hedge integration service."""

    return HedgeIntegrationService()
