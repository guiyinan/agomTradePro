"""
Factor Module Domain Layer - Entities

Multi-factor stock selection system entities.
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


class FactorCategory(Enum):
    """Factor categories for stock selection"""
    VALUE = "value"           # 价值因子 (PE, PB, PS, etc.)
    QUALITY = "quality"       # 质量因子 (ROE, ROA, debt ratio, etc.)
    GROWTH = "growth"         # 成长因子 (revenue growth, profit growth, etc.)
    MOMENTUM = "momentum"     # 动量因子 (price momentum, volume momentum, etc.)
    VOLATILITY = "volatility" # 波动因子 (standard deviation, beta, etc.)
    LIQUIDITY = "liquidity"   # 流动性因子 (turnover, trading volume, etc.)
    TECHNICAL = "technical"   # 技术因子 (RSI, MACD, etc.)


class FactorDirection(Enum):
    """Factor direction (how the factor affects stock selection)"""
    POSITIVE = "positive"     # Higher value is better (e.g., ROE)
    NEGATIVE = "negative"     # Lower value is better (e.g., PE)
    NEUTRAL = "neutral"       # Direction doesn't matter (e.g., for ranking only)


@dataclass(frozen=True)
class FactorDefinition:
    """
    Factor definition entity.

    Defines a single factor used in multi-factor stock selection.
    Immutable value object (frozen=True).
    """
    code: str                              # Factor code, e.g., "pe_ttm", "roe"
    name: str                              # Factor display name
    category: FactorCategory               # Factor category
    description: str                       # Factor description
    data_source: str                       # Data source (tushare, akshare, etc.)
    data_field: str                        # Field name in data source
    direction: FactorDirection = FactorDirection.POSITIVE  # Positive or negative
    update_frequency: str = "daily"        # daily, weekly, monthly
    is_active: bool = True                 # Whether this factor is active

    # Data quality requirements
    min_data_points: int = 20              # Minimum data points for calculation
    allow_missing: bool = False            # Whether to allow missing values

    # Factor characteristics
    higher_better: Optional[bool] = None   # Deprecated: use direction instead

    def __post_init__(self):
        """Validate factor definition"""
        if not self.code:
            raise ValueError("Factor code cannot be empty")
        if not self.name:
            raise ValueError("Factor name cannot be empty")
        if not self.data_source:
            raise ValueError("Data source cannot be empty")
        if self.min_data_points < 1:
            raise ValueError("min_data_points must be at least 1")

        # Handle legacy higher_better for backward compatibility
        if self.higher_better is not None:
            if self.direction == FactorDirection.NEUTRAL:
                direction = FactorDirection.POSITIVE if self.higher_better else FactorDirection.NEGATIVE
                object.__setattr__(self, 'direction', direction)


@dataclass(frozen=True)
class FactorExposure:
    """
    Factor exposure value object.

    Represents a single stock's exposure to a single factor on a specific date.
    """
    stock_code: str                        # Stock code
    trade_date: date                       # Trade date
    factor_code: str                       # Factor code
    factor_value: float                    # Raw factor value
    percentile_rank: float                 # Percentile rank (0-1) in universe
    z_score: float                         # Standardized score (mean=0, std=1)
    normalized_score: float = 0.0          # Normalized score (0-100)

    def __post_init__(self):
        """Validate factor exposure"""
        if not self.stock_code:
            raise ValueError("Stock code cannot be empty")
        if not self.factor_code:
            raise ValueError("Factor code cannot be empty")
        if not (0 <= self.percentile_rank <= 1):
            raise ValueError("percentile_rank must be between 0 and 1")
        if not (0 <= self.normalized_score <= 100):
            raise ValueError("normalized_score must be between 0 and 100")


@dataclass(frozen=True)
class FactorScore:
    """
    Factor score value object.

    Represents a stock's composite score across multiple factors.
    """
    stock_code: str                        # Stock code
    stock_name: str                        # Stock name
    trade_date: date                       # Trade date

    # Factor breakdown
    factor_scores: Dict[str, float]        # Individual factor scores
    factor_weights: Dict[str, float]       # Factor weights used

    # Composite scores
    composite_score: float                 # Weighted composite score
    percentile_rank: float                 # Rank in universe (0-1)

    # Additional info
    sector: str = ""                       # Sector classification
    market_cap: Optional[Decimal] = None   # Market cap in yuan

    # Scores by category
    value_score: float = 0.0
    quality_score: float = 0.0
    growth_score: float = 0.0
    momentum_score: float = 0.0
    volatility_score: float = 0.0
    liquidity_score: float = 0.0

    def __post_init__(self):
        """Validate factor score"""
        if not self.stock_code:
            raise ValueError("Stock code cannot be empty")
        if not self.stock_name:
            raise ValueError("Stock name cannot be empty")
        if not (0 <= self.percentile_rank <= 1):
            raise ValueError("percentile_rank must be between 0 and 1")

        # Validate weights sum to 1
        total_weight = sum(self.factor_weights.values())
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Factor weights must sum to 1.0, got {total_weight}")


@dataclass(frozen=True)
class FactorPortfolioConfig:
    """
    Factor portfolio configuration entity.

    Defines how to construct a portfolio using multi-factor selection.
    """
    name: str                              # Configuration name
    description: str = ""                  # Configuration description

    # Factor weights
    factor_weights: Dict[str, float] = field(default_factory=dict)  # {factor_code: weight}

    # Universe settings
    universe: str = "all_a"                # Stock universe: all_a, hs300, zz500, sz50
    min_market_cap: Optional[float] = None # Minimum market cap (in billion yuan)
    max_market_cap: Optional[float] = None # Maximum market cap (in billion yuan)

    # Filtering conditions
    max_pe: Optional[float] = None         # Maximum PE ratio
    min_pe: Optional[float] = None         # Minimum PE ratio
    max_pb: Optional[float] = None         # Maximum PB ratio
    max_debt_ratio: Optional[float] = None # Maximum debt ratio (%)

    # Portfolio construction
    top_n: int = 30                        # Number of stocks to select
    rebalance_frequency: str = "monthly"   # weekly, monthly, quarterly
    weight_method: str = "equal_weight"    # equal_weight, factor_weighted, market_cap_weighted

    # Risk controls
    max_sector_weight: float = 0.4         # Maximum weight per sector
    max_single_stock_weight: float = 0.05  # Maximum weight per stock

    # Status
    is_active: bool = True                 # Whether this config is active

    def __post_init__(self):
        """Validate portfolio configuration"""
        if not self.name:
            raise ValueError("Configuration name cannot be empty")
        if self.top_n < 1:
            raise ValueError("top_n must be at least 1")
        if self.max_sector_weight <= 0 or self.max_sector_weight > 1:
            raise ValueError("max_sector_weight must be between 0 and 1")
        if self.max_single_stock_weight <= 0 or self.max_single_stock_weight > 1:
            raise ValueError("max_single_stock_weight must be between 0 and 1")

        # Validate factor weights
        if self.factor_weights:
            total_weight = sum(abs(weight) for weight in self.factor_weights.values())
            if abs(total_weight - 1.0) > 0.01:
                raise ValueError(
                    f"Absolute factor weights must sum to 1.0, got {total_weight}"
                )

    def get_effective_universe(self) -> str:
        """Get the effective universe code"""
        return self.universe


@dataclass(frozen=True)
class FactorPortfolioHolding:
    """
    Factor portfolio holding value object.

    Represents a single stock holding in a factor portfolio on a specific date.
    """
    config_name: str                       # Configuration name
    trade_date: date                       # Trade date
    stock_code: str                        # Stock code
    stock_name: str                        # Stock name
    weight: float                          # Portfolio weight (0-1)
    factor_score: float                    # Composite factor score
    rank: int                              # Rank in selection
    sector: str = ""                       # Sector classification

    # Factor breakdown
    factor_scores: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        """Validate holding"""
        if not self.stock_code:
            raise ValueError("Stock code cannot be empty")
        if not (0 <= self.weight <= 1):
            raise ValueError("Weight must be between 0 and 1")
        if self.rank < 1:
            raise ValueError("Rank must be at least 1")


@dataclass(frozen=True)
class FactorPerformance:
    """
    Factor performance metrics value object.

    Tracks historical performance of factor-based strategies.
    """
    factor_code: str                       # Factor code
    period_start: date                     # Performance period start
    period_end: date                       # Performance period end

    # Return metrics
    total_return: float                    # Total return
    annual_return: float                   # Annualized return
    sharpe_ratio: float                    # Sharpe ratio
    max_drawdown: float                    # Maximum drawdown

    # Selection metrics
    win_rate: float                        # Win rate of selected stocks
    avg_rank: float                        # Average rank of factor in cross-section

    # Turnover
    turnover_rate: float = 0.0             # Portfolio turnover rate

    def __post_init__(self):
        """Validate performance metrics"""
        if self.period_start > self.period_end:
            raise ValueError("period_start must be before period_end")


# Domain factory functions

def create_default_factor_config() -> FactorPortfolioConfig:
    """Create a default factor portfolio configuration"""
    return FactorPortfolioConfig(
        name="默认价值成长组合",
        description="平衡价值和成长因子的默认配置",
        factor_weights={
            "pe_ttm": 0.15,
            "pb": 0.10,
            "roe": 0.25,
            "revenue_growth": 0.20,
            "profit_growth": 0.15,
            "momentum_3m": 0.15,
        },
        universe="zz500",
        top_n=30,
        rebalance_frequency="monthly",
        weight_method="equal_weight",
    )


def get_common_factors() -> List[FactorDefinition]:
    """Get list of commonly used factor definitions"""
    return [
        # Value factors
        FactorDefinition(
            code="pe_ttm",
            name="PE(TTM)",
            category=FactorCategory.VALUE,
            description="滚动市盈率",
            data_source="tushare",
            data_field="pe_ttm",
            direction=FactorDirection.NEGATIVE,
        ),
        FactorDefinition(
            code="pb",
            name="市净率",
            category=FactorCategory.VALUE,
            description="市净率",
            data_source="tushare",
            data_field="pb",
            direction=FactorDirection.NEGATIVE,
        ),
        FactorDefinition(
            code="ps",
            name="市销率",
            category=FactorCategory.VALUE,
            description="市销率",
            data_source="tushare",
            data_field="ps",
            direction=FactorDirection.NEGATIVE,
        ),
        FactorDefinition(
            code="dividend_yield",
            name="股息率",
            category=FactorCategory.VALUE,
            description="股息率",
            data_source="tushare",
            data_field="dv_ratio",
            direction=FactorDirection.POSITIVE,
        ),

        # Quality factors
        FactorDefinition(
            code="roe",
            name="净资产收益率",
            category=FactorCategory.QUALITY,
            description="净资产收益率(ROE)",
            data_source="tushare",
            data_field="roe",
            direction=FactorDirection.POSITIVE,
        ),
        FactorDefinition(
            code="roa",
            name="总资产收益率",
            category=FactorCategory.QUALITY,
            description="总资产收益率(ROA)",
            data_source="tushare",
            data_field="roa",
            direction=FactorDirection.POSITIVE,
        ),
        FactorDefinition(
            code="debt_ratio",
            name="资产负债率",
            category=FactorCategory.QUALITY,
            description="资产负债率",
            data_source="tushare",
            data_field="debt_to_assets",
            direction=FactorDirection.NEGATIVE,
        ),
        FactorDefinition(
            code="current_ratio",
            name="流动比率",
            category=FactorCategory.QUALITY,
            description="流动比率",
            data_source="tushare",
            data_field="current_ratio",
            direction=FactorDirection.POSITIVE,
        ),

        # Growth factors
        FactorDefinition(
            code="revenue_growth",
            name="营收增长率",
            category=FactorCategory.GROWTH,
            description="营业收入同比增长率",
            data_source="tushare",
            data_field="or_yoy",
            direction=FactorDirection.POSITIVE,
        ),
        FactorDefinition(
            code="profit_growth",
            name="利润增长率",
            category=FactorCategory.GROWTH,
            description="净利润同比增长率",
            data_source="tushare",
            data_field="netprofit_yoy",
            direction=FactorDirection.POSITIVE,
        ),

        # Momentum factors
        FactorDefinition(
            code="momentum_1m",
            name="1月动量",
            category=FactorCategory.MOMENTUM,
            description="过去1个月价格动量",
            data_source="calculated",
            data_field="momentum_20d",
            direction=FactorDirection.POSITIVE,
        ),
        FactorDefinition(
            code="momentum_3m",
            name="3月动量",
            category=FactorCategory.MOMENTUM,
            description="过去3个月价格动量",
            data_source="calculated",
            data_field="momentum_60d",
            direction=FactorDirection.POSITIVE,
        ),
        FactorDefinition(
            code="momentum_6m",
            name="6月动量",
            category=FactorCategory.MOMENTUM,
            description="过去6个月价格动量",
            data_source="calculated",
            data_field="momentum_120d",
            direction=FactorDirection.POSITIVE,
        ),

        # Volatility factors
        FactorDefinition(
            code="volatility_20d",
            name="20日波动率",
            category=FactorCategory.VOLATILITY,
            description="过去20日收益率标准差",
            data_source="calculated",
            data_field="volatility_20d",
            direction=FactorDirection.NEGATIVE,
        ),
        FactorDefinition(
            code="beta",
            name="Beta",
            category=FactorCategory.VOLATILITY,
            description="相对于沪深300的Beta",
            data_source="calculated",
            data_field="beta",
            direction=FactorDirection.NEGATIVE,
        ),

        # Liquidity factors
        FactorDefinition(
            code="turnover_20d",
            name="20日换手率",
            category=FactorCategory.LIQUIDITY,
            description="过去20日平均换手率",
            data_source="calculated",
            data_field="avg_turnover_20d",
            direction=FactorDirection.POSITIVE,
        ),
        FactorDefinition(
            code="amplitude_20d",
            name="20日振幅",
            category=FactorCategory.LIQUIDITY,
            description="过去20日平均振幅",
            data_source="calculated",
            data_field="avg_amplitude_20d",
            direction=FactorDirection.NEGATIVE,
        ),
    ]
