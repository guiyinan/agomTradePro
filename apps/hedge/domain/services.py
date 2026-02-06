"""
Hedge Module Domain Layer - Services

Pure Python business logic for hedge portfolio management.
Follows four-layer architecture: NO external dependencies (no pandas, numpy, django).

Uses only:
- Python standard library (typing, dataclasses, math)
- Pure business algorithms
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Callable
import math

from apps.hedge.domain.entities import (
    HedgeMethod,
    HedgePair,
    CorrelationMetric,
    HedgePortfolio,
    HedgeAlert,
    HedgeAlertType,
    get_common_hedge_pairs,
)
from shared.infrastructure.correlation import (
    RollingCorrelationCalculator,
    CorrelationResult,
)


@dataclass
class HedgeContext:
    """Context for hedge calculation"""
    calc_date: date
    hedge_pairs: List[HedgePair]

    # Data accessors (injected from Infrastructure layer)
    get_asset_prices: Callable[[str, date, int], Optional[List[float]]]  # (asset, end_date, days) -> [prices]
    get_asset_name: Callable[[str], Optional[str]]  # (asset_code) -> asset_name


class CorrelationMonitor:
    """
    Pure Python correlation monitoring service.

    Domain layer service - NO external dependencies.
    """

    def __init__(self, context: HedgeContext):
        self.context = context
        self.correlation_calculator = RollingCorrelationCalculator()

    def calculate_correlation(
        self,
        asset1: str,
        asset2: str,
        window_days: int = 60
    ) -> Optional[CorrelationMetric]:
        """
        Calculate correlation metrics between two assets.

        Args:
            asset1: First asset code
            asset2: Second asset code
            window_days: Lookback window in days

        Returns:
            CorrelationMetric with correlation statistics
        """
        # Get price data for both assets
        prices1 = self.context.get_asset_prices(asset1, self.context.calc_date, window_days + 60)
        prices2 = self.context.get_asset_prices(asset2, self.context.calc_date, window_days + 60)

        if not prices1 or not prices2 or len(prices1) != len(prices2):
            return None

        # Use last window_days prices
        prices1_window = prices1[-window_days:]
        prices2_window = prices2[-window_days:]

        # Calculate correlation using shared calculator
        correlation = self.correlation_calculator.calculate_correlation(
            prices1_window,
            prices2_window
        )

        # Calculate covariance
        covariance = self.correlation_calculator.calculate_covariance(
            prices1_window,
            prices2_window
        )

        # Calculate beta (asset1 to asset2)
        beta = self.correlation_calculator.calculate_beta(
            prices1_window,
            prices2_window
        )

        # Calculate trend
        correlation_trend = self._calculate_correlation_trend(
            prices1, prices2, window_days
        )

        # Check for alerts
        alert, alert_type = self._check_correlation_alert(
            asset1, asset2, correlation
        )

        # Calculate correlation moving average
        correlation_ma = self._calculate_rolling_correlation_ma(
            prices1, prices2, window_days
        )

        return CorrelationMetric(
            asset1=asset1,
            asset2=asset2,
            calc_date=self.context.calc_date,
            window_days=window_days,
            correlation=correlation,
            covariance=covariance,
            beta=beta,
            correlation_trend=correlation_trend,
            correlation_ma=correlation_ma,
            alert=alert,
            alert_type=alert_type,
        )

    def calculate_correlation_matrix(
        self,
        asset_codes: List[str],
        window_days: int = 60
    ) -> Dict[str, Dict[str, float]]:
        """
        Calculate correlation matrix for multiple assets.

        Returns:
            {asset1: {asset2: correlation}}
        """
        correlation_matrix = {}

        for i, asset1 in enumerate(asset_codes):
            correlation_matrix[asset1] = {}
            for asset2 in asset_codes:
                if asset1 == asset2:
                    correlation_matrix[asset1][asset2] = 1.0
                elif asset2 not in correlation_matrix:
                    # Only calculate each pair once
                    metric = self.calculate_correlation(asset1, asset2, window_days)
                    correlation_matrix[asset1][asset2] = (
                        metric.correlation if metric else 0.0
                    )

        return correlation_matrix

    def monitor_hedge_pairs(
        self,
        pairs: Optional[List[HedgePair]] = None
    ) -> List[HedgeAlert]:
        """
        Monitor all hedge pairs and generate alerts if needed.

        Args:
            pairs: List of hedge pairs to monitor (default: all)

        Returns:
            List of HedgeAlert for any issues found
        """
        if pairs is None:
            pairs = self.context.hedge_pairs

        alerts = []

        for pair in pairs:
            metric = self.calculate_correlation(
                pair.long_asset,
                pair.hedge_asset,
                pair.correlation_window
            )

            if metric is None:
                continue

            # Check correlation breakdown
            if metric.correlation > pair.max_correlation + pair.correlation_alert_threshold:
                alerts.append(HedgeAlert(
                    pair_name=pair.name,
                    alert_date=self.context.calc_date,
                    alert_type=HedgeAlertType.CORRELATION_BREAKDOWN,
                    severity="high",
                    message=f"对冲相关性失效: {metric.correlation:.2f} 超出阈值 {pair.max_correlation:.2f}",
                    current_value=metric.correlation,
                    threshold_value=pair.max_correlation,
                    action_required="考虑调整对冲比例或更换对冲标的",
                    action_priority=7,
                ))

            # Check if correlation is too weak (close to zero)
            if abs(metric.correlation) < 0.1:
                alerts.append(HedgeAlert(
                    pair_name=pair.name,
                    alert_date=self.context.calc_date,
                    alert_type=HedgeAlertType.CORRELATION_BREAKDOWN,
                    severity="medium",
                    message=f"对冲相关性过弱: {metric.correlation:.2f}，对冲效果有限",
                    current_value=metric.correlation,
                    threshold_value=0.1,
                    action_required="考虑增加对冲仓位或更换对冲标的",
                    action_priority=5,
                ))

        return alerts

    def _calculate_correlation_trend(
        self,
        prices1: List[float],
        prices2: List[float],
        window_days: int
    ) -> str:
        """Determine if correlation is trending up, down, or stable"""
        if len(prices1) < window_days * 2:
            return "stable"

        # Calculate early and late period correlations
        early_prices1 = prices1[-window_days*2:-window_days]
        early_prices2 = prices2[-window_days*2:-window_days]
        late_prices1 = prices1[-window_days:]
        late_prices2 = prices2[-window_days:]

        early_corr = self.correlation_calculator.calculate_correlation(
            early_prices1, early_prices2
        )
        late_corr = self.correlation_calculator.calculate_correlation(
            late_prices1, late_prices2
        )

        diff = late_corr - early_corr

        if abs(diff) < 0.1:
            return "stable"
        elif diff > 0:
            return "increasing"
        else:
            return "decreasing"

    def _check_correlation_alert(
        self,
        asset1: str,
        asset2: str,
        correlation: float
    ) -> Tuple[Optional[str], Optional[str]]:
        """Check if correlation triggers an alert"""
        # Find the hedge pair for these assets
        for pair in self.context.hedge_pairs:
            if (pair.long_asset == asset1 and pair.hedge_asset == asset2) or \
               (pair.long_asset == asset2 and pair.hedge_asset == asset1):

                if correlation > pair.max_correlation + pair.correlation_alert_threshold:
                    return (
                        f"相关性超出阈值: {correlation:.2f} > {pair.max_correlation:.2f}",
                        "correlation_high"
                    )
                elif correlation < pair.min_correlation - pair.correlation_alert_threshold:
                    return (
                        f"相关性低于阈值: {correlation:.2f} < {pair.min_correlation:.2f}",
                        "correlation_low"
                    )

        return None, None

    def _calculate_rolling_correlation_ma(
        self,
        prices1: List[float],
        prices2: List[float],
        window_days: int
    ) -> float:
        """Calculate moving average of correlation"""
        if len(prices1) < window_days * 3:
            # Need at least 3 windows for meaningful MA
            return 0.0

        # Calculate correlations over rolling windows
        correlations = []
        step = window_days // 3  # Use 3 overlapping windows

        for i in range(3):
            start = len(prices1) - window_days - (2 - i) * step
            end = len(prices1) - (2 - i) * step
            if start >= 0 and end > start:
                window_prices1 = prices1[start:end]
                window_prices2 = prices2[start:end]
                if len(window_prices1) == len(window_prices2) and len(window_prices1) >= 20:
                    corr = self.correlation_calculator.calculate_correlation(
                        window_prices1,
                        window_prices2
                    )
                    correlations.append(corr)

        if not correlations:
            return 0.0

        return sum(correlations) / len(correlations)


class HedgeRatioCalculator:
    """
    Pure Python hedge ratio calculator.

    Domain layer service - NO external dependencies.
    """

    def __init__(self, context: HedgeContext):
        self.context = context
        self.correlation_calculator = RollingCorrelationCalculator()

    def calculate_hedge_ratio(
        self,
        pair: HedgePair
    ) -> Tuple[float, Dict]:
        """
        Calculate optimal hedge ratio for a hedge pair.

        Args:
            pair: HedgePair configuration

        Returns:
            Tuple of (hedge_ratio, details_dict)
        """
        # Get price data
        long_prices = self.context.get_asset_prices(
            pair.long_asset,
            self.context.calc_date,
            pair.correlation_window + 60
        )
        hedge_prices = self.context.get_asset_prices(
            pair.hedge_asset,
            self.context.calc_date,
            pair.correlation_window + 60
        )

        if not long_prices or not hedge_prices:
            return 0.5, {"method": "default", "reason": "Insufficient data"}

        # Use recent prices
        long_prices_window = long_prices[-pair.correlation_window:]
        hedge_prices_window = hedge_prices[-pair.correlation_window:]

        if pair.hedge_method == HedgeMethod.BETA:
            return self._calculate_beta_hedge_ratio(
                long_prices_window,
                hedge_prices_window,
                pair.beta_target
            )

        elif pair.hedge_method == HedgeMethod.MIN_VARIANCE:
            return self._calculate_min_variance_hedge_ratio(
                long_prices_window,
                hedge_prices_window
            )

        elif pair.hedge_method == HedgeMethod.EQUAL_RISK:
            return self._calculate_equal_risk_hedge_ratio(
                long_prices_window,
                hedge_prices_window
            )

        elif pair.hedge_method == HedgeMethod.DOLLAR_NEUTRAL:
            return self._calculate_dollar_neutral_ratio(
                long_prices_window,
                hedge_prices_window
            )

        else:  # FIXED_RATIO or default
            return pair.target_hedge_weight / pair.target_long_weight, {
                "method": "fixed",
                "ratio": pair.target_hedge_weight / pair.target_long_weight
            }

    def _calculate_beta_hedge_ratio(
        self,
        long_prices: List[float],
        hedge_prices: List[float],
        beta_target: Optional[float] = None
    ) -> Tuple[float, Dict]:
        """Calculate beta-based hedge ratio"""
        beta = self.correlation_calculator.calculate_beta(
            long_prices,
            hedge_prices
        )

        if beta_target is not None:
            # Target a specific beta
            hedge_ratio = max(0, min(1, beta / beta_target))
        else:
            # Full beta hedge
            hedge_ratio = max(0, min(1, beta))

        return hedge_ratio, {
            "method": "beta",
            "beta": beta,
            "beta_target": beta_target,
        }

    def _calculate_min_variance_hedge_ratio(
        self,
        long_prices: List[float],
        hedge_prices: List[float]
    ) -> Tuple[float, Dict]:
        """
        Calculate minimum variance hedge ratio.

        h* = Cov(long, hedge) / Var(hedge)
        """
        if len(hedge_prices) < 2:
            return 0.5, {"method": "default", "reason": "Insufficient data"}

        # Calculate returns
        long_returns = self._calculate_returns(long_prices)
        hedge_returns = self._calculate_returns(hedge_prices)

        if not long_returns or not hedge_returns:
            return 0.5, {"method": "default", "reason": "Cannot calculate returns"}

        # Calculate covariance and variance
        n = len(long_returns)

        mean_long = sum(long_returns) / n
        mean_hedge = sum(hedge_returns) / n

        covariance = sum(
            (l - mean_long) * (h - mean_hedge)
            for l, h in zip(long_returns, hedge_returns)
        ) / (n - 1)

        variance_hedge = sum((h - mean_hedge) ** 2 for h in hedge_returns) / (n - 1)

        if variance_hedge == 0:
            return 0.0, {"method": "min_variance", "reason": "Zero variance in hedge asset"}

        hedge_ratio = -covariance / variance_hedge  # Negative for hedging

        # Clamp to reasonable range
        hedge_ratio = max(0, min(2, hedge_ratio))

        return hedge_ratio, {
            "method": "min_variance",
            "covariance": covariance,
            "variance_hedge": variance_hedge,
        }

    def _calculate_equal_risk_hedge_ratio(
        self,
        long_prices: List[float],
        hedge_prices: List[float]
    ) -> Tuple[float, Dict]:
        """
        Calculate equal risk contribution hedge ratio.

        Allocate so each asset contributes equal risk.
        """
        # Calculate volatilities
        long_vol = self._calculate_volatility(long_prices)
        hedge_vol = self._calculate_volatility(hedge_prices)

        if hedge_vol == 0:
            return 0.0, {"method": "equal_risk", "reason": "Zero volatility in hedge asset"}

        # Inverse volatility weighting
        inv_long = 1.0 / max(long_vol, 0.0001)
        inv_hedge = 1.0 / max(hedge_vol, 0.0001)

        total_inv = inv_long + inv_hedge
        long_weight = inv_long / total_inv
        hedge_weight = inv_hedge / total_inv

        hedge_ratio = hedge_weight / long_weight if long_weight > 0 else 1.0

        return hedge_ratio, {
            "method": "equal_risk",
            "long_vol": long_vol,
            "hedge_vol": hedge_vol,
            "long_weight": long_weight,
            "hedge_weight": hedge_weight,
        }

    def _calculate_dollar_neutral_ratio(
        self,
        long_prices: List[float],
        hedge_prices: List[float]
    ) -> Tuple[float, Dict]:
        """
        Calculate dollar neutral hedge ratio.

        Equal dollar amounts in long and short positions.
        """
        # Get current prices
        long_price = long_prices[-1] if long_prices else 1.0
        hedge_price = hedge_prices[-1] if hedge_prices else 1.0

        if hedge_price == 0:
            return 0.0, {"method": "dollar_neutral", "reason": "Zero hedge price"}

        # Hedge ratio = (long_dollar / hedge_dollar) * (hedge_price / long_price)
        # For dollar neutral, we want: long_dollar = hedge_dollar
        hedge_ratio = hedge_price / long_price

        return hedge_ratio, {
            "method": "dollar_neutral",
            "long_price": long_price,
            "hedge_price": hedge_price,
        }

    def _calculate_returns(self, prices: List[float]) -> List[float]:
        """Calculate simple returns from price series"""
        returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                ret = (prices[i] - prices[i - 1]) / prices[i - 1]
                returns.append(ret)
        return returns

    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate annualized volatility"""
        returns = self._calculate_returns(prices)

        if not returns:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance)

        return std_return * math.sqrt(252)  # Annualize


class HedgePortfolioService:
    """
    Main service for hedge portfolio management.

    Domain layer - coordinates monitoring and calculation.
    """

    def __init__(self, context: HedgeContext):
        self.context = context
        self.correlation_monitor = CorrelationMonitor(context)
        self.hedge_calculator = HedgeRatioCalculator(context)

    def update_hedge_portfolio(
        self,
        pair: HedgePair
    ) -> Optional[HedgePortfolio]:
        """
        Update hedge portfolio state for a given pair.

        Args:
            pair: HedgePair configuration

        Returns:
            HedgePortfolio with current state
        """
        # Calculate hedge ratio
        hedge_ratio, details = self.hedge_calculator.calculate_hedge_ratio(pair)

        # Calculate correlation metrics
        correlation_metric = self.correlation_monitor.calculate_correlation(
            pair.long_asset,
            pair.hedge_asset,
            pair.correlation_window
        )

        if correlation_metric is None:
            return None

        # Determine if rebalance is needed
        target_hedge_weight = pair.target_hedge_weight
        current_hedge_weight = hedge_ratio * pair.target_long_weight

        rebalance_needed = abs(current_hedge_weight - target_hedge_weight) > pair.rebalance_trigger
        rebalance_reason = ""
        if rebalance_needed:
            rebalance_reason = (
                f"对冲比例 {current_hedge_weight:.2%} 偏离目标 {target_hedge_weight:.2%} "
                f"超过阈值 {pair.rebalance_trigger:.1%}"
            )

        # Calculate hedge effectiveness
        hedge_effectiveness = self._calculate_effectiveness(correlation_metric.correlation)

        return HedgePortfolio(
            pair_name=pair.name,
            trade_date=self.context.calc_date,
            long_weight=pair.target_long_weight,
            hedge_weight=current_hedge_weight,
            hedge_ratio=hedge_ratio,
            target_hedge_ratio=target_hedge_weight / pair.target_long_weight,
            current_correlation=correlation_metric.correlation,
            correlation_20d=correlation_metric.correlation_ma,
            correlation_60d=correlation_metric.correlation_ma,
            portfolio_beta=1 - hedge_ratio * correlation_metric.beta,
            hedge_effectiveness=hedge_effectiveness,
            rebalance_needed=rebalance_needed,
            rebalance_reason=rebalance_reason,
        )

    def get_correlation_matrix(
        self,
        asset_codes: List[str],
        window_days: int = 60
    ) -> Dict[str, Dict[str, float]]:
        """Get correlation matrix for specified assets"""
        return self.correlation_monitor.calculate_correlation_matrix(
            asset_codes, window_days
        )

    def check_hedge_effectiveness(
        self,
        pair: HedgePair
    ) -> Dict:
        """
        Check effectiveness of a hedge pair.

        Returns:
            Dictionary with effectiveness metrics
        """
        metric = self.correlation_monitor.calculate_correlation(
            pair.long_asset,
            pair.hedge_asset,
            pair.correlation_window
        )

        if metric is None:
            return {
                "error": "Unable to calculate correlation"
            }

        hedge_ratio, details = self.hedge_calculator.calculate_hedge_ratio(pair)

        effectiveness = self._calculate_effectiveness(metric.correlation)

        # Determine rating
        if effectiveness >= 0.8:
            rating = "优秀"
        elif effectiveness >= 0.6:
            rating = "良好"
        elif effectiveness >= 0.4:
            rating = "一般"
        else:
            rating = "较差"

        return {
            "pair_name": pair.name,
            "correlation": round(metric.correlation, 3),
            "beta": round(metric.beta, 3),
            "hedge_ratio": round(hedge_ratio, 3),
            "hedge_method": details.get("method", "unknown"),
            "effectiveness": round(effectiveness, 2),
            "rating": rating,
            "trend": metric.correlation_trend,
            "recommendation": self._get_recommendation(effectiveness, metric.correlation, pair),
        }

    def _calculate_effectiveness(self, correlation: float) -> float:
        """Calculate hedge effectiveness from correlation"""
        # Effectiveness is based on absolute correlation
        # Perfect negative correlation (-1) = 100% effective
        return abs(correlation)

    def _get_recommendation(
        self,
        effectiveness: float,
        correlation: float,
        pair: HedgePair
    ) -> str:
        """Get recommendation based on effectiveness"""
        if effectiveness < 0.3:
            return "对冲效果较差，建议更换对冲标的或调整策略"
        elif effectiveness < 0.5:
            return "对冲效果一般，建议关注相关性变化"
        elif correlation > pair.max_correlation:
            return "相关性超出阈值，建议调整对冲比例"
        else:
            return "对冲效果良好，维持当前配置"
