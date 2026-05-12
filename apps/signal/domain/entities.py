"""
Domain Entities for Investment Signals.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, Optional

from apps.regime.domain.asset_eligibility import Eligibility

if TYPE_CHECKING:
    from .invalidation import InvalidationRule

__all__ = [
    "Eligibility",
    "InvestmentSignal",
    "SignalStatus",
]


class SignalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


@dataclass
class InvestmentSignal:
    """投资信号实体

    包含信号的基本信息和证伪规则。

    Attributes:
        id: 信号ID
        asset_code: 资产代码（如 ASSET_CODE）
        asset_class: 资产类别（如 a_share_growth）
        direction: 方向（LONG/SHORT/NEUTRAL）
        logic_desc: 信号逻辑描述
        invalidation_rule: 证伪规则（结构化对象）
        invalidation_description: 证伪逻辑的人类可读描述
        target_regime: 目标 Regime
        created_at: 创建日期
        status: 信号状态
        rejection_reason: 拒绝原因
        backtest_performance_score: 回测表现评分
        avg_backtest_return: 平均回测收益率
    """
    id: str | None
    asset_code: str
    asset_class: str
    direction: str  # LONG, SHORT, NEUTRAL
    logic_desc: str

    # 证伪规则（替代原来的 invalidation_logic + invalidation_threshold）
    invalidation_rule: Optional["InvalidationRule"] = None
    invalidation_description: str | None = None  # 人类可读描述
    # backward-compatible legacy fields
    invalidation_logic: str | None = None
    invalidation_threshold: float | None = None

    target_regime: str = ""
    created_at: date | None = None
    status: SignalStatus = SignalStatus.PENDING
    rejection_reason: str | None = None

    # 回测评分
    backtest_performance_score: float | None = None
    avg_backtest_return: float | None = None

    def __post_init__(self) -> None:
        # Keep legacy and new fields interoperable.
        if self.invalidation_description is None and self.invalidation_logic is not None:
            self.invalidation_description = self.invalidation_logic
        if self.invalidation_logic is None and self.invalidation_description is not None:
            self.invalidation_logic = self.invalidation_description

    @property
    def has_invalidation_rule(self) -> bool:
        """是否有证伪规则"""
        return self.invalidation_rule is not None

    @property
    def human_readable_invalidation(self) -> str:
        """获取人类可读的证伪描述"""
        if self.invalidation_rule:
            return self.invalidation_rule.human_readable
        return self.invalidation_description or "未设置证伪条件"
