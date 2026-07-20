"""Compatibility composition for the canonical valuation application service."""

from django.utils import timezone

from apps.valuation.application.use_cases import AssetValuationService
from apps.valuation.infrastructure.providers import (
    AssetAnalysisValuationSource,
    DataCenterValuationFactSource,
    ObservableMarketPriceSource,
)

from .valuation_adapters import DecisionRhythmSnapshotSource


class AssetValuationProvider(AssetValuationService):
    """Preserve the recommendation provider contract while delegating to valuation."""

    def __init__(self) -> None:
        super().__init__(
            formal_source=AssetAnalysisValuationSource(),
            snapshot_source=DecisionRhythmSnapshotSource(),
            fact_source=DataCenterValuationFactSource(),
            market_price_source=ObservableMarketPriceSource(),
            today_provider=timezone.localdate,
        )
