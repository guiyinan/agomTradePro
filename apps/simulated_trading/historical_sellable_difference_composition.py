"""Composition root for the read-only historical quantity report."""

from apps.account.historical_position_source_composition import (
    build_legacy_portfolio_position_reader,
)
from apps.simulated_trading.application.historical_sellable_difference import (
    HistoricalSellableDifferenceService,
)
from apps.simulated_trading.infrastructure.historical_sellable_difference_repository import (
    DjangoHistoricalSellableDifferenceRepository,
)


def build_historical_sellable_difference_service() -> HistoricalSellableDifferenceService:
    """Compose public Account reads with Simulated Trading's own read repository."""

    return HistoricalSellableDifferenceService(
        source_reader=build_legacy_portfolio_position_reader(),
        repository=DjangoHistoricalSellableDifferenceRepository(),
    )
