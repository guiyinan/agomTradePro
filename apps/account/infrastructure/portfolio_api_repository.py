"""Compatibility constructor for the Simulated Trading portfolio bridge."""

from __future__ import annotations

from typing import Any

from apps.account.application.simulated_trading_gateway import (
    build_portfolio_api_repository,
)


class PortfolioApiRepository:
    """Preserve the legacy Account import path while returning the owner implementation."""

    def __new__(cls) -> Any:
        """Build the configured owner-side portfolio repository."""

        return build_portfolio_api_repository()


__all__ = ["PortfolioApiRepository"]
