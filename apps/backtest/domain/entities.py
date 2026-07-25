"""
Domain Entities for Backtesting Module.

纯数据实体，使用 dataclass(frozen=True) 确保不可变性。
只使用 Python 标准库。
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import TypedDict


class RegimeHistoryEntry(TypedDict):
    """One regime observation captured during a backtest."""

    date: str
    regime: str
    confidence: float
    portfolio_value: float


class RebalanceFrequency(Enum):
    """再平衡频率"""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class AssetClass(Enum):
    """资产类别"""

    A_SHARE_GROWTH = "a_share_growth"
    A_SHARE_VALUE = "a_share_value"
    CHINA_BOND = "china_bond"
    GOLD = "gold"
    COMMODITY = "commodity"
    CASH = "cash"


class BacktestStatus(Enum):
    """回测状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class BacktestConfig:
    """回测配置（值对象）"""

    start_date: date
    end_date: date
    initial_capital: float
    rebalance_frequency: str  # "monthly", "quarterly", "yearly"
    use_pit_data: bool  # 是否使用 Point-in-Time 数据
    transaction_cost_bps: float = 10  # 交易成本（基点）
    trust_status: str = "exploratory"
    data_manifest_id: str | None = None
    pit_coverage: dict[str, float] = field(default_factory=dict)
    config_hash: str = ""
    code_commit: str = ""
    engine_version: str = "backtest-v1"
    research_trial_id: str | None = None
    decision_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        """验证配置"""
        if (
            isinstance(self.initial_capital, bool)
            or not math.isfinite(self.initial_capital)
            or self.initial_capital <= 0
        ):
            raise ValueError("initial_capital must be positive and finite")
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        if (
            isinstance(self.transaction_cost_bps, bool)
            or not math.isfinite(self.transaction_cost_bps)
            or self.transaction_cost_bps < 0
        ):
            raise ValueError("transaction_cost_bps must be non-negative and finite")
        valid_frequencies = ["monthly", "quarterly", "yearly"]
        if self.rebalance_frequency not in valid_frequencies:
            raise ValueError(f"rebalance_frequency must be one of {valid_frequencies}")
        valid_trust_statuses = {"legacy_unverified", "exploratory", "pit_verified"}
        if self.trust_status not in valid_trust_statuses:
            raise ValueError(f"trust_status must be one of {sorted(valid_trust_statuses)}")
        if self.trust_status == "pit_verified":
            if not self.use_pit_data:
                raise ValueError("pit_verified backtests must enable PIT data")
            if not self.data_manifest_id:
                raise ValueError("pit_verified backtests require data_manifest_id")
            if not self.config_hash or not self.code_commit or not self.engine_version:
                raise ValueError("pit_verified backtests require config, code and engine versions")
            if not self.research_trial_id:
                raise ValueError("pit_verified backtests require research_trial_id")
            if not self.decision_snapshot_id:
                raise ValueError("pit_verified backtests require decision_snapshot_id")


@dataclass(frozen=True)
class Trade:
    """交易记录（值对象）"""

    trade_date: date
    asset_class: str
    action: str  # "buy" or "sell"
    shares: float
    price: float
    notional: float
    cost: float


@dataclass
class PortfolioState:
    """组合状态（实体）"""

    as_of_date: date
    cash: float
    positions: dict[str, float]  # asset_class -> shares
    total_value: float

    def get_position_value(self, asset_class: str, price: float) -> float:
        """获取指定资产市值"""
        shares = self.positions.get(asset_class, 0)
        return shares * price

    def to_dict(self) -> dict[str, object]:
        """转换为字典"""
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "cash": self.cash,
            "positions": self.positions.copy(),
            "total_value": self.total_value,
        }


@dataclass
class BacktestResult:
    """回测结果（实体）"""

    config: BacktestConfig
    final_value: float
    total_return: float
    annualized_return: float
    sharpe_ratio: float | None
    max_drawdown: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    regime_history: list[RegimeHistoryEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_summary_dict(self) -> dict[str, object]:
        """转换为摘要字典"""
        return {
            "start_date": self.config.start_date.isoformat(),
            "end_date": self.config.end_date.isoformat(),
            "initial_capital": self.config.initial_capital,
            "final_value": self.final_value,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "num_trades": len(self.trades),
            "rebalance_frequency": self.config.rebalance_frequency,
        }

    def get_win_rate(self) -> float | None:
        """计算胜率"""
        if not self.trades:
            return None

        # 简化计算：盈利交易数 / 总交易数
        # 这里需要更复杂的逻辑来匹配买卖对
        # 暂时返回 None
        return None


@dataclass
class RebalanceResult:
    """再平衡结果（值对象）"""

    date: date
    regime: str
    regime_confidence: float
    old_weights: dict[str, float]
    new_weights: dict[str, float]
    trades: list[Trade]
    portfolio_value: float

    def to_dict(self) -> dict[str, object]:
        """转换为字典"""
        return {
            "date": self.date.isoformat(),
            "regime": self.regime,
            "regime_confidence": self.regime_confidence,
            "old_weights": self.old_weights.copy(),
            "new_weights": self.new_weights.copy(),
            "num_trades": len(self.trades),
            "portfolio_value": self.portfolio_value,
        }


@dataclass
class AttributionEntry:
    """归因分析条目"""

    date: date
    regime: str
    return_contribution: float  # 该期间收益贡献
    regime_return: float  # 该 Regime 下的平均收益
    benchmark_return: float  # 基准收益
    active_return: float  # 超额收益 = regime_return - benchmark_return


@dataclass
class AttributionReport:
    """归因分析报告"""

    backtest_config: BacktestConfig
    total_return: float
    benchmark_return: float
    active_return: float  # 超额收益
    regime_attribution: dict[str, dict[str, float]]  # 各 Regime 下的归因
    entries: list[AttributionEntry]

    def to_dict(self) -> dict[str, object]:
        """转换为字典"""
        return {
            "total_return": self.total_return,
            "benchmark_return": self.benchmark_return,
            "active_return": self.active_return,
            "regime_attribution": self.regime_attribution.copy(),
            "num_entries": len(self.entries),
        }


@dataclass
class PITDataConfig:
    """Point-in-Time 数据配置"""

    publication_lags: dict[str, timedelta] = field(default_factory=dict)

    def add_lag(self, indicator_code: str, lag_days: int) -> None:
        """添加指标的发布延迟"""
        self.publication_lags[indicator_code] = timedelta(days=lag_days)

    def get_lag(self, indicator_code: str) -> timedelta:
        """获取指标的发布延迟"""
        return self.publication_lags.get(indicator_code, timedelta(days=0))


@dataclass(frozen=True)
class DataVersion:
    """
    数据版本实体（用于追踪数据修订）

    虽然当前系统未实现完整的数据修订追踪，
    但此实体为未来扩展预留了接口。

    Attributes:
        indicator_code: 指标代码
        observed_at: 数据观测期（报告期）
        value: 数据值
        version: 版本号（1=初值，2=第一次修订，...）
        published_at: 该版本的发布日期
        is_final: 是否为最终值（不再修订）
        revision_note: 修订说明（可选）

    使用场景:
        1. GDP 数据：初值 -> 第一次修订 -> 第二次修订 -> 最终值
        2. PMI 数据：初值可能在大样本调查后修订
        3. 就业数据：初值和修正值常有差异

    示例:
        DataVersion("GDP", date(2024,1,1), 5.2, 1, date(2024,3,1), False, "初值")
        DataVersion("GDP", date(2024,1,1), 5.3, 2, date(2024,4,1), False, "修订值")
        DataVersion("GDP", date(2024,1,1), 5.3, 3, date(2024,5,1), True, "最终值")
    """

    indicator_code: str
    observed_at: date
    value: float
    version: int
    published_at: date
    is_final: bool = False
    revision_note: str = ""

    @property
    def version_type(self) -> str:
        """返回版本类型描述"""
        if self.version == 1:
            return "初值"
        elif self.is_final:
            return "最终值"
        else:
            return f"修订值{self.version - 1}"

    def is_available_on(self, query_date: date) -> bool:
        """检查该版本在指定日期是否已发布"""
        return self.published_at <= query_date


@dataclass(frozen=True)
class DataVersionHistory:
    """
    数据版本历史（包含所有版本）

    用于回测时获取"as-of"某个日期可用的数据版本。

    Attributes:
        indicator_code: 指标代码
        observed_at: 数据观测期
        versions: 该数据的所有版本，按发布时间排序

    方法:
        get_version_on(date): 获取指定日期可用的最新版本
    """

    indicator_code: str
    observed_at: date
    versions: tuple[DataVersion, ...]  # 按版本号排序

    def get_version_on(self, query_date: date) -> DataVersion | None:
        """
        获取在指定日期可用的最新版本

        Args:
            query_date: 查询日期（回测当前日期）

        Returns:
            Optional[DataVersion]: 可用的最新版本，如果没有则返回 None

        示例:
            回测日期为2024-03-15，GDP版本历史为：
            - v1: 初值，2024-03-01发布
            - v2: 修订值，2024-04-01发布
            返回 v1（初值）
        """
        for version in reversed(self.versions):  # 从最新版本开始查找
            if version.published_at <= query_date:
                return version
        return None

    def get_final_value(self) -> DataVersion | None:
        """获取最终值版本"""
        for version in reversed(self.versions):
            if version.is_final:
                return version
        return None
