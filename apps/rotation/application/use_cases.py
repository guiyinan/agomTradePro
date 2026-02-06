"""
Rotation Module Application Layer - Use Cases

Application use cases for the rotation module.
Orchestrates domain services and infrastructure adapters.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Callable

from apps.rotation.domain.entities import RotationConfig, RotationSignal
from apps.rotation.domain.services import (
    RotationContext,
    RotationService,
)
from apps.rotation.application.dtos import (
    RotationSignalRequest,
    RotationSignalResponse,
    AssetComparisonRequest,
    AssetComparisonResponse,
)


@dataclass
class RotationUseCaseContext:
    """Context for rotation use case execution"""
    calc_date: date
    asset_universe: List[str]

    # Repository accessors (injected)
    get_asset_prices: Callable[[str, date, int], Optional[List[float]]]
    get_current_regime: Callable[[], Optional[str]]
    get_rotation_config: Callable[[str], Optional[RotationConfig]]


class GenerateRotationSignalUseCase:
    """
    Use case: Generate rotation signal.

    Generates target allocation based on rotation strategy.
    """

    def __init__(self, context: RotationUseCaseContext):
        self.context = context

    def execute(self, request: RotationSignalRequest) -> RotationSignalResponse:
        """Execute rotation signal generation"""
        # Get configuration
        config = self.context.get_rotation_config(request.config_name)
        if not config:
            raise ValueError(f"Configuration not found: {request.config_name}")

        # Use request date or current date
        signal_date = request.signal_date or self.context.calc_date

        # Create domain context
        domain_context = RotationContext(
            calc_date=signal_date,
            asset_universe=config.asset_universe,
            get_asset_prices=self.context.get_asset_prices,
            get_current_regime=self.context.get_current_regime,
        )

        # Create service and generate signal
        service = RotationService(domain_context)
        signal = service.generate_signal(config)

        # Convert momentum ranking
        momentum_ranking = [
            {"asset": asset, "score": score}
            for asset, score in signal.momentum_ranking
        ]

        return RotationSignalResponse(
            config_name=signal.config_name,
            signal_date=signal.signal_date,
            target_allocation=signal.target_allocation,
            current_regime=signal.current_regime,
            action_required=signal.action_required,
            reason=signal.reason,
            momentum_ranking=momentum_ranking,
        )


class CompareAssetsUseCase:
    """
    Use case: Compare multiple assets.

    Returns comparison metrics for specified assets.
    """

    def __init__(self, context: RotationUseCaseContext):
        self.context = context

    def execute(self, request: AssetComparisonRequest) -> AssetComparisonResponse:
        """Execute asset comparison"""
        # Create domain context
        domain_context = RotationContext(
            calc_date=self.context.calc_date,
            asset_universe=request.asset_codes,
            get_asset_prices=self.context.get_asset_prices,
            get_current_regime=self.context.get_current_regime,
        )

        # Create service and compare
        service = RotationService(domain_context)
        comparison = service.compare_assets(request.asset_codes)

        return AssetComparisonResponse(
            assets=comparison,
            comparison_date=self.context.calc_date,
        )


class GetCurrentRegimeUseCase:
    """
    Use case: Get current macro regime.

    Returns the current macro regime for rotation.
    """

    def __init__(self, context: RotationUseCaseContext):
        self.context = context

    def execute(self) -> Optional[str]:
        """Execute get current regime"""
        return self.context.get_current_regime()
