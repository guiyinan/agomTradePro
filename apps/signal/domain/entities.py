"""
Domain Entities for Investment Signals.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional, TYPE_CHECKING
from shared.domain.asset_eligibility import Eligibility

if TYPE_CHECKING:
    from .invalidation import InvalidationRule


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
        asset_code: 资产代码（如 000001.SH）
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
    id: Optional[str]
    asset_code: str
    asset_class: str
    direction: str  # LONG, SHORT, NEUTRAL
    logic_desc: str

    # 证伪规则（替代原来的 invalidation_logic + invalidation_threshold）
    invalidation_rule: Optional["InvalidationRule"] = None
    invalidation_description: Optional[str] = None  # 人类可读描述

    target_regime: str = ""
    created_at: Optional[date] = None
    status: SignalStatus = SignalStatus.PENDING
    rejection_reason: Optional[str] = None

    # 回测评分
    backtest_performance_score: Optional[float] = None
    avg_backtest_return: Optional[float] = None

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
