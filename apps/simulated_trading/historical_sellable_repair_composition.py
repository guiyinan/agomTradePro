"""Composition root for the bounded native-simulated G5 repair command."""

from apps.simulated_trading.application.historical_sellable_repair import (
    HistoricalSellableRepairService,
)
from apps.simulated_trading.infrastructure.historical_sellable_difference_repository import (
    DjangoHistoricalSellableDifferenceRepository,
)


def build_historical_sellable_repair_service() -> HistoricalSellableRepairService:
    """Build the single-App repository that locks, re-proves, and journals a repair."""

    return HistoricalSellableRepairService(
        repository=DjangoHistoricalSellableDifferenceRepository(),
    )
