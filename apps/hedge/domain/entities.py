"""
Hedge Module Domain Layer - Entities

Hedge portfolio management entities for risk mitigation.
Follows four-layer architecture: Domain layer has NO external dependencies.

Uses only:
- Python standard library (dataclasses, typing, enum, datetime)
- Pure business logic
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple


class HedgeMethod(Enum):
    """Hedge calculation methods"""
    BETA = "beta"                       # Beta-based hedge ratio
    MIN_VARIANCE = "min_variance"       # Minimum variance hedge ratio
    EQUAL_RISK = "equal_risk"           # Equal risk contribution
    DOLLAR_NEUTRAL = "dollar_neutral"   # Dollar neutral hedge
    FIXED_RATIO = "fixed_ratio"         # Fixed hedge ratio


class HedgeAlertType(Enum):
    """Types of hedge alerts"""
    CORRELATION_BREAKDOWN = "correlation_breakdown"  # Correlation breakdown
    HEDGE_RATIO_DRIFT = "hedge_ratio_drift"         # Hedge ratio drifted
    BETA_CHANGE = "beta_change"                     # Beta changed significantly
    LIQUIDITY_RISK = "liquidity_risk"               # Liquidity risk


@dataclass(frozen=True)
class HedgePair:
    """
    Hedge pair configuration entity.

    Defines a hedging relationship between two assets.
    Immutable value object (frozen=True).
    """
    name: str                              # Pair name (e.g., "股债对冲")
    long_asset: str                        # Long position asset code
    hedge_asset: str                       # Hedge asset code
    hedge_method: HedgeMethod              # Hedge calculation method
    target_long_weight: float              # Target long weight (0-1)
    target_hedge_weight: float = 0.0       # Target hedge weight (0-1)

    # Rebalance triggers
    rebalance_trigger: float = 0.05        # Rebalance when weight drifts > 5%
    correlation_window: int = 60           # Correlation calculation window (days)

    # Correlation monitoring
    min_correlation: float = -0.3          # Minimum acceptable correlation
    max_correlation: float = -0.9          # Maximum (most negative) correlation
    correlation_alert_threshold: float = 0.2  # Alert if correlation drifts > 0.2

    # Risk limits
    max_hedge_cost: float = 0.05           # Maximum acceptable hedge cost (5%)
    beta_target: float | None = None    # Target beta for beta hedging

    # Status
    is_active: bool = True                 # Whether this pair is active

    def __post_init__(self):
        """Validate hedge pair"""
        if not self.name:
            raise ValueError("Pair name cannot be empty")
        if not self.long_asset:
            raise ValueError("Long asset cannot be empty")
        if not self.hedge_asset:
            raise ValueError("Hedge asset cannot be empty")
        if self.long_asset == self.hedge_asset:
            raise ValueError("Long and hedge assets cannot be the same")
        if not (0 <= self.target_long_weight <= 1):
            raise ValueError("target_long_weight must be between 0 and 1")
        if not (0 <= self.target_hedge_weight <= 1):
            raise ValueError("target_hedge_weight must be between 0 and 1")


@dataclass(frozen=True)
class CorrelationMetric:
    """
    Correlation metric value object.

    Represents correlation statistics between two assets.
    """
    asset1: str                            # First asset code
    asset2: str                            # Second asset code
    calc_date: date                        # Calculation date
    window_days: int                       # Calculation window

    # Correlation statistics
    correlation: float                     # Correlation coefficient (-1 to 1)
    covariance: float = 0.0                # Covariance
    beta: float = 0.0                      # Beta of asset1 to asset2

    # Additional metrics
    p_value: float = 0.0                   # Statistical significance
    standard_error: float = 0.0            # Standard error of correlation

    # Trend information
    correlation_trend: str = "neutral"     # increasing, decreasing, stable
    correlation_ma: float = 0.0            # Moving average of correlation

    # Alert information
    alert: str | None = None            # Alert message if any
    alert_type: str | None = None       # Type of alert

    def __post_init__(self):
        """Validate correlation metric"""
        if not self.asset1:
            raise ValueError("asset1 cannot be empty")
        if not self.asset2:
            raise ValueError("asset2 cannot be empty")
        if not (-1 <= self.correlation <= 1):
            raise ValueError("correlation must be between -1 and 1")


@dataclass(frozen=True)
class HedgePortfolio:
    """
    Hedge portfolio value object.

    Represents the current state of a hedged portfolio.
    """
    pair_name: str                          # Hedge pair name
    trade_date: date                        # Trade date

    # Current positions
    long_weight: float                      # Current long weight
    hedge_weight: float                     # Current hedge weight

    # Hedge metrics
    hedge_ratio: float                      # Actual hedge ratio
    target_hedge_ratio: float = 0.0         # Target hedge ratio

    # Correlation metrics
    current_correlation: float = 0.0        # Current correlation
    correlation_20d: float = 0.0            # 20-day average correlation
    correlation_60d: float = 0.0            # 60-day average correlation

    # Portfolio metrics
    portfolio_beta: float = 0.0             # Portfolio beta
    portfolio_volatility: float = 0.0       # Portfolio volatility
    hedge_effectiveness: float = 0.0        # Hedge effectiveness (0-1)

    # Performance
    daily_return: float = 0.0               # Daily return
    unhedged_return: float = 0.0            # Return without hedge
    hedge_return: float = 0.0               # Return from hedge position

    # Risk metrics
    value_at_risk: float = 0.0              # VaR
    max_drawdown: float = 0.0               # Maximum drawdown

    # Status
    rebalance_needed: bool = False          # Whether rebalance is needed
    rebalance_reason: str = ""              # Reason for rebalance

    def __post_init__(self):
        """Validate hedge portfolio"""
        if not self.pair_name:
            raise ValueError("Pair name cannot be empty")
        if not (0 <= self.long_weight <= 1):
            raise ValueError("long_weight must be between 0 and 1")
        if not (0 <= self.hedge_weight <= 1):
            raise ValueError("hedge_weight must be between 0 and 1")
        if not (-1 <= self.current_correlation <= 1):
            raise ValueError("current_correlation must be between -1 and 1")


@dataclass(frozen=True)
class HedgeAlert:
    """
    Hedge alert value object.

    Represents an alert or warning for a hedge position.
    """
    pair_name: str                          # Hedge pair name
    alert_date: date                        # Alert date
    alert_type: HedgeAlertType              # Type of alert

    # Alert details
    severity: str = "medium"                # low, medium, high, critical
    message: str = ""                       # Alert message
    current_value: float = 0.0              # Current value that triggered alert
    threshold_value: float = 0.0            # Threshold that was exceeded

    # Recommended action
    action_required: str = ""               # Action to take
    action_priority: int = 5                # Priority (1-10)

    # Status
    is_resolved: bool = False               # Whether alert has been resolved
    resolved_at: datetime | None = None  # When alert was resolved

    def __post_init__(self):
        """Validate hedge alert"""
        if not self.pair_name:
            raise ValueError("Pair name cannot be empty")
        if not self.message:
            raise ValueError("Alert message cannot be empty")
        if self.action_priority < 1 or self.action_priority > 10:
            raise ValueError("action_priority must be between 1 and 10")


@dataclass(frozen=True)
class HedgePerformance:
    """
    Hedge performance metrics value object.

    Tracks historical performance of hedge strategies.
    """
    pair_name: str                          # Hedge pair name
    period_start: date                      # Performance period start
    period_end: date                        # Performance period end

    # Return metrics
    total_return: float                     # Total return
    annual_return: float                    # Annualized return
    sharpe_ratio: float                     # Sharpe ratio

    # Hedge effectiveness
    volatility_reduction: float             # Volatility reduction (%)
    drawdown_reduction: float               # Max drawdown reduction (%)
    hedge_effectiveness: float              # Overall effectiveness (0-1)

    # Cost metrics
    hedge_cost: float                       # Total cost of hedging
    cost_benefit_ratio: float               # Benefit/cost ratio

    # Correlation metrics
    avg_correlation: float                  # Average correlation
    correlation_stability: float            # Correlation stability (0-1)

    def __post_init__(self):
        """Validate hedge performance"""
        if self.period_start > self.period_end:
            raise ValueError("period_start must be before period_end")


# Domain factory functions

def get_common_hedge_pairs() -> list[HedgePair]:
    """Get list of commonly used hedge pairs"""
    return [
        # Equity-Bond hedge
        HedgePair(
            name="股债对冲",
            long_asset="510300",           # 沪深300ETF
            hedge_asset="511260",          # 10年国债ETF
            hedge_method=HedgeMethod.BETA,
            target_long_weight=0.7,
            target_hedge_weight=0.3,
            min_correlation=-0.8,
            max_correlation=-0.2,
            correlation_window=60,
        ),

        # Growth-Value hedge
        HedgePair(
            name="成长价值对冲",
            long_asset="159915",           # 创业板ETF
            hedge_asset="512100",          # 红利ETF
            hedge_method=HedgeMethod.EQUAL_RISK,
            target_long_weight=0.6,
            target_hedge_weight=0.4,
            min_correlation=-0.7,
            max_correlation=-0.2,
            correlation_window=60,
        ),

        # Large-Small cap hedge
        HedgePair(
            name="大小盘对冲",
            long_asset="512100",           # 中证1000ETF (小盘)
            hedge_asset="510300",          # 沪深300ETF (大盘)
            hedge_method=HedgeMethod.MIN_VARIANCE,
            target_long_weight=0.5,
            target_hedge_weight=0.5,
            min_correlation=-0.9,
            max_correlation=-0.3,
            correlation_window=60,
        ),

        # Equity-Gold hedge (safe haven)
        HedgePair(
            name="股票黄金对冲",
            long_asset="510300",           # 沪深300ETF
            hedge_asset="159980",          # 黄金ETF
            hedge_method=HedgeMethod.DOLLAR_NEUTRAL,
            target_long_weight=0.8,
            target_hedge_weight=0.2,
            min_correlation=-0.5,
            max_correlation=0.3,
            correlation_window=60,
        ),

        # Equity-Commodity hedge
        HedgePair(
            name="股票商品对冲",
            long_asset="510300",           # 沪深300ETF
            hedge_asset="159985",          # 豆粕ETF
            hedge_method=HedgeMethod.FIXED_RATIO,
            target_long_weight=0.75,
            target_hedge_weight=0.25,
            min_correlation=-0.6,
            max_correlation=-0.1,
            correlation_window=60,
        ),

        # A-Share Gold hedge
        HedgePair(
            name="A股黄金对冲",
            long_asset="510500",           # 中证500ETF
            hedge_asset="159980",          # 黄金ETF
            hedge_method=HedgeMethod.BETA,
            target_long_weight=0.7,
            target_hedge_weight=0.3,
            beta_target=0.3,
            min_correlation=-0.5,
            max_correlation=0.2,
            correlation_window=60,
        ),

        # Sector hedge: Technology - Consumer Staples
        HedgePair(
            name="科技消费对冲",
            long_asset="515000",           # 科技ETF
            hedge_asset="512200",          # 消费ETF
            hedge_method=HedgeMethod.EQUAL_RISK,
            target_long_weight=0.6,
            target_hedge_weight=0.4,
            min_correlation=-0.8,
            max_correlation=-0.2,
            correlation_window=60,
        ),
    ]


def create_default_hedge_config() -> HedgePair:
    """Create a default hedge configuration"""
    return HedgePair(
        name="默认股债对冲",
        long_asset="510300",               # 沪深300ETF
        hedge_asset="511260",              # 10年国债ETF
        hedge_method=HedgeMethod.BETA,
        target_long_weight=0.7,
        target_hedge_weight=0.3,
        rebalance_trigger=0.05,
        correlation_window=60,
        min_correlation=-0.8,
        max_correlation=-0.2,
        correlation_alert_threshold=0.2,
    )
