"""Decision valuation, investment recommendation, and approval entities."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from apps.valuation.domain.entities import (
    ValuationMethod,
    ValuationSnapshot,
    create_valuation_snapshot,
)


class ApprovalStatus(Enum):
    """
    审批状态枚举

    定义执行审批的状态流转。
    """

    DRAFT = "DRAFT"
    """草稿：初始状态"""

    PENDING = "PENDING"
    """待审批：已提交审批"""

    APPROVED = "APPROVED"
    """已批准：审批通过"""

    REJECTED = "REJECTED"
    """已拒绝：审批拒绝"""

    EXECUTED = "EXECUTED"
    """已执行：执行完成"""

    FAILED = "FAILED"
    """执行失败：执行出错"""


class RecommendationSide(Enum):
    """
    投资建议方向枚举
    """

    BUY = "BUY"
    """买入"""

    SELL = "SELL"
    """卖出"""

    HOLD = "HOLD"
    """持有"""


@dataclass(frozen=True)
class InvestmentRecommendation:
    """
    投资建议

    完整的投资建议，包含方向、价格区间、数量建议和风险预算。

    Attributes:
        recommendation_id: 建议唯一标识
        security_code: 证券代码
        side: 方向 (BUY/SELL/HOLD)
        confidence: 置信度 (0-1)
        valuation_method: 估值方法
        fair_value: 公允价值
        entry_price_low: 入场价格下限
        entry_price_high: 入场价格上限
        target_price_low: 目标价格下限
        target_price_high: 目标价格上限
        stop_loss_price: 止损价格
        position_size_pct: 建议仓位比例
        max_capital: 最大资金量
        reason_codes: 原因代码列表
        human_readable_rationale: 人类可读的理由
        account_id: 账户 ID（用于账户内归并）
        valuation_snapshot_id: 关联的估值快照 ID
        source_recommendation_ids: 来源建议 ID 列表（用于聚合）
        created_at: 创建时间
        status: 建议状态

    Example:
        >>> rec = InvestmentRecommendation(
        ...     recommendation_id="rec_001",
        ...     security_code="000001.SH",
        ...     side=RecommendationSide.BUY.value,
        ...     confidence=0.85,
        ...     valuation_method=ValuationMethod.COMPOSITE.value,
        ...     fair_value=Decimal("12.50"),
        ...     entry_price_low=Decimal("10.50"),
        ...     entry_price_high=Decimal("11.00"),
        ...     target_price_low=Decimal("13.00"),
        ...     target_price_high=Decimal("14.50"),
        ...     stop_loss_price=Decimal("9.50"),
        ...     position_size_pct=5.0,
        ...     max_capital=Decimal("50000"),
        ...     reason_codes=["PMI_RECOVERY", "VALUATION_LOW"],
        ...     human_readable_rationale="PMI 连续回升，估值处于历史低位",
        ...     valuation_snapshot_id="vs_001",
        ...     source_recommendation_ids=[],
        ...     created_at=datetime.now(timezone.utc),
        ...     status="ACTIVE",
        ... )
    """

    recommendation_id: str
    security_code: str
    side: str  # RecommendationSide enum value
    confidence: float
    valuation_method: str
    fair_value: Decimal
    entry_price_low: Decimal
    entry_price_high: Decimal
    target_price_low: Decimal
    target_price_high: Decimal
    stop_loss_price: Decimal
    position_size_pct: float
    max_capital: Decimal
    reason_codes: list[str]
    human_readable_rationale: str
    account_id: str
    valuation_snapshot_id: str
    source_recommendation_ids: list[str]
    created_at: datetime
    status: str = "ACTIVE"

    @property
    def is_buy(self) -> bool:
        """是否买入建议"""
        return self.side == RecommendationSide.BUY.value

    @property
    def is_sell(self) -> bool:
        """是否卖出建议"""
        return self.side == RecommendationSide.SELL.value

    @property
    def suggested_quantity(self) -> int:
        """建议数量（基于入场价中位和最大资金）"""
        entry_mid = (self.entry_price_low + self.entry_price_high) / 2
        if entry_mid > 0:
            return int(self.max_capital / entry_mid)
        return 0

    @property
    def price_range(self) -> dict[str, Decimal]:
        """价格区间摘要"""
        return {
            "entry_low": self.entry_price_low,
            "entry_high": self.entry_price_high,
            "target_low": self.target_price_low,
            "target_high": self.target_price_high,
            "stop_loss": self.stop_loss_price,
        }

    def validate_buy_price(self, market_price: Decimal) -> tuple[bool, str]:
        """
        验证买入价格是否合理

        Args:
            market_price: 市场价格

        Returns:
            (是否合理, 原因)
        """
        if not self.is_buy:
            return False, "非买入建议"

        if market_price > self.entry_price_high:
            return False, f"市场价格 {market_price} 高于入场上限 {self.entry_price_high}"
        return True, "价格合理"

    def validate_sell_price(
        self, market_price: Decimal, triggered_by_risk: bool = False
    ) -> tuple[bool, str]:
        """
        验证卖出价格是否合理

        Args:
            market_price: 市场价格
            triggered_by_risk: 是否由风控触发

        Returns:
            (是否合理, 原因)
        """
        if not self.is_sell:
            return False, "非卖出建议"

        if triggered_by_risk:
            return True, "风控触发卖出"

        if market_price < self.target_price_low:
            return False, f"市场价格 {market_price} 低于目标下限 {self.target_price_low}"
        return True, "价格合理"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "recommendation_id": self.recommendation_id,
            "security_code": self.security_code,
            "side": self.side,
            "confidence": self.confidence,
            "valuation_method": self.valuation_method,
            "fair_value": str(self.fair_value),
            "entry_price_low": str(self.entry_price_low),
            "entry_price_high": str(self.entry_price_high),
            "target_price_low": str(self.target_price_low),
            "target_price_high": str(self.target_price_high),
            "stop_loss_price": str(self.stop_loss_price),
            "position_size_pct": self.position_size_pct,
            "max_capital": str(self.max_capital),
            "suggested_quantity": self.suggested_quantity,
            "reason_codes": self.reason_codes,
            "human_readable_rationale": self.human_readable_rationale,
            "account_id": self.account_id,
            "valuation_snapshot_id": self.valuation_snapshot_id,
            "source_recommendation_ids": self.source_recommendation_ids,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
        }


@dataclass(frozen=True)
class ExecutionApprovalRequest:
    """
    执行审批请求

    标准交易审批单，用于执行前的审批流程。

    Attributes:
        request_id: 请求唯一标识
        recommendation_id: 关联的投资建议 ID
        account_id: 账户 ID
        security_code: 证券代码
        side: 方向
        approval_status: 审批状态
        suggested_quantity: 建议数量
        market_price_at_review: 审批时的市场价格
        price_range_low: 价格区间下限
        price_range_high: 价格区间上限
        stop_loss_price: 止损价格
        risk_check_results: 风控检查结果
        reviewer_comments: 审批评论
        regime_source: Regime 来源标识
        created_at: 创建时间
        reviewed_at: 审批时间
        executed_at: 执行时间

    Example:
        >>> approval = ExecutionApprovalRequest(
        ...     request_id="apr_001",
        ...     recommendation_id="rec_001",
        ...     plan_id=None,
        ...     account_id="account_1",
        ...     security_code="000001.SH",
        ...     side=RecommendationSide.BUY.value,
        ...     approval_status=ApprovalStatus.PENDING,
        ...     suggested_quantity=500,
        ...     market_price_at_review=Decimal("10.80"),
        ...     price_range_low=Decimal("10.50"),
        ...     price_range_high=Decimal("11.00"),
        ...     stop_loss_price=Decimal("9.50"),
        ...     risk_check_results={"beta_gate": {"passed": True}},
        ...     reviewer_comments="",
        ...     regime_source="V2_CALCULATION",
        ...     created_at=datetime.now(timezone.utc),
        ... )
    """

    request_id: str
    recommendation_id: str
    plan_id: str | None
    account_id: str
    security_code: str
    side: str
    approval_status: ApprovalStatus
    suggested_quantity: int
    market_price_at_review: Decimal | None
    price_range_low: Decimal
    price_range_high: Decimal
    stop_loss_price: Decimal
    risk_check_results: dict[str, Any]
    reviewer_comments: str
    regime_source: str
    created_at: datetime
    reviewed_at: datetime | None = None
    executed_at: datetime | None = None

    @property
    def is_pending(self) -> bool:
        """是否待审批"""
        return self.approval_status == ApprovalStatus.PENDING

    @property
    def is_approved(self) -> bool:
        """是否已批准"""
        return self.approval_status == ApprovalStatus.APPROVED

    @property
    def is_executed(self) -> bool:
        """是否已执行"""
        return self.approval_status == ApprovalStatus.EXECUTED

    @property
    def is_rejected(self) -> bool:
        """是否已拒绝"""
        return self.approval_status == ApprovalStatus.REJECTED

    @property
    def aggregation_key(self) -> str:
        """聚合键（账户+证券+方向）"""
        return f"{self.account_id}:{self.security_code}:{self.side}"

    def validate_price_for_approval(self, market_price: Decimal) -> tuple[bool, str]:
        """
        验证价格是否允许审批

        Args:
            market_price: 当前市场价格

        Returns:
            (是否允许, 原因)
        """
        if self.side == RecommendationSide.BUY.value:
            if market_price > self.price_range_high:
                return False, f"买入价格 {market_price} 超过上限 {self.price_range_high}"
        elif self.side == RecommendationSide.SELL.value:
            # SELL 允许风控触发
            pass

        return True, "价格验证通过"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "request_id": self.request_id,
            "recommendation_id": self.recommendation_id,
            "plan_id": self.plan_id,
            "account_id": self.account_id,
            "security_code": self.security_code,
            "side": self.side,
            "approval_status": self.approval_status.value,
            "suggested_quantity": self.suggested_quantity,
            "market_price_at_review": (
                str(self.market_price_at_review) if self.market_price_at_review else None
            ),
            "price_range_low": str(self.price_range_low),
            "price_range_high": str(self.price_range_high),
            "stop_loss_price": str(self.stop_loss_price),
            "risk_check_results": self.risk_check_results,
            "reviewer_comments": self.reviewer_comments,
            "regime_source": self.regime_source,
            "created_at": self.created_at.isoformat(),
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "aggregation_key": self.aggregation_key,
            "is_pending": self.is_pending,
            "is_approved": self.is_approved,
            "is_executed": self.is_executed,
            "is_rejected": self.is_rejected,
        }


def create_investment_recommendation(
    security_code: str,
    side: str,
    confidence: float,
    valuation_snapshot: ValuationSnapshot,
    account_id: str = "default",
    position_size_pct: float = 5.0,
    max_capital: Decimal = Decimal("50000"),
    reason_codes: list[str] | None = None,
    human_readable_rationale: str = "",
    source_recommendation_ids: list[str] | None = None,
) -> InvestmentRecommendation:
    """
    创建投资建议的便捷函数

    Args:
        security_code: 证券代码
        side: 方向
        confidence: 置信度
        valuation_snapshot: 估值快照
        position_size_pct: 建议仓位比例
        max_capital: 最大资金量
        reason_codes: 原因代码列表
        human_readable_rationale: 人类可读的理由
        source_recommendation_ids: 来源建议 ID 列表

    Returns:
        InvestmentRecommendation 实例
    """
    return InvestmentRecommendation(
        recommendation_id=f"rec_{uuid4().hex[:12]}",
        security_code=security_code,
        side=side,
        confidence=confidence,
        valuation_method=valuation_snapshot.valuation_method,
        fair_value=valuation_snapshot.fair_value,
        entry_price_low=valuation_snapshot.entry_price_low,
        entry_price_high=valuation_snapshot.entry_price_high,
        target_price_low=valuation_snapshot.target_price_low,
        target_price_high=valuation_snapshot.target_price_high,
        stop_loss_price=valuation_snapshot.stop_loss_price,
        position_size_pct=position_size_pct,
        max_capital=max_capital,
        reason_codes=reason_codes or [],
        human_readable_rationale=human_readable_rationale,
        account_id=account_id,
        valuation_snapshot_id=valuation_snapshot.snapshot_id,
        source_recommendation_ids=source_recommendation_ids or [],
        created_at=datetime.now(UTC),
    )


def create_execution_approval_request(
    recommendation: InvestmentRecommendation,
    account_id: str,
    risk_check_results: dict[str, Any],
    regime_source: str,
    suggested_quantity: int | None = None,
    market_price_at_review: Decimal | None = None,
) -> ExecutionApprovalRequest:
    """
    创建执行审批请求的便捷函数

    Args:
        recommendation: 投资建议
        account_id: 账户 ID
        risk_check_results: 风控检查结果
        regime_source: Regime 来源标识
        suggested_quantity: 建议数量（默认使用建议的计算值）
        market_price_at_review: 审批时的市场价格

    Returns:
        ExecutionApprovalRequest 实例
    """
    return ExecutionApprovalRequest(
        request_id=f"apr_{uuid4().hex[:12]}",
        recommendation_id=recommendation.recommendation_id,
        plan_id=None,
        account_id=account_id,
        security_code=recommendation.security_code,
        side=recommendation.side,
        approval_status=ApprovalStatus.PENDING,
        suggested_quantity=suggested_quantity or recommendation.suggested_quantity,
        market_price_at_review=market_price_at_review,
        price_range_low=recommendation.entry_price_low,
        price_range_high=recommendation.entry_price_high,
        stop_loss_price=recommendation.stop_loss_price,
        risk_check_results=risk_check_results,
        reviewer_comments="",
        regime_source=regime_source,
        created_at=datetime.now(UTC),
    )


__all__ = [
    "ValuationMethod",
    "ApprovalStatus",
    "RecommendationSide",
    "ValuationSnapshot",
    "InvestmentRecommendation",
    "ExecutionApprovalRequest",
    "create_valuation_snapshot",
    "create_investment_recommendation",
    "create_execution_approval_request",
]
