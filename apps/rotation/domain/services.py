"""
Rotation Module Domain Layer - Services

Pure Python business logic for asset rotation strategies.
Follows four-layer architecture: NO external dependencies (no pandas, numpy, django).

Uses only:
- Python standard library (typing, dataclasses, math)
- Pure business algorithms
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Callable
import math

from apps.rotation.domain.entities import (
    AssetCategory,
    AssetClass,
    RotationStrategyType,
    RotationConfig,
    RotationSignal,
    RotationPortfolio,
    MomentumScore,
    get_common_etf_assets,
    create_default_regime_allocation,
)


@dataclass
class RotationContext:
    """Context for rotation strategy calculation"""
    calc_date: date
    asset_universe: List[str]  # List of asset codes

    # Data accessors (injected from Infrastructure layer)
    get_asset_prices: Callable[[str, date, int], Optional[List[float]]]  # (asset, end_date, days) -> [prices]
    get_current_regime: Callable[[], Optional[str]]  # () -> regime_name


class MomentumRotationEngine:
    """
    Pure Python momentum-based rotation engine.

    Domain layer service - NO external dependencies.
    """

    def __init__(self, context: RotationContext):
        self.context = context

    def calculate_momentum_scores(
        self,
        periods: List[int] = None
    ) -> List[MomentumScore]:
        """
        Calculate momentum scores for all assets in universe.

        Args:
            periods: List of lookback periods in days (default: [20, 60, 120])

        Returns:
            List of MomentumScore sorted by composite_score descending
        """
        if periods is None:
            periods = [20, 60, 120]

        scores = []
        for asset_code in self.context.asset_universe:
            score = self._calculate_asset_momentum(asset_code, periods)
            if score:
                scores.append(score)

        # Calculate ranks
        scores = self._assign_ranks(scores)

        # Sort by composite score
        scores.sort(key=lambda s: s.composite_score, reverse=True)

        return scores

    def select_top_assets(
        self,
        momentum_scores: List[MomentumScore],
        top_n: int = 3
    ) -> List[str]:
        """Select top N assets by momentum score"""
        return [s.asset_code for s in momentum_scores[:top_n]]

    def generate_signal(
        self,
        config: RotationConfig
    ) -> RotationSignal:
        """
        Generate rotation signal based on momentum strategy.

        Args:
            config: Rotation configuration

        Returns:
            RotationSignal with target allocation
        """
        # Calculate momentum scores
        periods = config.params.get("momentum_periods", [20, 60, 120])
        scores = self.calculate_momentum_scores(periods)

        # Select top N assets
        top_assets = self.select_top_assets(scores, config.top_n)

        # Calculate equal weights
        weight = 1.0 / len(top_assets) if top_assets else 0.0
        target_allocation = {asset: weight for asset in top_assets}

        # Build momentum ranking
        momentum_ranking = [(s.asset_code, s.composite_score) for s in scores]

        # Generate signal
        signal = RotationSignal(
            config_name=config.name,
            signal_date=self.context.calc_date,
            target_allocation=target_allocation,
            momentum_ranking=momentum_ranking,
            action_required="rebalance" if top_assets else "hold",
            reason=f"Top {len(top_assets)} assets by momentum: {', '.join(top_assets)}",
        )

        return signal

    def _calculate_asset_momentum(
        self,
        asset_code: str,
        periods: List[int]
    ) -> Optional[MomentumScore]:
        """Calculate momentum score for a single asset"""
        # Get historical prices (need max period + buffer for calculations)
        max_period = max(periods) if periods else 120
        prices = self.context.get_asset_prices(asset_code, self.context.calc_date, max_period + 60)

        if not prices or len(prices) < max_period + 1:
            return None

        # Calculate momentum for each period
        momentum_values = {}
        for period in periods:
            if len(prices) > period:
                current_price = prices[-1]
                past_price = prices[-(period + 1)]
                momentum = (current_price - past_price) / past_price if past_price > 0 else 0
                momentum_values[f"momentum_{period}m"] = momentum

        # Extract period values
        momentum_1m = momentum_values.get("momentum_20", 0.0)
        momentum_3m = momentum_values.get("momentum_60", 0.0)
        momentum_6m = momentum_values.get("momentum_120", 0.0)
        momentum_12m = momentum_values.get("momentum_252", momentum_6m)  # Use 6m if 12m not available

        # Calculate composite score (weighted average)
        composite_score = (
            momentum_1m * 0.2 +
            momentum_3m * 0.3 +
            momentum_6m * 0.3 +
            momentum_12m * 0.2
        )

        # Calculate Sharpe ratios (simplified)
        sharpe_1m = self._calculate_sharpe_ratio(prices, 20)
        sharpe_3m = self._calculate_sharpe_ratio(prices, 60)

        # Determine MA signal
        ma_signal = self._calculate_ma_signal(prices)

        # Calculate trend strength
        trend_strength = self._calculate_trend_strength(prices)

        return MomentumScore(
            asset_code=asset_code,
            calc_date=self.context.calc_date,
            momentum_1m=momentum_1m,
            momentum_3m=momentum_3m,
            momentum_6m=momentum_6m,
            momentum_12m=momentum_12m,
            composite_score=composite_score,
            sharpe_1m=sharpe_1m,
            sharpe_3m=sharpe_3m,
            ma_signal=ma_signal,
            trend_strength=trend_strength,
        )

    def _calculate_sharpe_ratio(self, prices: List[float], period: int) -> float:
        """Calculate simplified Sharpe ratio for a period"""
        if len(prices) < period + 1:
            return 0.0

        # Calculate returns
        returns = []
        for i in range(len(prices) - period, len(prices)):
            if i > 0 and prices[i - 1] > 0:
                ret = (prices[i] - prices[i - 1]) / prices[i - 1]
                returns.append(ret)

        if not returns:
            return 0.0

        # Calculate mean and std
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance)

        if std_return == 0:
            return 0.0

        # Annualized Sharpe (assuming 252 trading days)
        sharpe = (mean_return * 252) / (std_return * math.sqrt(252))
        return sharpe

    def _calculate_ma_signal(self, prices: List[float]) -> str:
        """Calculate moving average signal"""
        if len(prices) < 60:
            return "neutral"

        current = prices[-1]
        ma20 = sum(prices[-20:]) / 20
        ma60 = sum(prices[-60:]) / 60

        if current > ma20 > ma60:
            return "bullish"
        elif current < ma20 < ma60:
            return "bearish"
        else:
            return "neutral"

    def _calculate_trend_strength(self, prices: List[float]) -> float:
        """Calculate trend strength (0-1) using linear regression slope"""
        if len(prices) < 20:
            return 0.0

        # Use last 20 prices
        n = min(20, len(prices))
        recent_prices = prices[-n:]

        # Simple linear regression
        x_values = list(range(n))
        y_values = recent_prices

        sum_x = sum(x_values)
        sum_y = sum(y_values)
        sum_xy = sum(x * y for x, y in zip(x_values, y_values))
        sum_x2 = sum(x * x for x in x_values)

        # Calculate slope
        denominator = n * sum_x2 - sum_x * sum_x
        if denominator == 0:
            return 0.0

        slope = (n * sum_xy - sum_x * sum_y) / denominator

        # Normalize by average price
        avg_price = sum_y / n
        if avg_price == 0:
            return 0.0

        # Trend strength as absolute normalized slope
        trend = abs(slope / avg_price) * 100  # Scale for readability

        # Clamp to 0-1
        return min(max(trend, 0.0), 1.0)

    def _assign_ranks(self, scores: List[MomentumScore]) -> List[MomentumScore]:
        """Assign ranks based on composite score"""
        if not scores:
            return scores

        # Sort by composite score
        sorted_scores = sorted(scores, key=lambda s: s.composite_score, reverse=True)

        # Assign ranks
        for i, score in enumerate(sorted_scores):
            # Can't modify frozen dataclass, so return new objects
            # For now, just track ranks externally
            pass

        return scores


class RegimeBasedRotationEngine:
    """
    Regime-based rotation engine.

    Allocates assets based on current macro regime.
    """

    def __init__(self, context: RotationContext):
        self.context = context

    def generate_signal(
        self,
        config: RotationConfig
    ) -> RotationSignal:
        """
        Generate rotation signal based on current regime.

        Args:
            config: Rotation configuration with regime_allocations

        Returns:
            RotationSignal with target allocation
        """
        # Get current regime
        current_regime = self.context.get_current_regime()

        if not current_regime:
            # Default to balanced allocation if no regime available
            target_allocation = self._get_balanced_allocation(config.asset_universe)
            reason = "No regime data available, using balanced allocation"
        else:
            # Get allocation for current regime
            regime_allocations = config.regime_allocations.get(current_regime, {})
            target_allocation = self._filter_allocation_to_universe(regime_allocations, config.asset_universe)
            reason = f"Current regime: {current_regime}"

        # Build momentum ranking for context
        momentum_engine = MomentumRotationEngine(self.context)
        periods = config.params.get("momentum_periods", [20, 60])
        momentum_scores = momentum_engine.calculate_momentum_scores(periods)
        momentum_ranking = [(s.asset_code, s.composite_score) for s in momentum_scores[:10]]

        return RotationSignal(
            config_name=config.name,
            signal_date=self.context.calc_date,
            target_allocation=target_allocation,
            current_regime=current_regime or "Unknown",
            momentum_ranking=momentum_ranking,
            action_required="rebalance",
            reason=reason,
        )

    def _get_balanced_allocation(self, universe: List[str]) -> Dict[str, float]:
        """Get balanced equal-weight allocation"""
        weight = 1.0 / len(universe) if universe else 0.0
        return {asset: weight for asset in universe}

    def _filter_allocation_to_universe(
        self,
        allocation: Dict[str, float],
        universe: List[str]
    ) -> Dict[str, float]:
        """Filter allocation to only include assets in universe"""
        filtered = {k: v for k, v in allocation.items() if k in universe}

        # Renormalize weights
        total_weight = sum(filtered.values())
        if total_weight > 0:
            filtered = {k: v / total_weight for k, v in filtered.items()}

        return filtered


class RiskParityRotationEngine:
    """
    Risk parity rotation engine.

    Allocates assets based on equal risk contribution.
    """

    def __init__(self, context: RotationContext):
        self.context = context

    def generate_signal(
        self,
        config: RotationConfig
    ) -> RotationSignal:
        """
        Generate rotation signal based on risk parity.

        Args:
            config: Rotation configuration

        Returns:
            RotationSignal with target allocation
        """
        # Calculate volatility for each asset
        volatilities = {}
        for asset_code in config.asset_universe:
            prices = self.context.get_asset_prices(asset_code, self.context.calc_date, config.lookback_period)
            if prices:
                vol = self._calculate_volatility(prices)
                volatilities[asset_code] = vol

        if not volatilities:
            # Fallback to equal weight
            target_allocation = {a: 1.0 / len(config.asset_universe) for a in config.asset_universe}
            reason = "Insufficient data for risk parity, using equal weight"
        else:
            # Inverse volatility weighting
            inv_vol_sum = sum(1.0 / v for v in volatilities.values() if v > 0)
            if inv_vol_sum > 0:
                target_allocation = {
                    asset: (1.0 / vol) / inv_vol_sum
                    for asset, vol in volatilities.items()
                    if vol > 0
                }
            else:
                target_allocation = {}
            reason = "Risk parity allocation based on inverse volatility"

        return RotationSignal(
            config_name=config.name,
            signal_date=self.context.calc_date,
            target_allocation=target_allocation,
            action_required="rebalance",
            reason=reason,
        )

    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate annualized volatility"""
        if len(prices) < 2:
            return 0.0

        # Calculate returns
        returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                ret = (prices[i] - prices[i - 1]) / prices[i - 1]
                returns.append(ret)

        if not returns:
            return 0.0

        # Calculate standard deviation
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance)

        # Annualize (assuming 252 trading days)
        return std_return * math.sqrt(252)


class RotationService:
    """
    Main service for rotation strategies.

    Domain layer - coordinates different strategy engines.
    """

    def __init__(self, context: RotationContext):
        self.context = context

    def generate_signal(self, config: RotationConfig) -> RotationSignal:
        """
        Generate rotation signal based on strategy type.

        Args:
            config: Rotation configuration

        Returns:
            RotationSignal with target allocation
        """
        if config.strategy_type == RotationStrategyType.MOMENTUM:
            engine = MomentumRotationEngine(self.context)
            return engine.generate_signal(config)

        elif config.strategy_type == RotationStrategyType.REGIME_BASED:
            engine = RegimeBasedRotationEngine(self.context)
            return engine.generate_signal(config)

        elif config.strategy_type == RotationStrategyType.RISK_PARITY:
            engine = RiskParityRotationEngine(self.context)
            return engine.generate_signal(config)

        else:
            # Default to momentum
            engine = MomentumRotationEngine(self.context)
            return engine.generate_signal(config)

    def compare_assets(self, asset_codes: List[str]) -> Dict[str, Dict]:
        """
        Compare multiple assets across multiple dimensions.

        Returns:
            Dictionary with comparison metrics
        """
        momentum_engine = MomentumRotationEngine(self.context)

        # Get momentum scores
        scores = momentum_engine.calculate_momentum_scores([20, 60, 120])

        # Filter to requested assets
        asset_scores = {s.asset_code: s for s in scores if s.asset_code in asset_codes}

        # Build comparison result
        comparison = {}
        for asset_code in asset_codes:
            if asset_code in asset_scores:
                score = asset_scores[asset_code]
                comparison[asset_code] = {
                    "composite_score": round(score.composite_score, 4),
                    "momentum_1m": round(score.momentum_1m, 4),
                    "momentum_3m": round(score.momentum_3m, 4),
                    "momentum_6m": round(score.momentum_6m, 4),
                    "ma_signal": score.ma_signal,
                    "trend_strength": round(score.trend_strength, 2),
                }
            else:
                comparison[asset_code] = {
                    "error": "No data available"
                }

        return comparison
