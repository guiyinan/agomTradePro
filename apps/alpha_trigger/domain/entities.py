"""
Alpha Trigger Domain Entities

Alpha 事件触发的核心实体定义。
实现离散、可证伪、可行动的 Alpha 信号触发机制。

仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TriggerType(Enum):
    """
    触发器类型枚举

    定义 Alpha 触发器的不同类型。
    """

    THRESHOLD_CROSS = "threshold_cross"
    """阈值穿越：指标穿越阈值时触发"""

    MOMENTUM_SIGNAL = "momentum_signal"
    """动量信号：动量指标确认趋势时触发"""

    REGIME_TRANSITION = "regime_transition"
    """Regime 转换：Regime 变化时触发"""

    POLICY_CHANGE = "policy_change"
    """政策变化：Policy 档位变化时触发"""

    MANUAL_OVERRIDE = "manual_override"
    """手动覆盖：人工手动触发"""

    STRUCTURAL_MISALIGNMENT = "structural_misalignment"
    """结构性错位：市场与宏观环境出现错位时触发"""

    SUPPLY_SHOCK = "supply_shock"
    """供给冲击：发行/配额异常时触发"""

    CREDIT_SPREAD = "credit_spread"
    """信用利差：利差进入极端分位时触发"""


class TriggerStatus(Enum):
    """
    触发器状态枚举

    定义 Alpha 触发器的生命周期状态。
    """

    ACTIVE = "active"
    """激活中：等待触发条件"""

    TRIGGERED = "triggered"
    """已触发：触发条件已满足，等待决策"""

    EXPIRED = "expired"
    """已过期：超过有效期"""

    CANCELLED = "cancelled"
    """已取消：手动取消"""

    PAUSED = "paused"
    """已暂停：暂时停止触发"""

    INVALIDATED = "invalidated"
    """已证伪：证伪条件已满足"""


class SignalStrength(Enum):
    """
    信号强度枚举

    定义 Alpha 信号的强度等级。
    """

    VERY_WEAK = "very_weak"
    """极弱信号：兼容旧版枚举"""

    WEAK = "weak"
    """弱信号：置信度 0-0.3"""

    MODERATE = "moderate"
    """中等信号：置信度 0.3-0.6"""

    STRONG = "strong"
    """强信号：置信度 0.6-0.8"""

    VERY_STRONG = "very_strong"
    """极强信号：置信度 0.8-1.0"""


class CandidateStatus(str, Enum):
    """
    候选状态枚举

    定义 Alpha 候选的生命周期状态。
    """

    WATCH = "WATCH"
    """观察中：初步筛选通过，需要进一步观察"""

    CANDIDATE = "CANDIDATE"
    """候选中：通过 Beta Gate 筛选，等待行动时机"""

    ACTIONABLE = "ACTIONABLE"
    """可操作：满足所有条件，可以执行"""

    EXECUTED = "EXECUTED"
    """已执行：已经执行交易"""

    CANCELLED = "CANCELLED"
    """已取消：手动取消"""


class InvalidationType(str, Enum):
    """
    证伪类型枚举

    定义 Alpha 信号证伪的不同类型。
    """

    THRESHOLD_CROSS = "threshold_cross"
    """阈值穿越：指标穿越阈值时证伪"""
    INDICATOR = "threshold_cross"
    """兼容旧命名：指标条件（等价于 THRESHOLD_CROSS）"""

    TIME_DECAY = "time_decay"
    """时间衰减：超过最大持仓时间"""

    REGIME_MISMATCH = "regime_mismatch"
    """Regime 不匹配：当前 Regime 与要求不符"""

    POLICY_CHANGE = "policy_change"
    """政策变化：Policy 档位变化导致证伪"""

    MANUAL_INVALIDATION = "manual_invalidation"
    """手动证伪：人工手动证伪"""


@dataclass(frozen=True)
class InvalidationCondition:
    """
    证伪条件

    定义 Alpha 信号的证伪规则，支持多种条件类型。

    Attributes:
        condition_type: 条件类型
        indicator_code: 指标代码（threshold_cross 类型使用）
        threshold_value: 阈值
        cross_direction: 穿越方向 ("above", "below")
        max_holding_days: 最大持仓天数（时间衰减类型）
        required_regime: 要求的 Regime（regime_mismatch 类型）
        time_window_hours: 时间窗口（小时）
        compare_with_prev: 是否与前值比较

    Example:
        >>> condition = InvalidationCondition(
        ...     condition_type="threshold_cross",
        ...     indicator_code="CN_PMI_MANUFACTURING",
        ...     threshold_value=50.0,
        ...     cross_direction="below"
        ... )
    """

    condition_type: Any
    indicator_code: Optional[str] = None
    threshold_value: Optional[float] = None
    cross_direction: Optional[str] = None
    max_holding_days: Optional[int] = None
    required_regime: Optional[str] = None
    time_window_hours: Optional[int] = None
    compare_with_prev: bool = False
    prev_diff_threshold: Optional[float] = None
    # Backward-compatible aliases
    threshold: Optional[float] = None
    direction: Optional[str] = None
    time_limit_hours: Optional[int] = None
    custom_condition: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        """Normalize legacy field names and enum values."""
        if isinstance(self.condition_type, str):
            object.__setattr__(self, "condition_type", InvalidationType(self.condition_type))
        elif not isinstance(self.condition_type, InvalidationType):
            object.__setattr__(self, "condition_type", InvalidationType(str(self.condition_type)))

        if self.threshold_value is None and self.threshold is not None:
            object.__setattr__(self, "threshold_value", self.threshold)
        if self.threshold is None and self.threshold_value is not None:
            object.__setattr__(self, "threshold", self.threshold_value)

        if self.cross_direction is None and self.direction is not None:
            object.__setattr__(self, "cross_direction", self.direction)
        if self.direction is None and self.cross_direction is not None:
            object.__setattr__(self, "direction", self.cross_direction)

        if self.time_window_hours is None and self.time_limit_hours is not None:
            object.__setattr__(self, "time_window_hours", self.time_limit_hours)
        if self.time_limit_hours is None and self.time_window_hours is not None:
            object.__setattr__(self, "time_limit_hours", self.time_window_hours)

        if self.custom_condition is None and self.required_regime is not None:
            object.__setattr__(self, "custom_condition", {"expected_regime": self.required_regime})
        if self.required_regime is None and self.custom_condition:
            expected = self.custom_condition.get("expected_regime")
            if expected:
                object.__setattr__(self, "required_regime", expected)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "condition_type": self.condition_type.value if isinstance(self.condition_type, InvalidationType) else self.condition_type,
            "indicator_code": self.indicator_code,
            "threshold_value": self.threshold_value,
            "cross_direction": self.cross_direction,
            "max_holding_days": self.max_holding_days,
            "required_regime": self.required_regime,
            "time_window_hours": self.time_window_hours,
            "compare_with_prev": self.compare_with_prev,
            "prev_diff_threshold": self.prev_diff_threshold,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InvalidationCondition":
        """从字典创建"""
        return cls(**data)


@dataclass
class AlphaTrigger:
    """
    Alpha 触发器实体

    定义一个完整的 Alpha 触发器，包括触发条件、证伪条件和信号强度。

    Attributes:
        trigger_id: 触发器唯一标识
        trigger_type: 触发器类型
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向 ("LONG", "SHORT", "NEUTRAL")
        trigger_condition: 触发条件（灵活的 JSON 结构）
        invalidation_conditions: 证伪条件列表
        strength: 信号强度
        confidence: 置信度（0-1）
        created_at: 创建时间
        expires_at: 过期时间（可选）
        status: 触发器状态
        triggered_at: 触发时间
        invalidated_at: 证伪时间
        source_signal_id: 源信号 ID（可选）
        related_regime: 相关 Regime（可选）
        related_policy_level: 相关 Policy 档位（可选）
        thesis: 投资论点
        evidence_refs: 证据引用列表

    Example:
        >>> trigger = AlphaTrigger(
        ...     trigger_id="trigger_001",
        ...     trigger_type=TriggerType.MOMENTUM_SIGNAL,
        ...     asset_code="000001.SH",
        ...     asset_class="a_share金融",
        ...     direction="LONG",
        ...     trigger_condition={"momentum_pct": 0.05},
        ...     invalidation_conditions=[...],
        ...     strength=SignalStrength.STRONG,
        ...     confidence=0.75,
        ...     created_at=datetime.now(),
        ...     thesis="PMI 回升，经济复苏预期增强"
        ... )
    """

    trigger_id: str
    trigger_type: TriggerType
    asset_code: str
    asset_class: str
    direction: str
    trigger_condition: Dict[str, Any]
    invalidation_conditions: List[InvalidationCondition]
    strength: SignalStrength
    confidence: float
    created_at: datetime
    expires_at: Optional[datetime] = None
    status: TriggerStatus = TriggerStatus.ACTIVE
    triggered_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    source_signal_id: Optional[str] = None
    related_regime: Optional[str] = None
    related_policy_level: Optional[int] = None
    thesis: str = ""
    evidence_refs: List[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        """是否激活"""
        return self.status == TriggerStatus.ACTIVE

    @property
    def is_triggered(self) -> bool:
        """是否已触发"""
        return self.status == TriggerStatus.TRIGGERED

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        if self.expires_at is None:
            return False
        now = datetime.now(self.expires_at.tzinfo) if self.expires_at.tzinfo else datetime.now()
        return now > self.expires_at

    @property
    def is_invalidated(self) -> bool:
        """是否已证伪"""
        return self.status == TriggerStatus.INVALIDATED

    @property
    def days_since_creation(self) -> int:
        """创建后天数"""
        return (datetime.now() - self.created_at).days

    @property
    def days_since_trigger(self) -> Optional[int]:
        """触发后天数"""
        if self.triggered_at is None:
            return None
        return (datetime.now() - self.triggered_at).days

    @property
    def remaining_days(self) -> Optional[int]:
        """剩余有效天数"""
        if self.expires_at is None:
            return None
        delta = self.expires_at - datetime.now()
        return max(0, delta.days)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "trigger_id": self.trigger_id,
            "trigger_type": self.trigger_type.value,
            "asset_code": self.asset_code,
            "asset_class": self.asset_class,
            "direction": self.direction,
            "trigger_condition": self.trigger_condition,
            "invalidation_conditions": [c.to_dict() for c in self.invalidation_conditions],
            "strength": self.strength.value,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status.value,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "invalidated_at": self.invalidated_at.isoformat() if self.invalidated_at else None,
            "source_signal_id": self.source_signal_id,
            "related_regime": self.related_regime,
            "related_policy_level": self.related_policy_level,
            "thesis": self.thesis,
            "evidence_refs": self.evidence_refs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlphaTrigger":
        """从字典创建"""
        return cls(
            trigger_id=data["trigger_id"],
            trigger_type=TriggerType(data["trigger_type"]),
            asset_code=data["asset_code"],
            asset_class=data["asset_class"],
            direction=data["direction"],
            trigger_condition=data["trigger_condition"],
            invalidation_conditions=[
                InvalidationCondition.from_dict(c) for c in data.get("invalidation_conditions", [])
            ],
            strength=SignalStrength(data["strength"]),
            confidence=data["confidence"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            status=TriggerStatus(data.get("status", "active")),
            triggered_at=datetime.fromisoformat(data["triggered_at"]) if data.get("triggered_at") else None,
            invalidated_at=datetime.fromisoformat(data["invalidated_at"]) if data.get("invalidated_at") else None,
            source_signal_id=data.get("source_signal_id"),
            related_regime=data.get("related_regime"),
            related_policy_level=data.get("related_policy_level"),
            thesis=data.get("thesis", ""),
            evidence_refs=data.get("evidence_refs", []),
        )


@dataclass(frozen=True)
class TriggerEvent:
    """
    触发事件

    记录触发器状态变化的事件。

    Attributes:
        event_id: 事件唯一标识
        trigger_id: 触发器 ID
        event_type: 事件类型
        occurred_at: 发生时间
        trigger_value: 触发时的指标值
        indicator_value: 相关指标值
        reason: 原因描述
        current_regime: 当前 Regime
        policy_level: 当前 Policy 档位
        metadata: 额外元数据

    Example:
        >>> event = TriggerEvent(
        ...     event_id="event_001",
        ...     trigger_id="trigger_001",
        ...     event_type="triggered",
        ...     occurred_at=datetime.now(),
        ...     trigger_value=0.75,
        ...     reason="PMI 超预期回升"
        ... )
    """

    event_id: str
    trigger_id: str
    event_type: str
    occurred_at: datetime
    trigger_value: Optional[float] = None
    indicator_value: Optional[float] = None
    reason: str = ""
    current_regime: Optional[str] = None
    policy_level: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_id": self.event_id,
            "trigger_id": self.trigger_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "trigger_value": self.trigger_value,
            "indicator_value": self.indicator_value,
            "reason": self.reason,
            "current_regime": self.current_regime,
            "policy_level": self.policy_level,
            "metadata": self.metadata,
        }


@dataclass
class AlphaCandidate:
    """
    Alpha 候选

    通过 Beta Gate 和 Alpha Trigger 筛选后的可行动候选。

    Attributes:
        candidate_id: 候选唯一标识
        trigger_id: 源触发器 ID
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向
        strength: 信号强度
        confidence: 置信度
        thesis: 投资论点
        invalidation: 证伪条件描述
        time_window_start: 时间窗口开始
        time_window_end: 时间窗口结束
        expected_asymmetry: 预期不对称性 ("HIGH", "MED", "LOW")
        status: 状态 ("WATCH", "CANDIDATE", "ACTIONABLE", "DROPPED")
        created_at: 创建时间
        updated_at: 更新时间
        audit_trail: 审计轨迹
        last_decision_request_id: 最后决策请求 ID（可选）
        last_execution_status: 最后执行状态（可选）

    Example:
        >>> candidate = AlphaCandidate(
        ...     candidate_id="cand_001",
        ...     trigger_id="trigger_001",
        ...     asset_code="000001.SH",
        ...     asset_class="a_share金融",
        ...     direction="LONG",
        ...     strength=SignalStrength.STRONG,
        ...     confidence=0.75,
        ...     thesis="PMI 回升，经济复苏预期增强",
        ...     invalidation="PMI 跌破 50 且连续 2 月低于前值",
        ...     expected_asymmetry="HIGH"
        ... )
    """

    candidate_id: str
    trigger_id: str
    asset_code: str
    asset_class: str
    direction: str
    strength: SignalStrength
    confidence: float
    thesis: str
    invalidation: str = ""
    time_window_start: date = field(default_factory=date.today)
    time_window_end: date = field(default_factory=lambda: date.today() + timedelta(days=30))
    expected_asymmetry: str = "MED"
    status: Any = CandidateStatus.CANDIDATE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    audit_trail: List[str] = field(default_factory=list)
    # Backward-compatible fields
    entry_zone: Optional[Dict[str, Any]] = None
    exit_zone: Optional[Dict[str, Any]] = None
    time_horizon: Optional[int] = None
    expected_return: Optional[float] = None
    risk_level: Optional[str] = None
    status_changed_at: Optional[datetime] = None
    promoted_to_signal_at: Optional[datetime] = None
    # 新增字段：首页主流程闭环改造
    last_decision_request_id: Optional[str] = None
    last_execution_status: Optional[str] = None

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            try:
                self.status = CandidateStatus(self.status)
            except ValueError:
                pass
        if self.time_horizon is not None:
            self.time_window_end = self.time_window_start + timedelta(days=self.time_horizon)

    @property
    def is_actionable(self) -> bool:
        """是否可行动"""
        return self.status == CandidateStatus.ACTIONABLE or self.status == "ACTIONABLE"

    @property
    def is_watch(self) -> bool:
        """是否在观察列表"""
        return self.status == CandidateStatus.WATCH or self.status == "WATCH"

    @property
    def is_dropped(self) -> bool:
        """是否已放弃"""
        return self.status == "DROPPED"

    @property
    def is_executed(self) -> bool:
        """是否已执行"""
        return self.status == CandidateStatus.EXECUTED or self.status == "EXECUTED"

    @property
    def has_decision_request(self) -> bool:
        """是否有关联的决策请求"""
        return self.last_decision_request_id is not None and self.last_decision_request_id != ""

    @property
    def days_remaining(self) -> int:
        """剩余天数"""
        return (self.time_window_end - date.today()).days

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        return date.today() > self.time_window_end

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "candidate_id": self.candidate_id,
            "trigger_id": self.trigger_id,
            "asset_code": self.asset_code,
            "asset_class": self.asset_class,
            "direction": self.direction,
            "strength": self.strength.value,
            "confidence": self.confidence,
            "thesis": self.thesis,
            "invalidation": self.invalidation,
            "time_window_start": self.time_window_start.isoformat(),
            "time_window_end": self.time_window_end.isoformat(),
            "expected_asymmetry": self.expected_asymmetry,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "audit_trail": self.audit_trail,
            "entry_zone": self.entry_zone,
            "exit_zone": self.exit_zone,
            "time_horizon": self.time_horizon,
            "expected_return": self.expected_return,
            "risk_level": self.risk_level,
            "status_changed_at": self.status_changed_at.isoformat() if self.status_changed_at else None,
            "promoted_to_signal_at": self.promoted_to_signal_at.isoformat() if self.promoted_to_signal_at else None,
            # 新增字段
            "last_decision_request_id": self.last_decision_request_id,
            "last_execution_status": self.last_execution_status,
            "is_executed": self.is_executed,
            "has_decision_request": self.has_decision_request,
        }


@dataclass(frozen=True)
class TriggerConfig:
    """
    触发器配置

    定义 Alpha 触发器的全局配置参数。

    Attributes:
        weak_threshold: 弱信号阈值
        moderate_threshold: 中等信号阈值
        strong_threshold: 强信号阈值
        min_interval_hours: 同一资产最小触发间隔
        default_expiry_days: 默认过期天数
        invalidation_check_hours: 证伪检查间隔
        enable_auto_trigger: 是否启用自动触发
        max_active_triggers: 最大激活触发器数量

    Example:
        >>> config = TriggerConfig(
        ...     weak_threshold=0.3,
        ...     moderate_threshold=0.6,
        ...     strong_threshold=0.8
        ... )
    """

    weak_threshold: float = 0.2
    moderate_threshold: float = 0.5
    strong_threshold: float = 0.8
    min_interval_hours: int = 24
    default_expiry_days: int = 90
    invalidation_check_hours: int = 6
    enable_auto_trigger: bool = True
    max_active_triggers: int = 100

    @property
    def strength_thresholds(self) -> Dict[SignalStrength, float]:
        """Backward-compatible threshold mapping."""
        return {
            SignalStrength.VERY_WEAK: 0.0,
            SignalStrength.WEAK: self.weak_threshold,
            SignalStrength.MODERATE: self.moderate_threshold,
            SignalStrength.STRONG: (self.strong_threshold + self.moderate_threshold) / 2,
            SignalStrength.VERY_STRONG: self.strong_threshold,
        }

    def get_strength(self, confidence: float) -> SignalStrength:
        """
        根据置信度获取信号强度

        Args:
            confidence: 置信度

        Returns:
            信号强度
        """
        if confidence >= self.strong_threshold:
            return SignalStrength.VERY_STRONG
        elif confidence >= self.strength_thresholds[SignalStrength.STRONG]:
            return SignalStrength.STRONG
        elif confidence >= self.moderate_threshold:
            return SignalStrength.MODERATE
        elif confidence >= self.weak_threshold:
            return SignalStrength.WEAK
        else:
            return SignalStrength.VERY_WEAK

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "weak_threshold": self.weak_threshold,
            "moderate_threshold": self.moderate_threshold,
            "strong_threshold": self.strong_threshold,
            "min_interval_hours": self.min_interval_hours,
            "default_expiry_days": self.default_expiry_days,
            "invalidation_check_hours": self.invalidation_check_hours,
            "enable_auto_trigger": self.enable_auto_trigger,
            "max_active_triggers": self.max_active_triggers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriggerConfig":
        """从字典创建"""
        return cls(
            weak_threshold=data.get("weak_threshold", 0.3),
            moderate_threshold=data.get("moderate_threshold", 0.6),
            strong_threshold=data.get("strong_threshold", 0.8),
            min_interval_hours=data.get("min_interval_hours", 24),
            default_expiry_days=data.get("default_expiry_days", 90),
            invalidation_check_hours=data.get("invalidation_check_hours", 6),
            enable_auto_trigger=data.get("enable_auto_trigger", True),
            max_active_triggers=data.get("max_active_triggers", 100),
        )


# ========== 便捷工厂函数 ==========


def create_invalidations(
    threshold_invalidations: Optional[List[Dict[str, Any]]] = None,
    time_decay_days: Optional[int] = None,
    regime_mismatch: Optional[str] = None,
) -> List[InvalidationCondition]:
    """
    创建证伪条件列表的便捷函数

    Args:
        threshold_invalidations: 阈值穿越条件列表
        time_decay_days: 时间衰减天数
        regime_mismatch: 不匹配的 Regime

    Returns:
        证伪条件列表

    Example:
        >>> conditions = create_invalidations(
        ...     threshold_invalidations=[{
        ...         "indicator_code": "CN_PMI_MANUFACTURING",
        ...         "threshold_value": 50.0,
        ...         "cross_direction": "below"
        ...     }],
        ...     time_decay_days=30
        ... )
    """
    conditions: List[InvalidationCondition] = []

    if threshold_invalidations:
        for inv in threshold_invalidations:
            conditions.append(
                InvalidationCondition(
                    condition_type="threshold_cross",
                    indicator_code=inv.get("indicator_code"),
                    threshold_value=inv.get("threshold_value"),
                    cross_direction=inv.get("cross_direction"),
                )
            )

    if time_decay_days:
        conditions.append(
            InvalidationCondition(
                condition_type="time_decay",
                max_holding_days=time_decay_days,
            )
        )

    if regime_mismatch:
        conditions.append(
            InvalidationCondition(
                condition_type="regime_mismatch",
                required_regime=regime_mismatch,
            )
        )

    return conditions


def calculate_strength(confidence: float, config: Optional[TriggerConfig] = None) -> SignalStrength:
    """
    计算信号强度的便捷函数

    Args:
        confidence: 置信度
        config: 触发器配置（可选）

    Returns:
        信号强度
    """
    if config is None:
        config = TriggerConfig()
    return config.get_strength(confidence)
