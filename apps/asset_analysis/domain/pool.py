"""
资产池管理模块 - Domain 层

定义资产池相关的实体和值对象。
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class PoolType(Enum):
    """资产池类型"""
    INVESTABLE = "investable"    # 可投池 - 符合准入条件
    PROHIBITED = "prohibited"    # 禁投池 - 不符合条件
    WATCH = "watch"             # 观察池 - 边界状态，需持续观察
    CANDIDATE = "candidate"      # 候选池 - 潜在投资标的


class PoolCategory(Enum):
    """资产分类"""
    EQUITY = "equity"           # 股票
    FUND = "fund"               # 基金
    BOND = "bond"               # 债券
    WEALTH = "wealth"           # 理财
    COMMODITY = "commodity"     # 商品
    INDEX = "index"             # 指数


class EntryReason(Enum):
    """入池原因"""
    HIGH_SCORE = "high_score"           # 高评分
    REGIME_MATCH = "regime_match"       # 匹配当前Regime
    POLICY_FAVORABLE = "policy_favorable"  # 政策友好
    SENTIMENT_POSITIVE = "sentiment_positive"  # 情绪正面
    SIGNAL_TRIGGERED = "signal_triggered"  # 信号触发
    MANUAL_ADD = "manual_add"          # 手动添加


class ExitReason(Enum):
    """出池原因"""
    LOW_SCORE = "low_score"           # 低评分
    REGIME_MISMATCH = "regime_mismatch"  # 不匹配当前Regime
    POLICY_UNFAVORABLE = "policy_unfavorable"  # 政策不友好
    SENTIMENT_NEGATIVE = "sentiment_negative"  # 情绪负面
    SIGNAL_INVALIDATED = "signal_invalidated"  # 信号失效
    RISK_CONTROL = "risk_control"      # 风险控制
    MANUAL_REMOVE = "manual_remove"    # 手动移除
    SCORE_DECLINE = "score_decline"    # 评分下降


@dataclass(frozen=True)
class PoolEntry:
    """资产池条目"""
    asset_type: PoolCategory
    asset_code: str
    asset_name: str
    pool_type: PoolType

    # 评分信息
    total_score: float = 0.0
    regime_score: float = 0.0
    policy_score: float = 0.0
    sentiment_score: float = 0.0
    signal_score: float = 0.0

    # 入池/出池信息
    entry_date: date = field(default_factory=date.today)
    entry_reason: EntryReason | None = None
    exit_date: date | None = None
    exit_reason: ExitReason | None = None
    is_active: bool = True

    # 风险指标
    risk_level: str = "未知"
    volatility: float | None = None
    max_drawdown: float | None = None

    # 额外属性
    sector: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None

    # 元数据
    context: dict[str, Any] | None = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "asset_type": self.asset_type.value,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "pool_type": self.pool_type.value,
            "scores": {
                "total": self.total_score,
                "regime": self.regime_score,
                "policy": self.policy_score,
                "sentiment": self.sentiment_score,
                "signal": self.signal_score,
            },
            "entry_date": self.entry_date.isoformat(),
            "entry_reason": self.entry_reason.value if self.entry_reason else None,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "exit_reason": self.exit_reason.value if self.exit_reason else None,
            "is_active": self.is_active,
            "risk_level": self.risk_level,
            "volatility": self.volatility,
            "max_drawdown": self.max_drawdown,
            "sector": self.sector,
            "market_cap": self.market_cap,
            "pe_ratio": self.pe_ratio,
            "pb_ratio": self.pb_ratio,
        }


@dataclass
class PoolStatistics:
    """资产池统计信息"""
    pool_type: PoolType
    asset_category: PoolCategory
    total_count: int = 0
    avg_score: float = 0.0
    avg_regime_score: float = 0.0
    avg_policy_score: float = 0.0

    # 行业分布
    sector_distribution: dict[str, int] = field(default_factory=dict)

    # 更新时间
    last_updated: date = field(default_factory=date.today)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "pool_type": self.pool_type.value,
            "asset_category": self.asset_category.value,
            "total_count": self.total_count,
            "avg_score": round(self.avg_score, 2),
            "avg_regime_score": round(self.avg_regime_score, 2),
            "avg_policy_score": round(self.avg_policy_score, 2),
            "sector_distribution": self.sector_distribution,
            "last_updated": self.last_updated.isoformat(),
        }


@dataclass
class PoolConfig:
    """资产池配置"""
    pool_type: PoolType
    asset_category: PoolCategory

    # 准入阈值
    min_total_score: float = 60.0
    min_regime_score: float = 50.0
    min_policy_score: float = 50.0

    # 禁投阈值
    max_total_score: float = 30.0
    max_regime_score: float = 40.0
    max_policy_score: float = 40.0

    # 观察池阈值（边界区域）
    watch_min_score: float = 30.0
    watch_max_score: float = 60.0

    # 风险控制
    max_volatility: float | None = None  # 最大波动率
    max_drawdown: float | None = None    # 最大回撤

    # 其他限制
    min_market_cap: float | None = None  # 最小市值（元）
    max_pe_ratio: float | None = None    # 最大PE
    max_pb_ratio: float | None = None    # 最大PB

    def is_investable(self, total_score: float, regime_score: float, policy_score: float) -> bool:
        """判断是否可投"""
        return (
            total_score >= self.min_total_score and
            regime_score >= self.min_regime_score and
            policy_score >= self.min_policy_score
        )

    def is_prohibited(self, total_score: float, regime_score: float, policy_score: float) -> bool:
        """判断是否禁投"""
        return (
            total_score <= self.max_total_score or
            regime_score <= self.max_regime_score or
            policy_score <= self.max_policy_score
        )

    def is_watch(self, total_score: float) -> bool:
        """判断是否观察"""
        return self.watch_min_score < total_score < self.watch_max_score
