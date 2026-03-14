"""
Rotation Module Infrastructure Layer - Integration Services

Integration services that connect domain logic with data adapters.
This layer is NOT part of the four-layer architecture but provides
integration between Application layer and Infrastructure.
"""

from datetime import date, datetime
from typing import Dict, List, Optional, Callable
import logging

from apps.rotation.domain.entities import (
    AssetClass,
    RotationConfig,
    RotationSignal,
    RotationStrategyType,
)
from apps.rotation.domain.services import (
    RotationContext,
    RotationService,
)
from apps.rotation.infrastructure.adapters.price_adapter import (
    RotationPriceDataService,
    PriceDataCache,
)
from apps.rotation.infrastructure.repositories import (
    AssetClassRepository,
    RotationConfigRepository,
    RotationSignalRepository,
    MomentumScoreRepository,
)

logger = logging.getLogger(__name__)


class RotationIntegrationService:
    """
    High-level service for rotation operations.

    Integrates domain services with repositories and data adapters.
    """

    def __init__(
        self,
        price_service: Optional[RotationPriceDataService] = None,
    ):
        self.price_service = price_service or RotationPriceDataService()
        self.asset_repo = AssetClassRepository()
        self.config_repo = RotationConfigRepository()
        self.signal_repo = RotationSignalRepository()
        self.momentum_repo = MomentumScoreRepository()

    def generate_rotation_signal(
        self,
        config_name: str,
        signal_date: Optional[date] = None
    ) -> Optional[Dict]:
        """
        Generate rotation signal for a configuration.

        Args:
            config_name: Name of the rotation configuration
            signal_date: Date for signal (default: today)

        Returns:
            Dictionary with signal details
        """
        signal_date = signal_date or date.today()

        # Get configuration
        config = self.config_repo.get_by_name(config_name)
        if not config:
            logger.error(f"Configuration not found: {config_name}")
            return None

        # Get current regime from regime module
        current_regime = self._get_current_regime()

        # Create domain context
        def get_prices(asset_code: str, end_date: date, days: int) -> Optional[List[float]]:
            return self.price_service.get_prices(asset_code, end_date, days)

        def get_regime() -> Optional[str]:
            return current_regime

        context = RotationContext(
            calc_date=signal_date,
            asset_universe=config.asset_universe,
            get_asset_prices=get_prices,
            get_current_regime=get_regime,
        )

        # Generate signal using domain service
        try:
            domain_service = RotationService(context)
            signal = domain_service.generate_signal(config)

            # Save to database
            config_model = self.config_repo.get_model_by_name(config_name)
            if config_model:
                signal_model = self.signal_repo.save(signal, config_model.id)

                return {
                    'config_name': signal.config_name,
                    'signal_date': signal.signal_date.isoformat(),
                    'target_allocation': signal.target_allocation,
                    'current_regime': signal.current_regime,
                    'action_required': signal.action_required,
                    'reason': signal.reason,
                    'momentum_ranking': signal.momentum_ranking,
                }

        except Exception as e:
            logger.error(f"Failed to generate signal for {config_name}: {e}")
            return None

    def compare_assets(
        self,
        asset_codes: List[str],
        lookback_days: int = 60
    ) -> Dict:
        """
        Compare multiple assets across multiple dimensions.

        Args:
            asset_codes: List of asset codes to compare
            lookback_days: Number of days to look back for calculations

        Returns:
            Dictionary with comparison results
        """
        # Create domain context
        def get_prices(asset_code: str, end_date: date, days: int) -> Optional[List[float]]:
            return self.price_service.get_prices(asset_code, end_date, days)

        def get_regime() -> Optional[str]:
            return self._get_current_regime()

        context = RotationContext(
            calc_date=date.today(),
            asset_universe=asset_codes,
            get_asset_prices=get_prices,
            get_current_regime=get_regime,
        )

        # Get comparison using domain service
        domain_service = RotationService(context)
        comparison = domain_service.compare_assets(asset_codes)

        return {
            'calc_date': date.today().isoformat(),
            'lookback_days': lookback_days,
            'assets': comparison,
        }

    def get_correlation_matrix(
        self,
        asset_codes: List[str],
        window_days: int = 60
    ) -> Dict:
        """
        Get correlation matrix for specified assets.

        Args:
            asset_codes: List of asset codes
            window_days: Window for correlation calculation

        Returns:
            Dictionary with correlation matrix
        """
        from shared.infrastructure.correlation import NumPyCorrelationCalculator

        # Fetch price data for all assets
        price_dict = {}
        for asset_code in asset_codes:
            prices = self.price_service.get_prices(
                asset_code,
                date.today(),
                window_days + 30  # Add buffer
            )
            if prices:
                price_dict[asset_code] = prices[-window_days:]

        if not price_dict:
            return {
                'error': 'No price data available',
                'calc_date': date.today().isoformat(),
            }

        # Calculate correlation matrix
        calculator = NumPyCorrelationCalculator()
        correlation_matrix = calculator.calculate_correlation_matrix(
            price_dict,
            window_days
        )

        # Convert to dict format
        matrix_dict = {
            asset1: {
                asset2: correlation_matrix.get_correlation(asset1, asset2)
                for asset2 in asset_codes
            }
            for asset1 in asset_codes
        }

        return {
            'calc_date': date.today().isoformat(),
            'window_days': window_days,
            'assets': asset_codes,
            'correlation_matrix': matrix_dict,
        }

    def get_rotation_recommendation(self, strategy_type: str = 'momentum') -> Dict:
        """
        Get rotation recommendation based on strategy type.

        Args:
            strategy_type: 'momentum', 'regime_based', or 'risk_parity'

        Returns:
            Dictionary with recommendation
        """
        # Get active configuration for strategy type
        configs = self.config_repo.get_active()

        strategy_map = {
            'momentum': RotationStrategyType.MOMENTUM,
            'regime_based': RotationStrategyType.REGIME_BASED,
            'risk_parity': RotationStrategyType.RISK_PARITY,
        }

        target_strategy = strategy_map.get(strategy_type, RotationStrategyType.MOMENTUM)

        # Find matching configuration
        config = None
        for c in configs:
            if c.strategy_type == target_strategy:
                config = c
                break

        if not config:
            # Use first active config as fallback
            config = configs[0] if configs else None

        if not config:
            return {
                'error': 'No active rotation configuration found',
                'calc_date': date.today().isoformat(),
            }

        # Generate signal
        signal = self.generate_rotation_signal(config.name)

        if signal:
            signal['strategy_type'] = strategy_type
            signal['config_description'] = config.description
            return signal

        return {
            'error': 'Failed to generate rotation signal',
            'calc_date': date.today().isoformat(),
        }

    def get_asset_info(self, asset_code: str) -> Optional[Dict]:
        """
        Get information about a specific asset.

        Args:
            asset_code: Asset code

        Returns:
            Dictionary with asset information
        """
        asset = self.asset_repo.get_by_code(asset_code)

        if not asset:
            return None

        # Get recent prices
        prices = self.price_service.get_prices(asset_code, date.today(), 60)

        price_info = {}
        if prices and len(prices) > 1:
            current_price = prices[-1]
            prev_price = prices[-20] if len(prices) > 20 else prices[0]

            price_info = {
                'current_price': round(current_price, 3),
                'change_20d': round((current_price - prev_price) / prev_price * 100, 2) if prev_price > 0 else 0,
                'has_price_data': True,
            }
        else:
            price_info = {
                'current_price': None,
                'change_20d': None,
                'has_price_data': False,
            }

        return {
            'code': asset.code,
            'name': asset.name,
            'category': asset.category.value,
            'description': asset.description,
            'underlying_index': asset.underlying_index,
            'currency': asset.currency,
            'is_active': asset.is_active,
            **price_info,
        }

    def get_all_assets(self) -> List[Dict]:
        """Get information about all active assets."""
        assets = self.asset_repo.get_all_active()

        result = []
        for asset in assets:
            info = self.get_asset_info(asset.code)
            if info:
                result.append(info)

        return result

    def _get_current_regime(self) -> Optional[str]:
        """
        Get current macro regime from regime module.

        Returns:
            Current regime name or None
        """
        try:
            from apps.regime.application.current_regime import resolve_current_regime

            current_state = resolve_current_regime(as_of_date=date.today())
            if current_state:
                return current_state.dominant_regime
        except Exception as e:
            logger.warning(f"Failed to get current regime: {e}")

        return None

    def clear_price_cache(self):
        """Clear the price data cache."""
        self.price_service.clear_cache()


class RotationSignalScheduler:
    """
    Scheduler for automatically generating rotation signals.

    Can be used with Celery beat for periodic signal generation.
    """

    def __init__(
        self,
        integration_service: Optional[RotationIntegrationService] = None,
    ):
        self.service = integration_service or RotationIntegrationService()

    def generate_all_signals(self, signal_date: Optional[date] = None) -> Dict[str, any]:
        """
        Generate signals for all active configurations.

        Args:
            signal_date: Date for signal generation

        Returns:
            Summary of signal generation
        """
        signal_date = signal_date or date.today()

        configs = self.config_repo = RotationConfigRepository().get_active()

        results = {
            'signal_date': signal_date.isoformat(),
            'total_configs': len(configs),
            'successful': 0,
            'failed': 0,
            'signals': [],
        }

        for config in configs:
            try:
                signal = self.service.generate_rotation_signal(config.name, signal_date)
                if signal:
                    results['successful'] += 1
                    results['signals'].append({
                        'config': config.name,
                        'strategy': config.strategy_type.value,
                        'signal': signal,
                    })
                else:
                    results['failed'] += 1
            except Exception as e:
                logger.error(f"Failed to generate signal for {config.name}: {e}")
                results['failed'] += 1

        return results
