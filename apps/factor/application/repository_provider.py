"""Repository providers for factor application consumers."""

from __future__ import annotations

from apps.factor.infrastructure.providers import (
    FactorDefinitionRepository,
    FactorPortfolioConfigRepository,
    FactorPortfolioHoldingRepository,
)
from apps.factor.infrastructure.services import FactorIntegrationService


def get_factor_definition_repository() -> FactorDefinitionRepository:
    """Return the factor definition repository."""

    return FactorDefinitionRepository()


def get_factor_portfolio_config_repository() -> FactorPortfolioConfigRepository:
    """Return the factor portfolio configuration repository."""

    return FactorPortfolioConfigRepository()


def get_factor_portfolio_holding_repository() -> FactorPortfolioHoldingRepository:
    """Return the factor portfolio holding repository."""

    return FactorPortfolioHoldingRepository()


def get_factor_integration_service(
    *,
    cache_price_results: bool = True,
) -> FactorIntegrationService:
    """Return the factor integration service with explicit cache-write policy."""

    return FactorIntegrationService(cache_price_results=cache_price_results)
