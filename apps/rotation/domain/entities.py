"""
Rotation Module Domain Layer - Entities

Asset rotation system entities for cross-asset allocation.
Follows four-layer architecture: Domain layer has NO external dependencies.

Uses only:
- Python standard library (dataclasses, typing, enum, datetime)
- Pure business logic
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple


class AssetCategory(Enum):
    """Asset categories for rotation"""
    EQUITY = "equity"           # 股票类
    BOND = "bond"               # 债券类
    COMMODITY = "commodity"     # 商品类
    CURRENCY = "currency"       # 货币类
    ALTERNATIVE = "alternative" # 另类投资


class RotationStrategyType(Enum):
    """Rotation strategy types"""
    REGIME_BASED = "regime_based"       # Based on macro regime
    MOMENTUM = "momentum"               # Based on price momentum
    RISK_PARITY = "risk_parity"         # Risk parity allocation
    MEAN_REVERSION = "mean_reversion"   # Mean reversion
    CUSTOM = "custom"                   # Custom strategy


@dataclass(frozen=True)
class AssetClass:
    """
    Asset class entity.

    Defines a tradeable asset class for rotation.
    Immutable value object (frozen=True).
    """
    code: str                              # Asset code (e.g., "510300" for ETF)
    name: str                              # Asset name
    category: AssetCategory                # Asset category
    description: str                       # Asset description
    underlying_index: str | None = None # Underlying index (e.g., "000300.SH")
    currency: str = "CNY"                  # Currency denomination
    is_active: bool = True                 # Whether this asset is available

    def __post_init__(self):
        """Validate asset class"""
        if not self.code:
            raise ValueError("Asset code cannot be empty")
        if not self.name:
            raise ValueError("Asset name cannot be empty")


@dataclass(frozen=True)
class MomentumScore:
    """
    Momentum score value object.

    Represents momentum metrics for an asset.
    """
    asset_code: str                        # Asset code
    calc_date: date                        # Calculation date

    # Momentum periods (returns)
    momentum_1m: float = 0.0               # 1-month momentum
    momentum_3m: float = 0.0               # 3-month momentum
    momentum_6m: float = 0.0               # 6-month momentum
    momentum_12m: float = 0.0              # 12-month momentum

    # Composite score
    composite_score: float = 0.0           # Composite momentum score
    rank: int = 0                          # Rank among universe

    # Volatility-adjusted metrics
    sharpe_1m: float = 0.0                 # 1-month Sharpe ratio
    sharpe_3m: float = 0.0                 # 3-month Sharpe ratio

    # Trend indicators
    ma_signal: str = "neutral"             # Moving average signal
    trend_strength: float = 0.0            # Trend strength (0-1)

    def __post_init__(self):
        """Validate momentum score"""
        if not self.asset_code:
            raise ValueError("Asset code cannot be empty")


@dataclass(frozen=True)
class RotationConfig:
    """
    Rotation configuration entity.

    Defines how to construct a rotation strategy.
    """
    name: str                              # Configuration name
    description: str = ""                  # Configuration description
    strategy_type: RotationStrategyType = RotationStrategyType.MOMENTUM

    # Asset universe
    asset_universe: list[str] = field(default_factory=list)  # List of asset codes

    # Strategy parameters
    params: dict = field(default_factory=dict)  # Strategy-specific parameters

    # Portfolio construction
    rebalance_frequency: str = "monthly"   # weekly, monthly, quarterly
    min_weight: float = 0.0                # Minimum weight per asset
    max_weight: float = 1.0                # Maximum weight per asset

    # Risk controls
    max_turnover: float = 1.0              # Maximum turnover rate
    lookback_period: int = 252             # Lookback period for calculations (days)

    # Regime-based settings (if strategy_type == REGIME_BASED)
    regime_allocations: dict = field(default_factory=dict)  # {regime: {asset: weight}}

    # Momentum settings (if strategy_type == MOMENTUM)
    momentum_periods: list[int] = field(default_factory=lambda: [20, 60, 120, 252])
    top_n: int = 3                         # Number of top assets to select

    # Status
    is_active: bool = True                 # Whether this config is active

    def __post_init__(self):
        """Validate rotation configuration"""
        if not self.name:
            raise ValueError("Configuration name cannot be empty")
        if self.max_weight <= 0 or self.max_weight > 1:
            raise ValueError("max_weight must be between 0 and 1")
        if self.min_weight < 0:
            raise ValueError("min_weight must be non-negative")
        if self.min_weight >= self.max_weight:
            raise ValueError("min_weight must be less than max_weight")
        if self.top_n < 1:
            raise ValueError("top_n must be at least 1")
        if not self.asset_universe:
            raise ValueError("asset_universe cannot be empty")


@dataclass(frozen=True)
class RotationSignal:
    """
    Rotation signal value object.

    Represents a rotation signal generated by a strategy.
    """
    config_name: str                       # Configuration name
    signal_date: date                      # Signal date

    # Allocation recommendations
    target_allocation: dict[str, float]    # {asset_code: target_weight}

    # Context information
    current_regime: str = ""               # Current macro regime (if applicable)
    momentum_ranking: list[tuple[str, float]] = field(default_factory=list)  # [(asset, score)]

    # Risk metrics
    expected_volatility: float = 0.0       # Expected portfolio volatility
    expected_return: float = 0.0           # Expected portfolio return

    # Signals
    action_required: str = "hold"          # rebalance, hold, reduce_risk
    reason: str = ""                       # Explanation of the signal

    def __post_init__(self):
        """Validate rotation signal"""
        if not self.config_name:
            raise ValueError("Config name cannot be empty")

        # Validate weights sum to 1 (or close to it)
        total_weight = sum(self.target_allocation.values())
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Target allocation weights must sum to 1.0, got {total_weight}")


@dataclass(frozen=True)
class RotationPortfolio:
    """
    Rotation portfolio value object.

    Represents the current state of a rotation portfolio.
    """
    config_name: str                       # Configuration name
    trade_date: date                       # Trade date

    # Current holdings
    current_allocation: dict[str, float]   # {asset_code: current_weight}

    # Performance
    daily_return: float = 0.0              # Daily return
    cumulative_return: float = 0.0         # Cumulative return since inception

    # Risk metrics
    portfolio_volatility: float = 0.0      # Portfolio volatility
    max_drawdown: float = 0.0              # Maximum drawdown

    # Turnover
    turnover_since_last: float = 0.0       # Turnover since last rebalance

    def __post_init__(self):
        """Validate rotation portfolio"""
        if not self.config_name:
            raise ValueError("Config name cannot be empty")

        # Validate weights sum to 1 (or close to it)
        total_weight = sum(self.current_allocation.values())
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Current allocation weights must sum to 1.0, got {total_weight}")


# Domain factory functions

def get_common_etf_assets() -> list[AssetClass]:
    """Rotation 资产应从数据库读取，Domain 层不再内置默认资产。"""
    return []


def create_default_regime_allocation() -> dict[str, dict[str, float]]:
    """
    Create default regime-based allocation matrix.

    Returns:
        {regime: {asset_code: weight}}
    """
    return {}


def create_default_momentum_config() -> RotationConfig:
    """Create default momentum-based rotation configuration"""
    raise ValueError("默认轮动配置已移除，请从数据库中的 RotationConfigModel 读取配置")


def create_default_regime_config() -> RotationConfig:
    """Create default regime-based rotation configuration"""
    raise ValueError("默认轮动配置已移除，请从数据库中的 RotationConfigModel 读取配置")
