"""Unified decision recommendation and feature snapshot entities."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4


class RecommendationStatus(Enum):
    """
    统一推荐状态枚举

    定义推荐对象的生命周期状态。
    """

    NEW = "NEW"
    """新建：推荐刚生成"""

    REVIEWING = "REVIEWING"
    """审核中：正在审核"""

    APPROVED = "APPROVED"
    """已批准：审批通过，等待执行"""

    REJECTED = "REJECTED"
    """已拒绝：审批拒绝"""

    EXECUTED = "EXECUTED"
    """已执行：执行完成"""

    FAILED = "FAILED"
    """执行失败：执行出错"""

    CONFLICT = "CONFLICT"
    """冲突：同证券 BUY/SELL 冲突"""


class UserDecisionAction(Enum):
    """
    用户决策动作枚举

    独立于 RecommendationStatus，用于表示用户对系统推荐的主观决策。
    """

    PENDING = "PENDING"
    """待决策：系统已生成，用户尚未表态"""

    WATCHING = "WATCHING"
    """观察中：用户加入观察名单"""

    ADOPTED = "ADOPTED"
    """已采纳：用户接受推荐，后续可进入审批/执行"""

    IGNORED = "IGNORED"
    """已忽略：用户明确忽略该推荐"""


class DecisionFeatureSnapshot:
    """
    决策特征快照

    保存打分输入快照，支持回放与审计。

    Attributes:
        snapshot_id: 快照唯一标识
        security_code: 证券代码
        snapshot_time: 快照时间
        regime: 当前 Regime 状态
        regime_confidence: Regime 置信度
        policy_level: 政策档位
        beta_gate_passed: Beta Gate 是否通过
        sentiment_score: 舆情分数
        flow_score: 资金流向分数
        technical_score: 技术面分数
        fundamental_score: 基本面分数
        alpha_model_score: Alpha 模型分数
        extra_features: 额外特征
        created_at: 创建时间
    """

    snapshot_id: str
    security_code: str
    snapshot_time: datetime
    # Top-down 特征
    regime: str
    regime_confidence: float
    policy_level: str
    beta_gate_passed: bool
    # Bottom-up 特征
    sentiment_score: float
    flow_score: float
    technical_score: float
    fundamental_score: float
    alpha_model_score: float
    # 额外特征
    extra_features: dict[str, Any]
    created_at: datetime

    def __init__(
        self,
        snapshot_id: str,
        security_code: str,
        snapshot_time: datetime,
        regime: str = "",
        regime_confidence: float = 0.0,
        policy_level: str = "",
        beta_gate_passed: bool = False,
        sentiment_score: float = 0.0,
        flow_score: float = 0.0,
        technical_score: float = 0.0,
        fundamental_score: float = 0.0,
        alpha_model_score: float = 0.0,
        extra_features: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ):
        self.snapshot_id = snapshot_id
        self.security_code = security_code
        self.snapshot_time = snapshot_time
        self.regime = regime
        self.regime_confidence = regime_confidence
        self.policy_level = policy_level
        self.beta_gate_passed = beta_gate_passed
        self.sentiment_score = sentiment_score
        self.flow_score = flow_score
        self.technical_score = technical_score
        self.fundamental_score = fundamental_score
        self.alpha_model_score = alpha_model_score
        self.extra_features = extra_features or {}
        self.created_at = created_at or datetime.now(UTC)

    def __repr__(self) -> str:
        return (
            f"DecisionFeatureSnapshot({self.snapshot_id}, {self.security_code}, "
            f"alpha={self.alpha_model_score:.2f})"
        )


class UnifiedRecommendation:
    """
    统一推荐对象

    融合 Top-down（宏观/Regime/Policy/Beta Gate）和
    Bottom-up（Alpha、舆情、价格等）的统一推荐对象。

    Attributes:
        recommendation_id: 推荐唯一标识
        account_id: 账户 ID
        security_code: 证券代码
        side: 方向 (BUY/SELL/HOLD)
        # Top-down 特征
        regime: 当前 Regime 状态
        regime_confidence: Regime 置信度
        policy_level: 政策档位
        beta_gate_passed: Beta Gate 是否通过
        # Bottom-up 特征
        sentiment_score: 舆情分数
        flow_score: 资金流向分数
        technical_score: 技术面分数
        fundamental_score: 基本面分数
        alpha_model_score: Alpha 模型分数
        # 综合分数
        composite_score: 综合分数
        confidence: 置信度
        reason_codes: 原因代码列表
        human_rationale: 人类可读理由
        # 交易参数
        fair_value: 公允价值
        entry_price_low: 入场价格下限
        entry_price_high: 入场价格上限
        target_price_low: 目标价格下限
        target_price_high: 目标价格上限
        stop_loss_price: 止损价格
        position_pct: 建议仓位比例
        suggested_quantity: 建议数量
        max_capital: 最大资金量
        # 溯源
        source_signal_ids: 来源信号 ID 列表
        source_candidate_ids: 来源候选 ID 列表
        feature_snapshot_id: 特征快照 ID
        # 状态
        status: 推荐状态
        user_action: 用户决策动作
        user_action_note: 用户备注
        user_action_at: 用户动作时间
        created_at: 创建时间
        updated_at: 更新时间
    """

    recommendation_id: str
    account_id: str
    security_code: str
    side: str
    # Top-down
    regime: str
    regime_confidence: float
    policy_level: str
    beta_gate_passed: bool
    # Bottom-up
    sentiment_score: float
    flow_score: float
    technical_score: float
    fundamental_score: float
    alpha_model_score: float
    # 综合
    composite_score: float
    confidence: float
    reason_codes: list[str]
    human_rationale: str
    # 交易参数
    fair_value: Decimal
    entry_price_low: Decimal
    entry_price_high: Decimal
    target_price_low: Decimal
    target_price_high: Decimal
    stop_loss_price: Decimal
    position_pct: float
    suggested_quantity: int
    max_capital: Decimal
    # 溯源
    source_signal_ids: list[str]
    source_candidate_ids: list[str]
    feature_snapshot_id: str
    # 状态
    status: RecommendationStatus
    user_action: UserDecisionAction
    user_action_note: str
    user_action_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def __init__(
        self,
        recommendation_id: str,
        account_id: str,
        security_code: str,
        side: str,
        regime: str = "",
        regime_confidence: float = 0.0,
        policy_level: str = "",
        beta_gate_passed: bool = False,
        sentiment_score: float = 0.0,
        flow_score: float = 0.0,
        technical_score: float = 0.0,
        fundamental_score: float = 0.0,
        alpha_model_score: float = 0.0,
        composite_score: float = 0.0,
        confidence: float = 0.0,
        reason_codes: list[str] | None = None,
        human_rationale: str = "",
        fair_value: Decimal = Decimal("0"),
        entry_price_low: Decimal = Decimal("0"),
        entry_price_high: Decimal = Decimal("0"),
        target_price_low: Decimal = Decimal("0"),
        target_price_high: Decimal = Decimal("0"),
        stop_loss_price: Decimal = Decimal("0"),
        position_pct: float = 5.0,
        suggested_quantity: int = 0,
        max_capital: Decimal = Decimal("50000"),
        source_signal_ids: list[str] | None = None,
        source_candidate_ids: list[str] | None = None,
        feature_snapshot_id: str = "",
        status: RecommendationStatus = RecommendationStatus.NEW,
        user_action: UserDecisionAction = UserDecisionAction.PENDING,
        user_action_note: str = "",
        user_action_at: datetime | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ):
        self.recommendation_id = recommendation_id
        self.account_id = account_id
        self.security_code = security_code
        self.side = side
        # Top-down
        self.regime = regime
        self.regime_confidence = regime_confidence
        self.policy_level = policy_level
        self.beta_gate_passed = beta_gate_passed
        # Bottom-up
        self.sentiment_score = sentiment_score
        self.flow_score = flow_score
        self.technical_score = technical_score
        self.fundamental_score = fundamental_score
        self.alpha_model_score = alpha_model_score
        # 综合
        self.composite_score = composite_score
        self.confidence = confidence
        self.reason_codes = reason_codes or []
        self.human_rationale = human_rationale
        # 交易参数
        self.fair_value = fair_value
        self.entry_price_low = entry_price_low
        self.entry_price_high = entry_price_high
        self.target_price_low = target_price_low
        self.target_price_high = target_price_high
        self.stop_loss_price = stop_loss_price
        self.position_pct = position_pct
        self.suggested_quantity = suggested_quantity
        self.max_capital = max_capital
        # 溯源
        self.source_signal_ids = source_signal_ids or []
        self.source_candidate_ids = source_candidate_ids or []
        self.feature_snapshot_id = feature_snapshot_id
        # 状态
        self.status = status
        self.user_action = user_action
        self.user_action_note = user_action_note
        self.user_action_at = user_action_at
        self.created_at = created_at or datetime.now(UTC)
        self.updated_at = updated_at or datetime.now(UTC)

    def __repr__(self) -> str:
        return (
            f"UnifiedRecommendation({self.recommendation_id}, "
            f"{self.account_id}/{self.security_code}/{self.side}, "
            f"composite={self.composite_score:.2f}, "
            f"status={self.status.value}, user_action={self.user_action.value})"
        )

    def get_aggregation_key(self) -> str:
        """
        获取聚合键

        用于按 account_id + security_code + side 去重。

        Returns:
            聚合键字符串
        """
        return f"{self.account_id}|{self.security_code}|{self.side}"

    def is_executable(self) -> bool:
        """
        判断是否可执行

        Returns:
            是否可执行（状态为 APPROVED 且通过 Beta Gate）
        """
        return self.status == RecommendationStatus.APPROVED and self.beta_gate_passed


def create_unified_recommendation(
    account_id: str,
    security_code: str,
    side: str,
    feature_snapshot: DecisionFeatureSnapshot,
    composite_score: float = 0.0,
    confidence: float = 0.0,
    reason_codes: list[str] | None = None,
    human_rationale: str = "",
    fair_value: Decimal = Decimal("0"),
    entry_price_low: Decimal = Decimal("0"),
    entry_price_high: Decimal = Decimal("0"),
    target_price_low: Decimal = Decimal("0"),
    target_price_high: Decimal = Decimal("0"),
    stop_loss_price: Decimal = Decimal("0"),
    position_pct: float = 5.0,
    suggested_quantity: int = 0,
    max_capital: Decimal = Decimal("50000"),
    source_signal_ids: list[str] | None = None,
    source_candidate_ids: list[str] | None = None,
) -> UnifiedRecommendation:
    """
    创建统一推荐对象的便捷函数

    Args:
        account_id: 账户 ID
        security_code: 证券代码
        side: 方向
        feature_snapshot: 特征快照
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

    Returns:
        UnifiedRecommendation 实例
    """
    return UnifiedRecommendation(
        recommendation_id=f"urec_{uuid4().hex[:12]}",
        account_id=account_id,
        security_code=security_code,
        side=side,
        # Top-down
        regime=feature_snapshot.regime,
        regime_confidence=feature_snapshot.regime_confidence,
        policy_level=feature_snapshot.policy_level,
        beta_gate_passed=feature_snapshot.beta_gate_passed,
        # Bottom-up
        sentiment_score=feature_snapshot.sentiment_score,
        flow_score=feature_snapshot.flow_score,
        technical_score=feature_snapshot.technical_score,
        fundamental_score=feature_snapshot.fundamental_score,
        alpha_model_score=feature_snapshot.alpha_model_score,
        # 综合
        composite_score=composite_score,
        confidence=confidence,
        reason_codes=reason_codes or [],
        human_rationale=human_rationale,
        # 交易参数
        fair_value=fair_value,
        entry_price_low=entry_price_low,
        entry_price_high=entry_price_high,
        target_price_low=target_price_low,
        target_price_high=target_price_high,
        stop_loss_price=stop_loss_price,
        position_pct=position_pct,
        suggested_quantity=suggested_quantity,
        max_capital=max_capital,
        # 溯源
        source_signal_ids=source_signal_ids or [],
        source_candidate_ids=source_candidate_ids or [],
        feature_snapshot_id=feature_snapshot.snapshot_id,
        status=RecommendationStatus.NEW,
    )


__all__ = [
    "RecommendationStatus",
    "UserDecisionAction",
    "DecisionFeatureSnapshot",
    "UnifiedRecommendation",
    "create_unified_recommendation",
]
