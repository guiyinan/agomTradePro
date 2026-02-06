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
from typing import Dict, List, Optional, Tuple
from enum import Enum


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
    underlying_index: Optional[str] = None # Underlying index (e.g., "000300.SH")
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
    asset_universe: List[str] = field(default_factory=list)  # List of asset codes

    # Strategy parameters
    params: Dict = field(default_factory=dict)  # Strategy-specific parameters

    # Portfolio construction
    rebalance_frequency: str = "monthly"   # weekly, monthly, quarterly
    min_weight: float = 0.0                # Minimum weight per asset
    max_weight: float = 1.0                # Maximum weight per asset

    # Risk controls
    max_turnover: float = 1.0              # Maximum turnover rate
    lookback_period: int = 252             # Lookback period for calculations (days)

    # Regime-based settings (if strategy_type == REGIME_BASED)
    regime_allocations: Dict = field(default_factory=dict)  # {regime: {asset: weight}}

    # Momentum settings (if strategy_type == MOMENTUM)
    momentum_periods: List[int] = field(default_factory=lambda: [20, 60, 120, 252])
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
    target_allocation: Dict[str, float]    # {asset_code: target_weight}

    # Context information
    current_regime: str = ""               # Current macro regime (if applicable)
    momentum_ranking: List[Tuple[str, float]] = field(default_factory=list)  # [(asset, score)]

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
    current_allocation: Dict[str, float]   # {asset_code: current_weight}

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

def get_common_etf_assets() -> List[AssetClass]:
    """Get list of commonly traded ETF assets for rotation"""
    return [
        # Equity ETFs
        AssetClass(
            code="510300",
            name="沪深300ETF",
            category=AssetCategory.EQUITY,
            description="跟踪沪深300指数，代表A股核心资产",
            underlying_index="000300.SH",
        ),
        AssetClass(
            code="510500",
            name="中证500ETF",
            category=AssetCategory.EQUITY,
            description="跟踪中证500指数，代表中盘成长股",
            underlying_index="000905.SH",
        ),
        AssetClass(
            code="159915",
            name="创业板ETF",
            category=AssetCategory.EQUITY,
            description="跟踪创业板指数，代表新兴成长股",
            underlying_index="399006.SZ",
        ),
        AssetClass(
            code="512100",
            name="中证1000ETF",
            category=AssetCategory.EQUITY,
            description="跟踪中证1000指数，代表小盘股",
            underlying_index="000852.SH",
        ),
        AssetClass(
            code="588000",
            name="科创50ETF",
            category=AssetCategory.EQUITY,
            description="跟踪科创50指数，代表科技创新企业",
            underlying_index="000688.SH",
        ),

        # Bond ETFs
        AssetClass(
            code="511260",
            name="十年国债ETF",
            category=AssetCategory.BOND,
            description="跟踪10年期国债指数",
            underlying_index="净价10年国债",
        ),
        AssetClass(
            code="511010",
            name="国债ETF",
            category=AssetCategory.BOND,
            description="跟踪国债指数",
            underlying_index="上证国债",
        ),
        AssetClass(
            code="511270",
            name="十年地方债ETF",
            category=AssetCategory.BOND,
            description="跟踪10年期地方债指数",
        ),

        # Commodity ETFs
        AssetClass(
            code="159985",
            name="豆粕ETF",
            category=AssetCategory.COMMODITY,
            description="跟踪大商所豆粕期货价格",
        ),
        AssetClass(
            code="159980",
            name="黄金ETF",
            category=AssetCategory.COMMODITY,
            description="跟踪上海黄金现货价格",
        ),
        AssetClass(
            code="515180",
            name="新能源ETF",
            category=AssetCategory.EQUITY,
            description="跟踪中证新能源指数",
        ),

        # Currency/Money Market
        AssetClass(
            code="511880",
            name="银华日利",
            category=AssetCategory.CURRENCY,
            description="货币市场基金，短期现金管理工具",
        ),
        AssetClass(
            code="511990",
            name="华宝添益",
            category=AssetCategory.CURRENCY,
            description="货币市场基金，短期现金管理工具",
        ),
    ]


def create_default_regime_allocation() -> Dict[str, Dict[str, float]]:
    """
    Create default regime-based allocation matrix.

    Returns:
        {regime: {asset_code: weight}}
    """
    return {
        "Recovery": {  # 复苏期
            "510300": 0.30,  # 沪深300 - 大盘蓝筹
            "510500": 0.20,  # 中证500 - 中盘成长
            "159985": 0.15,  # 豆粕 - 商品
            "511260": 0.20,  # 10年国债 - 债券
            "511880": 0.15,  # 货币 - 现金
        },
        "Overheat": {  # 过热期
            "510300": 0.20,
            "159985": 0.25,  # 增加商品
            "159980": 0.15,  # 黄金
            "511260": 0.25,  # 增加债券
            "511880": 0.15,  # 现金
        },
        "Stagflation": {  # 滞胀期
            "159985": 0.20,  # 商品
            "159980": 0.20,  # 黄金
            "511260": 0.35,  # 大幅增加债券
            "511880": 0.25,  # 大幅增加现金
            "510300": 0.0,   # 清空股票
            "510500": 0.0,
        },
        "Deflation": {  # 通缩期
            "511260": 0.50,  # 大幅增加债券
            "511880": 0.30,  # 现金
            "159980": 0.10,  # 少量黄金
            "510300": 0.10,  # 少量高质量股票
        },
    }


def create_default_momentum_config() -> RotationConfig:
    """Create default momentum-based rotation configuration"""
    assets = get_common_etf_assets()
    asset_codes = [a.code for a in assets[:10]]  # Top 10 assets

    return RotationConfig(
        name="动量轮动策略",
        description="基于价格动量的资产轮动策略，选择近期表现最好的资产",
        strategy_type=RotationStrategyType.MOMENTUM,
        asset_universe=asset_codes,
        params={
            "momentum_periods": [20, 60, 120],
            "weight_method": "equal_weight",
        },
        rebalance_frequency="monthly",
        min_weight=0.0,
        max_weight=1.0,
        lookback_period=120,
        top_n=3,
    )


def create_default_regime_config() -> RotationConfig:
    """Create default regime-based rotation configuration"""
    assets = get_common_etf_assets()
    asset_codes = [a.code for a in assets]

    return RotationConfig(
        name="宏观象限轮动策略",
        description="根据宏观象限进行资产配置，复苏期配股票，滞胀期配债券和黄金",
        strategy_type=RotationStrategyType.REGIME_BASED,
        asset_universe=asset_codes,
        regime_allocations=create_default_regime_allocation(),
        rebalance_frequency="monthly",
        min_weight=0.0,
        max_weight=0.5,
        lookback_period=60,
    )
