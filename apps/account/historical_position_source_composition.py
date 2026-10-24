"""Composition root for Account's public historical position reader."""

from apps.account.application.historical_position_source import ReadLegacyPortfolioPositions
from apps.account.infrastructure.historical_position_source_repository import (
    DjangoLegacyPortfolioPositionRepository,
)


def build_legacy_portfolio_position_reader() -> ReadLegacyPortfolioPositions:
    """Build the public Account Application reader over Account-owned storage."""

    return ReadLegacyPortfolioPositions(DjangoLegacyPortfolioPositionRepository())
