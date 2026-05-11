"""
Decision Rhythm Application Layer DTOs

统一推荐相关的数据传输对象。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .user_action_labels import build_user_action_label

if TYPE_CHECKING:
    from ..domain.entities import UnifiedRecommendation


@dataclass
class UnifiedRecommendationDTO:
    """
    统一推荐 API 响应 DTO

    用于 API 响应的统一推荐数据传输对象。

    Attributes:
        recommendation_id: 推荐唯一标识
        account_id: 账户 ID
        security_code: 证券代码
        side: 方向 (BUY/SELL/HOLD)
        regime: 当前 Regime 状态
        regime_confidence: Regime 置信度
        policy_level: 政策档位
        beta_gate_passed: Beta Gate 是否通过
        sentiment_score: 舆情分数
        flow_score: 资金流向分数
        technical_score: 技术面分数
        fundamental_score: 基本面分数
        alpha_model_score: Alpha 模型分数
        composite_score: 综合分数
        confidence: 置信度
        reason_codes: 原因代码列表
        human_rationale: 人类可读理由
        fair_value: 公允价值
        entry_price_low: 入场价格下限
        entry_price_high: 入场价格上限
        target_price_low: 目标价格下限
        target_price_high: 目标价格上限
        stop_loss_price: 止损价格
        position_pct: 建议仓位比例
        suggested_quantity: 建议数量
        max_capital: 最大资金量
        source_signal_ids: 来源信号 ID 列表
        source_candidate_ids: 来源候选 ID 列表
        feature_snapshot_id: 特征快照 ID
        status: 推荐状态
        created_at: 创建时间
        updated_at: 更新时间
    """

    recommendation_id: str
    account_id: str
    security_code: str
    side: str
    security_name: str = field(default="", kw_only=True)
    # Top-down
    regime: str = ""
    regime_confidence: float = 0.0
    policy_level: str = ""
    beta_gate_passed: bool = False
    # Bottom-up
    sentiment_score: float = 0.0
    flow_score: float = 0.0
    technical_score: float = 0.0
    fundamental_score: float = 0.0
    alpha_model_score: float = 0.0
    # 综合
    composite_score: float = 0.0
    confidence: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    human_rationale: str = ""
    # 交易参数
    fair_value: Decimal = Decimal("0")
    entry_price_low: Decimal = Decimal("0")
    entry_price_high: Decimal = Decimal("0")
    target_price_low: Decimal = Decimal("0")
    target_price_high: Decimal = Decimal("0")
    stop_loss_price: Decimal = Decimal("0")
    position_pct: float = 5.0
    suggested_quantity: int = 0
    max_capital: Decimal = Decimal("50000")
    # 溯源
    source_signal_ids: list[str] = field(default_factory=list)
    source_candidate_ids: list[str] = field(default_factory=list)
    feature_snapshot_id: str = ""
    valuation_repair: dict[str, Any] | None = None
    # 状态
    status: str = "NEW"
    user_action: str = "PENDING"
    user_action_note: str = ""
    user_action_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_domain(
        cls,
        recommendation: "UnifiedRecommendation",
    ) -> "UnifiedRecommendationDTO":
        """
        从 Domain 实体创建 DTO

        Args:
            recommendation: UnifiedRecommendation 实体

        Returns:
            UnifiedRecommendationDTO 实例
        """
        return cls(
            recommendation_id=recommendation.recommendation_id,
            account_id=recommendation.account_id,
            security_code=recommendation.security_code,
            security_name=getattr(recommendation, "security_name", ""),
            side=recommendation.side,
            regime=recommendation.regime,
            regime_confidence=recommendation.regime_confidence,
            policy_level=recommendation.policy_level,
            beta_gate_passed=recommendation.beta_gate_passed,
            sentiment_score=recommendation.sentiment_score,
            flow_score=recommendation.flow_score,
            technical_score=recommendation.technical_score,
            fundamental_score=recommendation.fundamental_score,
            alpha_model_score=recommendation.alpha_model_score,
            composite_score=recommendation.composite_score,
            confidence=recommendation.confidence,
            reason_codes=recommendation.reason_codes,
            human_rationale=recommendation.human_rationale,
            fair_value=recommendation.fair_value,
            entry_price_low=recommendation.entry_price_low,
            entry_price_high=recommendation.entry_price_high,
            target_price_low=recommendation.target_price_low,
            target_price_high=recommendation.target_price_high,
            stop_loss_price=recommendation.stop_loss_price,
            position_pct=recommendation.position_pct,
            suggested_quantity=recommendation.suggested_quantity,
            max_capital=recommendation.max_capital,
            source_signal_ids=recommendation.source_signal_ids,
            source_candidate_ids=recommendation.source_candidate_ids,
            feature_snapshot_id=recommendation.feature_snapshot_id,
            status=recommendation.status.value,
            user_action=recommendation.user_action.value,
            user_action_note=recommendation.user_action_note,
            user_action_at=recommendation.user_action_at,
            created_at=recommendation.created_at,
            updated_at=recommendation.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典

        Returns:
            字典表示
        """
        return {
            "recommendation_id": self.recommendation_id,
            "account_id": self.account_id,
            "security_code": self.security_code,
            "security_name": self.security_name or self.security_code,
            "side": self.side,
            "regime": self.regime,
            "regime_confidence": self.regime_confidence,
            "policy_level": self.policy_level,
            "beta_gate_passed": self.beta_gate_passed,
            "sentiment_score": self.sentiment_score,
            "flow_score": self.flow_score,
            "technical_score": self.technical_score,
            "fundamental_score": self.fundamental_score,
            "alpha_model_score": self.alpha_model_score,
            "composite_score": self.composite_score,
            "confidence": self.confidence,
            "reason_codes": self.reason_codes,
            "human_rationale": self.human_rationale,
            "fair_value": str(self.fair_value),
            "entry_price_low": str(self.entry_price_low),
            "entry_price_high": str(self.entry_price_high),
            "target_price_low": str(self.target_price_low),
            "target_price_high": str(self.target_price_high),
            "stop_loss_price": str(self.stop_loss_price),
            "position_pct": self.position_pct,
            "suggested_quantity": self.suggested_quantity,
            "max_capital": str(self.max_capital),
            "source_signal_ids": self.source_signal_ids,
            "source_candidate_ids": self.source_candidate_ids,
            "feature_snapshot_id": self.feature_snapshot_id,
            "valuation_repair": self.valuation_repair,
            "status": self.status,
            "user_action": self.user_action,
            "user_action_label": build_user_action_label(self.user_action),
            "user_action_note": self.user_action_note,
            "user_action_at": self.user_action_at.isoformat() if self.user_action_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class RefreshRecommendationsRequestDTO:
    """
    刷新推荐请求 DTO

    用于手动触发推荐重算的请求。

    Attributes:
        account_id: 账户 ID（可选，不传则刷新所有账户）
        security_codes: 证券代码列表（可选，不传则刷新所有证券）
        force: 是否强制刷新（忽略缓存）
        async_mode: 是否异步执行
    """

    account_id: str | None = None
    security_codes: list[str] | None = None
    force: bool = False
    async_mode: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RefreshRecommendationsRequestDTO":
        """
        从字典创建 DTO

        Args:
            data: 输入字典

        Returns:
            RefreshRecommendationsRequestDTO 实例
        """
        return cls(
            account_id=data.get("account_id"),
            security_codes=data.get("security_codes"),
            force=data.get("force", False),
            async_mode=data.get("async_mode", True),
        )


@dataclass
class RefreshRecommendationsResponseDTO:
    """
    刷新推荐响应 DTO

    刷新操作的响应。

    Attributes:
        task_id: 异步任务 ID（如果是异步模式）
        status: 任务状态
        message: 状态消息
        recommendations_count: 生成的推荐数量
        conflicts_count: 冲突数量
    """

    task_id: str | None = None
    status: str = "PENDING"
    message: str = ""
    recommendations_count: int = 0
    conflicts_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典

        Returns:
            字典表示
        """
        return {
            "task_id": self.task_id,
            "status": self.status,
            "message": self.message,
            "recommendations_count": self.recommendations_count,
            "conflicts_count": self.conflicts_count,
        }


@dataclass
class ConflictDTO:
    """
    冲突对象 DTO

    用于表示同证券 BUY/SELL 冲突。

    Attributes:
        security_code: 证券代码
        account_id: 账户 ID
        buy_recommendation: BUY 方向的推荐
        sell_recommendation: SELL 方向的推荐
        conflict_type: 冲突类型
        resolution_hint: 解决提示
    """

    security_code: str
    account_id: str
    security_name: str = ""
    buy_recommendation: UnifiedRecommendationDTO | None = None
    sell_recommendation: UnifiedRecommendationDTO | None = None
    conflict_type: str = "BUY_SELL_CONFLICT"
    resolution_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典

        Returns:
            字典表示
        """
        return {
            "security_code": self.security_code,
            "security_name": self.security_name or self.security_code,
            "account_id": self.account_id,
            "buy_recommendation": (
                self.buy_recommendation.to_dict() if self.buy_recommendation else None
            ),
            "sell_recommendation": (
                self.sell_recommendation.to_dict() if self.sell_recommendation else None
            ),
            "conflict_type": self.conflict_type,
            "resolution_hint": self.resolution_hint,
        }


@dataclass
class RecommendationsListDTO:
    """
    推荐列表 DTO

    用于 API 响应的推荐列表。

    Attributes:
        recommendations: 推荐列表
        total_count: 总数
        page: 当前页
        page_size: 每页大小
    """

    recommendations: list[UnifiedRecommendationDTO]
    total_count: int = 0
    page: int = 1
    page_size: int = 20

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典

        Returns:
            字典表示
        """
        return {
            "recommendations": [r.to_dict() for r in self.recommendations],
            "total_count": self.total_count,
            "page": self.page,
            "page_size": self.page_size,
        }


@dataclass
class ConflictsListDTO:
    """
    冲突列表 DTO

    用于 API 响应的冲突列表。

    Attributes:
        conflicts: 冲突列表
        total_count: 总数
    """

    conflicts: list[ConflictDTO]
    total_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典

        Returns:
            字典表示
        """
        return {
            "conflicts": [c.to_dict() for c in self.conflicts],
            "total_count": self.total_count,
        }


@dataclass
class ExecutionPreviewDTO:
    """
    执行预览 DTO

    用于执行前的预览数据。

    Attributes:
        recommendation_id: 推荐唯一标识
        security_code: 证券代码
        side: 方向
        fair_value: 公允价值
        entry_price_low: 入场价格下限
        entry_price_high: 入场价格上限
        target_price_low: 目标价格下限
        target_price_high: 目标价格上限
        stop_loss_price: 止损价格
        position_pct: 建议仓位比例
        suggested_quantity: 建议数量
        max_capital: 最大资金量
        risk_check_results: 风控检查结果
        approval_request_id: 审批请求 ID
    """

    recommendation_id: str
    security_code: str
    side: str
    fair_value: Decimal
    entry_price_low: Decimal
    entry_price_high: Decimal
    target_price_low: Decimal
    target_price_high: Decimal
    stop_loss_price: Decimal
    position_pct: float
    suggested_quantity: int
    max_capital: Decimal
    risk_check_results: dict[str, Any]
    approval_request_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典

        Returns:
            字典表示
        """
        return {
            "recommendation_id": self.recommendation_id,
            "security_code": self.security_code,
            "side": self.side,
            "fair_value": str(self.fair_value),
            "entry_price_low": str(self.entry_price_low),
            "entry_price_high": str(self.entry_price_high),
            "target_price_low": str(self.target_price_low),
            "target_price_high": str(self.target_price_high),
            "stop_loss_price": str(self.stop_loss_price),
            "position_pct": self.position_pct,
            "suggested_quantity": self.suggested_quantity,
            "max_capital": str(self.max_capital),
            "risk_check_results": self.risk_check_results,
            "approval_request_id": self.approval_request_id,
        }


@dataclass
class TransitionOrderDTO:
    """交易计划订单 DTO。"""

    security_code: str
    action: str
    current_qty: int
    target_qty: int
    delta_qty: int
    current_weight: float
    target_weight: float
    price_band_low: str
    price_band_high: str
    max_capital: str
    stop_loss_price: str | None
    invalidation_rule: dict[str, Any]
    invalidation_description: str
    requires_user_confirmation: bool
    review_by: str | None
    time_horizon: str
    source_recommendation_id: str
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_code": self.security_code,
            "action": self.action,
            "current_qty": self.current_qty,
            "target_qty": self.target_qty,
            "delta_qty": self.delta_qty,
            "current_weight": self.current_weight,
            "target_weight": self.target_weight,
            "price_band_low": self.price_band_low,
            "price_band_high": self.price_band_high,
            "max_capital": self.max_capital,
            "stop_loss_price": self.stop_loss_price,
            "invalidation_rule": self.invalidation_rule,
            "invalidation_description": self.invalidation_description,
            "requires_user_confirmation": self.requires_user_confirmation,
            "review_by": self.review_by,
            "time_horizon": self.time_horizon,
            "source_recommendation_id": self.source_recommendation_id,
            "notes": self.notes,
        }


@dataclass
class PortfolioTransitionPlanDTO:
    """账户级调仓计划 DTO。"""

    plan_id: str
    account_id: str
    as_of: str
    source_recommendation_ids: list[str]
    current_positions: list[dict[str, Any]]
    target_positions: list[dict[str, Any]]
    orders: list[TransitionOrderDTO]
    risk_contract: dict[str, Any]
    summary: dict[str, Any]
    status: str
    approval_request_id: str | None
    can_enter_approval: bool
    blocking_issues: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "account_id": self.account_id,
            "as_of": self.as_of,
            "source_recommendation_ids": self.source_recommendation_ids,
            "current_positions": self.current_positions,
            "target_positions": self.target_positions,
            "orders": [order.to_dict() for order in self.orders],
            "risk_contract": self.risk_contract,
            "summary": self.summary,
            "status": self.status,
            "approval_request_id": self.approval_request_id,
            "can_enter_approval": self.can_enter_approval,
            "blocking_issues": self.blocking_issues,
        }


@dataclass
class ApproveExecutionRequestDTO:
    """
    批准执行请求 DTO

    用于批准执行的请求。

    Attributes:
        approval_request_id: 审批请求 ID
        reviewer_comments: 审批评论（必填）
        execution_params: 执行参数
    """

    approval_request_id: str
    reviewer_comments: str
    execution_params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApproveExecutionRequestDTO":
        """
        从字典创建 DTO

        Args:
            data: 输入字典

        Returns:
            ApproveExecutionRequestDTO 实例
        """
        return cls(
            approval_request_id=data.get("approval_request_id", ""),
            reviewer_comments=data.get("reviewer_comments", ""),
            execution_params=data.get("execution_params", {}),
        )


@dataclass
class RejectExecutionRequestDTO:
    """
    拒绝执行请求 DTO

    用于拒绝执行的请求。

    Attributes:
        approval_request_id: 审批请求 ID
        reviewer_comments: 审批评论（必填）
    """

    approval_request_id: str
    reviewer_comments: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RejectExecutionRequestDTO":
        """
        从字典创建 DTO

        Args:
            data: 输入字典

        Returns:
            RejectExecutionRequestDTO 实例
        """
        return cls(
            approval_request_id=data.get("approval_request_id", ""),
            reviewer_comments=data.get("reviewer_comments", ""),
        )


@dataclass
class ExecutionResponseDTO:
    """
    执行响应 DTO

    执行操作的响应。

    Attributes:
        success: 是否成功
        message: 消息
        execution_ref: 执行引用
        executed_at: 执行时间
    """

    success: bool
    message: str = ""
    execution_ref: dict[str, Any] | None = None
    executed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典

        Returns:
            字典表示
        """
        return {
            "success": self.success,
            "message": self.message,
            "execution_ref": self.execution_ref,
            "executed_at": (self.executed_at.isoformat() if self.executed_at else None),
        }
