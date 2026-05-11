"""
Decision Rhythm Domain Entities

决策频率约束和配额管理的核心实体定义。
实现稀疏决策的工程化约束。

仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4


class ValuationMethod(Enum):
    """
    估值方法枚举

    定义支持的估值计算方法。
    """

    DCF = "DCF"
    """现金流折现法"""

    PE_BAND = "PE_BAND"
    """PE 通道法"""

    PB_BAND = "PB_BAND"
    """PB 通道法"""

    PEG = "PEG"
    """PEG 估值法"""

    DIVIDEND = "DIVIDEND"
    """股息折现法"""

    COMPOSITE = "COMPOSITE"
    """综合估值法"""

    FALLBACK = "FALLBACK"
    """当前价兜底估值"""


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


class TransitionPlanStatus(Enum):
    """交易计划状态枚举。"""

    DRAFT = "DRAFT"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


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


class DecisionPriority(Enum):
    """
    决策优先级枚举

    定义决策请求的优先级等级。
    """

    CRITICAL = "critical"
    """紧急：如强制平仓、风控触发"""

    HIGH = "high"
    """高：如强信号触发"""

    MEDIUM = "medium"
    """中：如正常调仓"""

    LOW = "low"
    """低：如优化建议"""

    INFO = "info"
    """信息：不执行，仅记录"""


class DecisionStatus(Enum):
    """决策请求状态枚举（向后兼容）"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExecutionTarget(Enum):
    """
    执行目标枚举

    定义决策请求的执行目标类型。
    """

    NONE = "NONE"
    """无执行：仅决策，不执行"""

    SIMULATED = "SIMULATED"
    """模拟盘执行：在模拟账户中执行"""

    ACCOUNT = "ACCOUNT"
    """实盘执行：在真实账户中执行"""


class ExecutionStatus(Enum):
    """
    执行状态枚举

    定义决策请求的执行状态。
    """

    PENDING = "PENDING"
    """待执行：等待执行"""

    EXECUTED = "EXECUTED"
    """已执行：执行完成"""

    FAILED = "FAILED"
    """执行失败：执行过程中出错"""

    CANCELLED = "CANCELLED"
    """已取消：执行被取消"""


class QuotaPeriod(Enum):
    """
    配额周期枚举

    定义配额的计算周期。
    """

    DAILY = "daily"
    """日配额"""

    WEEKLY = "weekly"
    """周配额"""

    MONTHLY = "monthly"
    """月配额"""


class QuotaStatus(Enum):
    """
    配额状态枚举

    定义配额的使用状态。
    """

    AVAILABLE = "available"
    """可用：有剩余配额"""

    EXHAUSTED = "exhausted"
    """耗尽：配额已用完"""

    RESET_PENDING = "reset_pending"
    """待重置：等待周期重置"""

    OVER_LIMIT = "over_limit"
    """超限：超过配额限制"""


@dataclass(frozen=True)
class DecisionQuota:
    """
    决策配额

    定义指定周期内的决策配额限制。

    Attributes:
        period: 配额周期
        max_decisions: 最大决策次数
        max_execution_count: 最大执行次数
        used_decisions: 已使用决策次数
        used_executions: 已使用执行次数
        period_start: 周期开始时间
        period_end: 周期结束时间
        quota_id: 配额唯一标识
        created_at: 创建时间
        updated_at: 更新时间

    Example:
        >>> quota = DecisionQuota(
        ...     period=QuotaPeriod.WEEKLY,
        ...     max_decisions=5,
        ...     max_execution_count=3,
        ...     used_decisions=0,
        ...     used_executions=0
        ... )
        >>> print(f"剩余决策: {quota.remaining_decisions}")
    """

    period: QuotaPeriod
    max_decisions: int
    max_execution_count: int = 0
    used_decisions: int = 0
    used_executions: int = 0
    period_start: datetime | None = None
    period_end: datetime | None = None
    quota_id: str | None = None
    account_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Backward compatibility fields
    max_executions: int | None = None
    is_active: bool = True

    def __post_init__(self):
        if self.max_execution_count == 0 and self.max_executions is not None:
            object.__setattr__(self, "max_execution_count", self.max_executions)

    @property
    def remaining_decisions(self) -> int:
        """剩余决策次数"""
        return max(0, self.max_decisions - self.used_decisions)

    @property
    def remaining_executions(self) -> int:
        """剩余执行次数"""
        return max(0, self.max_execution_count - self.used_executions)

    @property
    def is_quota_exceeded(self) -> bool:
        """是否超配额"""
        return self.remaining_decisions <= 0 or self.remaining_executions <= 0

    @property
    def is_decision_exceeded(self) -> bool:
        """是否决策次数超限"""
        return self.remaining_decisions <= 0

    @property
    def is_execution_exceeded(self) -> bool:
        """是否执行次数超限"""
        return self.remaining_executions <= 0

    @property
    def utilization_rate(self) -> float:
        """配额使用率"""
        if self.max_decisions == 0:
            return 1.0
        return self.used_decisions / self.max_decisions

    @property
    def status(self) -> QuotaStatus:
        """配额状态"""
        if self.is_quota_exceeded:
            return QuotaStatus.EXHAUSTED
        if self.utilization_rate >= 0.9:
            return QuotaStatus.OVER_LIMIT
        return QuotaStatus.AVAILABLE

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        if self.period_end is None:
            return False
        return datetime.now(UTC) > self.period_end

    @property
    def days_remaining(self) -> int | None:
        """剩余天数"""
        if self.period_end is None:
            return None
        delta = self.period_end - datetime.now(UTC)
        return max(0, delta.days)

    def consume_decision(self, count: int = 1) -> "DecisionQuota":
        """消耗决策配额，返回新的配额对象"""
        return DecisionQuota(
            period=self.period,
            max_decisions=self.max_decisions,
            max_execution_count=self.max_execution_count,
            used_decisions=self.used_decisions + count,
            used_executions=self.used_executions,
            period_start=self.period_start,
            period_end=self.period_end,
            quota_id=self.quota_id,
            account_id=self.account_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def consume_execution(self, count: int = 1) -> "DecisionQuota":
        """消耗执行配额，返回新的配额对象"""
        return DecisionQuota(
            period=self.period,
            max_decisions=self.max_decisions,
            max_execution_count=self.max_execution_count,
            used_decisions=self.used_decisions,
            used_executions=self.used_executions + count,
            period_start=self.period_start,
            period_end=self.period_end,
            quota_id=self.quota_id,
            account_id=self.account_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def reset(self) -> "DecisionQuota":
        """重置配额，返回新的配额对象"""
        return DecisionQuota(
            period=self.period,
            max_decisions=self.max_decisions,
            max_execution_count=self.max_execution_count,
            used_decisions=0,
            used_executions=0,
            period_start=datetime.now(UTC),
            period_end=self._calculate_period_end(),
            quota_id=self.quota_id,
            account_id=self.account_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def _calculate_period_end(self, now: datetime | None = None) -> datetime | None:
        """计算周期结束时间

        Args:
            now: 可选的时间戳，用于避免竞态条件
        """
        if now is None:
            now = datetime.now(UTC)
        if self.period == QuotaPeriod.DAILY:
            return now.replace(hour=23, minute=59, second=59)
        elif self.period == QuotaPeriod.WEEKLY:
            # 下周一
            days_ahead = 7 - now.weekday()
            if days_ahead == 0:
                days_ahead = 7
            return now + timedelta(days=days_ahead)
        elif self.period == QuotaPeriod.MONTHLY:
            # 下月第一天
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)
            return next_month
        return None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "quota_id": self.quota_id,
            "period": self.period.value,
            "max_decisions": self.max_decisions,
            "max_execution_count": self.max_execution_count,
            "used_decisions": self.used_decisions,
            "used_executions": self.used_executions,
            "is_active": self.is_active,
            "remaining_decisions": self.remaining_decisions,
            "remaining_executions": self.remaining_executions,
            "utilization_rate": self.utilization_rate,
            "status": self.status.value,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "is_expired": self.is_expired,
            "days_remaining": self.days_remaining,
        }


@dataclass(frozen=True)
class CooldownPeriod:
    """
    冷却期配置

    定义决策和执行之间的冷却时间约束。

    Attributes:
        asset_code: 资产代码
        last_decision_at: 最后决策时间
        last_execution_at: 最后执行时间
        min_decision_interval_hours: 最小决策间隔（小时）
        min_execution_interval_hours: 最小执行间隔（小时）
        same_asset_cooldown_hours: 同资产冷却期（小时）
        cooldown_id: 冷却配置唯一标识

    Example:
        >>> cooldown = CooldownPeriod(
        ...     asset_code="000001.SH",
        ...     min_decision_interval_hours=24,
        ...     min_execution_interval_hours=48
        ... )
        >>> if cooldown.is_decision_ready:
        ...     print("可以进行决策")
    """

    asset_code: str
    last_decision_at: datetime | None = None
    last_execution_at: datetime | None = None
    min_decision_interval_hours: int = 24
    min_execution_interval_hours: int = 48
    same_asset_cooldown_hours: int = 72
    cooldown_id: str | None = None

    @property
    def is_decision_ready(self) -> bool:
        """是否可以决策"""
        if self.last_decision_at is None:
            return True

        elapsed = (datetime.now(UTC) - self.last_decision_at).total_seconds() / 3600
        return elapsed >= self.min_decision_interval_hours

    @property
    def is_execution_ready(self) -> bool:
        """是否可以执行"""
        if self.last_execution_at is None:
            return True

        elapsed = (datetime.now(UTC) - self.last_execution_at).total_seconds() / 3600
        return elapsed >= self.min_execution_interval_hours

    @property
    def decision_ready_in_hours(self) -> float:
        """距离可决策的小时数"""
        if self.last_decision_at is None:
            return 0.0

        elapsed = (datetime.now(UTC) - self.last_decision_at).total_seconds() / 3600
        remaining = self.min_decision_interval_hours - elapsed
        return max(0.0, remaining)

    @property
    def execution_ready_in_hours(self) -> float:
        """距离可执行的小时数"""
        if self.last_execution_at is None:
            return 0.0

        elapsed = (datetime.now(UTC) - self.last_execution_at).total_seconds() / 3600
        remaining = self.min_execution_interval_hours - elapsed
        return max(0.0, remaining)

    def update_decision_time(self) -> "CooldownPeriod":
        """更新决策时间，返回新的冷却期对象"""
        return CooldownPeriod(
            asset_code=self.asset_code,
            last_decision_at=datetime.now(UTC),
            last_execution_at=self.last_execution_at,
            min_decision_interval_hours=self.min_decision_interval_hours,
            min_execution_interval_hours=self.min_execution_interval_hours,
            same_asset_cooldown_hours=self.same_asset_cooldown_hours,
            cooldown_id=self.cooldown_id,
        )

    def update_execution_time(self) -> "CooldownPeriod":
        """更新执行时间，返回新的冷却期对象"""
        return CooldownPeriod(
            asset_code=self.asset_code,
            last_decision_at=self.last_decision_at,
            last_execution_at=datetime.now(UTC),
            min_decision_interval_hours=self.min_decision_interval_hours,
            min_execution_interval_hours=self.min_execution_interval_hours,
            same_asset_cooldown_hours=self.same_asset_cooldown_hours,
            cooldown_id=self.cooldown_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "cooldown_id": self.cooldown_id,
            "asset_code": self.asset_code,
            "last_decision_at": self.last_decision_at.isoformat() if self.last_decision_at else None,
            "last_execution_at": self.last_execution_at.isoformat() if self.last_execution_at else None,
            "min_decision_interval_hours": self.min_decision_interval_hours,
            "min_execution_interval_hours": self.min_execution_interval_hours,
            "same_asset_cooldown_hours": self.same_asset_cooldown_hours,
            "is_decision_ready": self.is_decision_ready,
            "is_execution_ready": self.is_execution_ready,
            "decision_ready_in_hours": self.decision_ready_in_hours,
            "execution_ready_in_hours": self.execution_ready_in_hours,
        }


@dataclass(frozen=True)
class DecisionRequest:
    """
    决策请求

    表示一个决策请求。

    Attributes:
        request_id: 请求唯一标识
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向 ("BUY", "SELL")
        priority: 优先级
        trigger_id: 触发器 ID（可选）
        reason: 原因描述
        expected_confidence: 预期置信度
        quantity: 数量（可选）
        notional: 名义金额（可选）
        requested_at: 请求时间
        expires_at: 过期时间（可选）
        candidate_id: 关联的候选 ID（可选）
        execution_target: 执行目标
        execution_status: 执行状态
        executed_at: 执行时间（可选）
        execution_ref: 执行引用（可选）

    Example:
        >>> request = DecisionRequest(
        ...     request_id="req_001",
        ...     asset_code="000001.SH",
        ...     direction="BUY",
        ...     priority=DecisionPriority.HIGH,
        ...     reason="强 Alpha 信号"
        ... )
    """

    request_id: str
    asset_code: str
    asset_class: str
    direction: str
    priority: DecisionPriority
    trigger_id: str | None = None
    reason: str = ""
    expected_confidence: float = 0.0
    quota_period: QuotaPeriod | None = None
    quantity: int | None = None
    notional: float | None = None
    status: DecisionStatus = DecisionStatus.PENDING
    created_at: datetime | None = None
    requested_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None
    # 新增字段：首页主流程闭环改造
    candidate_id: str | None = None
    execution_target: ExecutionTarget = ExecutionTarget.NONE
    execution_status: ExecutionStatus = ExecutionStatus.PENDING
    executed_at: datetime | None = None
    execution_ref: dict[str, Any] | None = None

    @property
    def is_buy(self) -> bool:
        """是否买入"""
        return self.direction.upper() == "BUY"

    @property
    def is_sell(self) -> bool:
        """是否卖出"""
        return self.direction.upper() == "SELL"

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    @property
    def is_executed(self) -> bool:
        """是否已执行"""
        return self.execution_status == ExecutionStatus.EXECUTED

    @property
    def is_execution_pending(self) -> bool:
        """是否待执行"""
        return self.execution_status == ExecutionStatus.PENDING

    @property
    def has_execution_target(self) -> bool:
        """是否有执行目标"""
        return self.execution_target != ExecutionTarget.NONE

    def __post_init__(self):
        if self.created_at is not None:
            object.__setattr__(self, "requested_at", self.created_at)

    @property
    def priority_level(self) -> int:
        """优先级等级（数字越大优先级越高）"""
        priority_map = {
            DecisionPriority.INFO: 0,
            DecisionPriority.LOW: 1,
            DecisionPriority.MEDIUM: 2,
            DecisionPriority.HIGH: 3,
            DecisionPriority.CRITICAL: 4,
        }
        return priority_map.get(self.priority, 0)

    def validate_execution_consistency(self) -> bool:
        """
        验证执行状态一致性

        Returns:
            True 如果状态一致，False 否则

        规则：
        - execution_status='EXECUTED' 时 executed_at 必填
        - execution_target='NONE' 时 execution_ref 应为空
        """
        # EXECUTED 状态必须有 executed_at
        if self.execution_status == ExecutionStatus.EXECUTED and self.executed_at is None:
            return False
        # NONE 目标不应该有 execution_ref
        if self.execution_target == ExecutionTarget.NONE and self.execution_ref is not None:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "request_id": self.request_id,
            "asset_code": self.asset_code,
            "asset_class": self.asset_class,
            "direction": self.direction,
            "priority": self.priority.value,
            "priority_level": self.priority_level,
            "trigger_id": self.trigger_id,
            "reason": self.reason,
            "expected_confidence": self.expected_confidence,
            "quota_period": self.quota_period.value if self.quota_period else None,
            "quantity": self.quantity,
            "notional": self.notional,
            "status": self.status.value,
            "requested_at": self.requested_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_expired": self.is_expired,
            # 新增字段
            "candidate_id": self.candidate_id,
            "execution_target": self.execution_target.value,
            "execution_status": self.execution_status.value,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "execution_ref": self.execution_ref,
            "is_executed": self.is_executed,
            "is_execution_pending": self.is_execution_pending,
            "has_execution_target": self.has_execution_target,
        }


@dataclass(frozen=True)
class DecisionResponse:
    """
    决策响应

    表示对决策请求的响应。

    Attributes:
        request_id: 请求 ID
        approved: 是否批准
        approval_reason: 批准原因
        scheduled_at: 调度时间
        estimated_execution_at: 预计执行时间
        rejection_reason: 拒绝原因
        wait_until: 等待直到
        alternative_suggestions: 替代建议列表
        quota_status: 配额状态
        cooldown_status: 冷却状态
        responded_at: 响应时间

    Example:
        >>> response = DecisionResponse(
        ...     request_id="req_001",
        ...     approved=True,
        ...     approval_reason="配额充足，冷却期已过"
        ... )
    """

    request_id: str
    approved: bool
    approval_reason: str
    scheduled_at: datetime | None = None
    estimated_execution_at: datetime | None = None
    rejection_reason: str | None = None
    wait_until: datetime | None = None
    alternative_suggestions: list[str] = field(default_factory=list)
    quota_status: str | None = None
    cooldown_status: str | None = None
    responded_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "request_id": self.request_id,
            "approved": self.approved,
            "approval_reason": self.approval_reason,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "estimated_execution_at": self.estimated_execution_at.isoformat() if self.estimated_execution_at else None,
            "rejection_reason": self.rejection_reason,
            "wait_until": self.wait_until.isoformat() if self.wait_until else None,
            "alternative_suggestions": self.alternative_suggestions,
            "quota_status": self.quota_status,
            "cooldown_status": self.cooldown_status,
            "responded_at": self.responded_at.isoformat(),
        }


@dataclass(frozen=True)
class RhythmConfig:
    """
    决策节奏配置

    定义决策节奏的全局配置。

    Attributes:
        daily_quota: 日配额
        weekly_quota: 周配额
        monthly_quota: 月配额
        default_cooldown: 默认冷却配置
        priority_weights: 优先级权重
        daily_reset_hour: 日重置小时
        weekly_reset_day: 周重置星期（0=Monday）
        monthly_reset_day: 月重置日期
        enable_cooldown: 是否启用冷却
        enable_quota: 是否启用配额

    Example:
        >>> config = RhythmConfig(
        ...     daily_quota=DecisionQuota(QuotaPeriod.DAILY, 10, 5),
        ...     weekly_quota=DecisionQuota(QuotaPeriod.WEEKLY, 30, 15),
        ...     monthly_quota=DecisionQuota(QuotaPeriod.MONTHLY, 100, 50)
        ... )
    """

    daily_quota: DecisionQuota
    weekly_quota: DecisionQuota
    monthly_quota: DecisionQuota
    default_cooldown: CooldownPeriod
    priority_weights: dict[DecisionPriority, float] = field(default_factory=lambda: {
        DecisionPriority.CRITICAL: 1.0,
        DecisionPriority.HIGH: 0.8,
        DecisionPriority.MEDIUM: 0.5,
        DecisionPriority.LOW: 0.2,
        DecisionPriority.INFO: 0.0,
    })
    daily_reset_hour: int = 8
    weekly_reset_day: int = 0
    monthly_reset_day: int = 1
    enable_cooldown: bool = True
    enable_quota: bool = True

    def get_quota(self, period: QuotaPeriod) -> DecisionQuota:
        """获取指定周期的配额"""
        if period == QuotaPeriod.DAILY:
            return self.daily_quota
        elif period == QuotaPeriod.WEEKLY:
            return self.weekly_quota
        elif period == QuotaPeriod.MONTHLY:
            return self.monthly_quota
        raise ValueError(f"Unknown quota period: {period}")

    def get_priority_weight(self, priority: DecisionPriority) -> float:
        """获取优先级权重"""
        return self.priority_weights.get(priority, 0.0)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "daily_quota": self.daily_quota.to_dict(),
            "weekly_quota": self.weekly_quota.to_dict(),
            "monthly_quota": self.monthly_quota.to_dict(),
            "default_cooldown": self.default_cooldown.to_dict(),
            "priority_weights": {k.value: v for k, v in self.priority_weights.items()},
            "daily_reset_hour": self.daily_reset_hour,
            "weekly_reset_day": self.weekly_reset_day,
            "monthly_reset_day": self.monthly_reset_day,
            "enable_cooldown": self.enable_cooldown,
            "enable_quota": self.enable_quota,
        }


# ========== 便捷工厂函数 ==========


def create_quota(
    period: QuotaPeriod,
    max_decisions: int,
    max_executions: int,
) -> DecisionQuota:
    """
    创建决策配额的便捷函数

    Args:
        period: 配额周期
        max_decisions: 最大决策次数
        max_executions: 最大执行次数

    Returns:
        DecisionQuota 实例
    """
    from uuid import uuid4

    now = datetime.now(UTC)
    quota = DecisionQuota(
        period=period,
        max_decisions=max_decisions,
        max_execution_count=max_executions,
        used_decisions=0,
        used_executions=0,
        period_start=now,
        quota_id=str(uuid4()),
        created_at=now,
    )
    # 计算周期结束时间 - 使用同一时间戳避免竞态条件
    period_end = quota._calculate_period_end(now)
    return DecisionQuota(
        period=quota.period,
        max_decisions=quota.max_decisions,
        max_execution_count=quota.max_execution_count,
        used_decisions=quota.used_decisions,
        used_executions=quota.used_executions,
        period_start=quota.period_start,
        period_end=period_end,
        quota_id=quota.quota_id,
        created_at=quota.created_at,
    )


def create_cooldown(
    asset_code: str,
    min_decision_interval_hours: int = 24,
    min_execution_interval_hours: int = 48,
) -> CooldownPeriod:
    """
    创建冷却期的便捷函数

    Args:
        asset_code: 资产代码
        min_decision_interval_hours: 最小决策间隔
        min_execution_interval_hours: 最小执行间隔

    Returns:
        CooldownPeriod 实例
    """
    from uuid import uuid4

    return CooldownPeriod(
        asset_code=asset_code,
        cooldown_id=str(uuid4()),
        min_decision_interval_hours=min_decision_interval_hours,
        min_execution_interval_hours=min_execution_interval_hours,
    )


def create_request(
    asset_code: str,
    asset_class: str,
    direction: str,
    priority: DecisionPriority,
    reason: str = "",
    **kwargs,
) -> DecisionRequest:
    """
    创建决策请求的便捷函数

    Args:
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向
        priority: 优先级
        reason: 原因
        **kwargs: 其他参数

    Returns:
        DecisionRequest 实例
    """
    from uuid import uuid4

    return DecisionRequest(
        request_id=str(uuid4()),
        asset_code=asset_code,
        asset_class=asset_class,
        direction=direction,
        priority=priority,
        reason=reason,
        **kwargs,
    )


def get_default_rhythm_config() -> RhythmConfig:
    """
    获取默认的决策节奏配置

    Returns:
        RhythmConfig 实例
    """
    return RhythmConfig(
        daily_quota=create_quota(QuotaPeriod.DAILY, 5, 3),
        weekly_quota=create_quota(QuotaPeriod.WEEKLY, 20, 10),
        monthly_quota=create_quota(QuotaPeriod.MONTHLY, 80, 40),
        default_cooldown=create_cooldown("*"),
    )


# ========== 估值定价引擎实体 ==========


@dataclass(frozen=True)
class ValuationSnapshot:
    """
    估值快照

    捕获决策时的估值状态，用于后续追溯和审计。

    Attributes:
        snapshot_id: 快照唯一标识
        security_code: 证券代码
        valuation_method: 估值方法
        fair_value: 公允价值
        entry_price_low: 入场价格下限
        entry_price_high: 入场价格上限
        target_price_low: 目标价格下限
        target_price_high: 目标价格上限
        stop_loss_price: 止损价格
        calculated_at: 计算时间
        input_parameters: 输入参数
        version: 版本号
        is_legacy: 是否为历史数据迁移

    Example:
        >>> snapshot = ValuationSnapshot(
        ...     snapshot_id="vs_001",
        ...     security_code="000001.SH",
        ...     valuation_method=ValuationMethod.COMPOSITE,
        ...     fair_value=Decimal("12.50"),
        ...     entry_price_low=Decimal("10.50"),
        ...     entry_price_high=Decimal("11.00"),
        ...     target_price_low=Decimal("13.00"),
        ...     target_price_high=Decimal("14.50"),
        ...     stop_loss_price=Decimal("9.50"),
        ...     calculated_at=datetime.now(timezone.utc),
        ...     input_parameters={"pe_percentile": 0.15, "pb_percentile": 0.20},
        ... )
    """

    snapshot_id: str
    security_code: str
    valuation_method: str  # ValuationMethod enum value
    fair_value: Decimal
    entry_price_low: Decimal
    entry_price_high: Decimal
    target_price_low: Decimal
    target_price_high: Decimal
    stop_loss_price: Decimal
    calculated_at: datetime
    input_parameters: dict[str, Any]
    version: int = 1
    is_legacy: bool = False

    @property
    def entry_range(self) -> tuple[Decimal, Decimal]:
        """入场价格区间"""
        return (self.entry_price_low, self.entry_price_high)

    @property
    def target_range(self) -> tuple[Decimal, Decimal]:
        """目标价格区间"""
        return (self.target_price_low, self.target_price_high)

    @property
    def upside_potential(self) -> Decimal:
        """上行空间（基于入场价中位）"""
        entry_mid = (self.entry_price_low + self.entry_price_high) / 2
        target_mid = (self.target_price_low + self.target_price_high) / 2
        if entry_mid > 0:
            return (target_mid - entry_mid) / entry_mid * 100
        return Decimal("0")

    @property
    def downside_risk(self) -> Decimal:
        """下行风险（基于入场价中位）"""
        entry_mid = (self.entry_price_low + self.entry_price_high) / 2
        if entry_mid > 0:
            return (entry_mid - self.stop_loss_price) / entry_mid * 100
        return Decimal("0")

    @property
    def risk_reward_ratio(self) -> Decimal:
        """风险收益比"""
        if self.downside_risk > 0:
            return self.upside_potential / self.downside_risk
        return Decimal("0")

    def is_price_in_entry_range(self, price: Decimal) -> bool:
        """检查价格是否在入场区间内"""
        return self.entry_price_low <= price <= self.entry_price_high

    def is_price_above_target(self, price: Decimal) -> bool:
        """检查价格是否达到目标区间"""
        return price >= self.target_price_low

    def should_stop_loss(self, price: Decimal) -> bool:
        """检查是否触发止损"""
        return price <= self.stop_loss_price

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "snapshot_id": self.snapshot_id,
            "security_code": self.security_code,
            "valuation_method": self.valuation_method,
            "fair_value": str(self.fair_value),
            "entry_price_low": str(self.entry_price_low),
            "entry_price_high": str(self.entry_price_high),
            "target_price_low": str(self.target_price_low),
            "target_price_high": str(self.target_price_high),
            "stop_loss_price": str(self.stop_loss_price),
            "calculated_at": self.calculated_at.isoformat(),
            "input_parameters": self.input_parameters,
            "version": self.version,
            "is_legacy": self.is_legacy,
            "upside_potential": str(self.upside_potential),
            "downside_risk": str(self.downside_risk),
            "risk_reward_ratio": str(self.risk_reward_ratio),
        }


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

    def validate_sell_price(self, market_price: Decimal, triggered_by_risk: bool = False) -> tuple[bool, str]:
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
            "market_price_at_review": str(self.market_price_at_review) if self.market_price_at_review else None,
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


@dataclass(frozen=True)
class TransitionOrder:
    """账户级调仓指令。"""

    security_code: str
    action: str
    current_qty: int
    target_qty: int
    delta_qty: int
    current_weight: float
    target_weight: float
    price_band_low: Decimal
    price_band_high: Decimal
    max_capital: Decimal
    stop_loss_price: Decimal | None
    invalidation_rule: dict[str, Any]
    invalidation_description: str = ""
    requires_user_confirmation: bool = False
    review_by: str | None = None
    time_horizon: str = "swing"
    source_recommendation_id: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def is_hold(self) -> bool:
        return self.action == "HOLD"

    @property
    def is_ready_for_approval(self) -> bool:
        if self.is_hold:
            return False
        if self.stop_loss_price in [None, Decimal("0"), "0", 0]:
            return False
        if not self.invalidation_rule:
            return False
        if self.invalidation_rule.get("requires_user_confirmation"):
            return False
        return bool(self.invalidation_rule.get("conditions"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_code": self.security_code,
            "action": self.action,
            "current_qty": self.current_qty,
            "target_qty": self.target_qty,
            "delta_qty": self.delta_qty,
            "current_weight": self.current_weight,
            "target_weight": self.target_weight,
            "price_band_low": str(self.price_band_low),
            "price_band_high": str(self.price_band_high),
            "max_capital": str(self.max_capital),
            "stop_loss_price": str(self.stop_loss_price) if self.stop_loss_price is not None else None,
            "invalidation_rule": self.invalidation_rule,
            "invalidation_description": self.invalidation_description,
            "requires_user_confirmation": self.requires_user_confirmation,
            "review_by": self.review_by,
            "time_horizon": self.time_horizon,
            "source_recommendation_id": self.source_recommendation_id,
            "notes": self.notes,
            "is_ready_for_approval": self.is_ready_for_approval,
        }


@dataclass(frozen=True)
class PortfolioTransitionPlan:
    """账户级调仓计划。"""

    plan_id: str
    account_id: str
    as_of: datetime
    source_recommendation_ids: list[str]
    current_positions_snapshot: list[dict[str, Any]]
    target_positions_snapshot: list[dict[str, Any]]
    orders: list[TransitionOrder]
    risk_contract: dict[str, Any]
    summary: dict[str, Any]
    status: TransitionPlanStatus = TransitionPlanStatus.DRAFT
    approval_request_id: str | None = None

    @property
    def blocking_issues(self) -> list[str]:
        issues: list[str] = []
        actionable_orders = [order for order in self.orders if not order.is_hold]
        if not actionable_orders:
            return ["当前计划没有可执行订单"]
        for order in actionable_orders:
            if order.stop_loss_price in [None, Decimal("0"), "0", 0]:
                issues.append(f"{order.security_code}: 缺少止损价")
            if not order.invalidation_rule or order.invalidation_rule.get("requires_user_confirmation"):
                issues.append(f"{order.security_code}: 缺少完整证伪条件")
            elif not order.invalidation_rule.get("conditions"):
                issues.append(f"{order.security_code}: 证伪条件为空")
        return issues

    @property
    def can_enter_approval(self) -> bool:
        return not self.blocking_issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "account_id": self.account_id,
            "as_of": self.as_of.isoformat(),
            "source_recommendation_ids": self.source_recommendation_ids,
            "current_positions": self.current_positions_snapshot,
            "target_positions": self.target_positions_snapshot,
            "orders": [order.to_dict() for order in self.orders],
            "risk_contract": self.risk_contract,
            "summary": self.summary,
            "status": self.status.value,
            "approval_request_id": self.approval_request_id,
            "can_enter_approval": self.can_enter_approval,
            "blocking_issues": self.blocking_issues,
        }


# ========== 估值定价工厂函数 ==========


def create_valuation_snapshot(
    security_code: str,
    valuation_method: str,
    fair_value: Decimal,
    entry_price_low: Decimal,
    entry_price_high: Decimal,
    target_price_low: Decimal,
    target_price_high: Decimal,
    stop_loss_price: Decimal,
    input_parameters: dict[str, Any],
    is_legacy: bool = False,
) -> ValuationSnapshot:
    """
    创建估值快照的便捷函数

    Args:
        security_code: 证券代码
        valuation_method: 估值方法
        fair_value: 公允价值
        entry_price_low: 入场价格下限
        entry_price_high: 入场价格上限
        target_price_low: 目标价格下限
        target_price_high: 目标价格上限
        stop_loss_price: 止损价格
        input_parameters: 输入参数
        is_legacy: 是否为历史数据

    Returns:
        ValuationSnapshot 实例
    """
    return ValuationSnapshot(
        snapshot_id=f"vs_{uuid4().hex[:12]}",
        security_code=security_code,
        valuation_method=valuation_method,
        fair_value=fair_value,
        entry_price_low=entry_price_low,
        entry_price_high=entry_price_high,
        target_price_low=target_price_low,
        target_price_high=target_price_high,
        stop_loss_price=stop_loss_price,
        calculated_at=datetime.now(UTC),
        input_parameters=input_parameters,
        is_legacy=is_legacy,
    )


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


def _build_default_invalidation_rule() -> dict[str, Any]:
    return {
        "logic": "AND",
        "conditions": [],
        "requires_user_confirmation": True,
    }


def _resolve_invalidation_payload(
    signal_ids: list[str],
    signal_payloads: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str, bool]:
    payloads = signal_payloads or {}
    for signal_id in signal_ids:
        payload = payloads.get(str(signal_id)) or {}
        rule = payload.get("invalidation_rule_json")
        if rule:
            return (
                rule,
                str(payload.get("invalidation_description") or payload.get("invalidation_logic") or ""),
                False,
            )
    return _build_default_invalidation_rule(), "待补充证伪条件", True


def create_portfolio_transition_plan(
    account_id: str,
    recommendations: list["UnifiedRecommendation"],
    current_positions: list[dict[str, Any]],
    signal_payloads: dict[str, dict[str, Any]] | None = None,
    risk_contract: dict[str, Any] | None = None,
    as_of: datetime | None = None,
) -> PortfolioTransitionPlan:
    """
    根据当前账户持仓和推荐生成账户级调仓计划。
    """

    as_of_time = as_of or datetime.now(UTC)
    signal_payload_map = signal_payloads or {}
    current_position_map = {
        str(position.get("asset_code") or "").upper(): position
        for position in current_positions
        if position.get("asset_code")
    }
    total_market_value = sum(
        Decimal(str(position.get("market_value") or "0")) for position in current_positions
    )
    orders: list[TransitionOrder] = []
    filtered_out: list[dict[str, str]] = []
    target_positions: list[dict[str, Any]] = []

    for recommendation in recommendations:
        if getattr(recommendation, "status", None) == RecommendationStatus.CONFLICT:
            filtered_out.append(
                {
                    "recommendation_id": recommendation.recommendation_id,
                    "security_code": recommendation.security_code,
                    "reason": "conflict",
                }
            )
            continue

        security_code = str(recommendation.security_code or "").upper()
        current_position = current_position_map.get(security_code, {})
        current_qty = int(current_position.get("quantity") or 0)
        current_market_value = Decimal(str(current_position.get("market_value") or "0"))
        current_weight = 0.0
        if total_market_value > 0:
            current_weight = float((current_market_value / total_market_value) * Decimal("100"))

        desired_qty = int(max(getattr(recommendation, "suggested_quantity", 0) or 0, 0))
        action = "HOLD"
        target_qty = current_qty
        target_weight = current_weight
        notes: list[str] = []
        if recommendation.side == RecommendationSide.BUY.value:
            target_qty = max(current_qty, desired_qty)
            if target_qty > current_qty:
                action = "BUY"
            target_weight = float(getattr(recommendation, "position_pct", 0.0) or 0.0)
        elif recommendation.side == RecommendationSide.SELL.value:
            if current_qty <= 0:
                filtered_out.append(
                    {
                        "recommendation_id": recommendation.recommendation_id,
                        "security_code": recommendation.security_code,
                        "reason": "no_position_to_sell",
                    }
                )
                continue
            reduction_qty = desired_qty if desired_qty > 0 else current_qty
            reduction_qty = min(current_qty, reduction_qty)
            target_qty = max(current_qty - reduction_qty, 0)
            action = "EXIT" if target_qty == 0 else "REDUCE"
            if current_qty > 0:
                target_weight = round(current_weight * (target_qty / current_qty), 2)
        else:
            if current_qty > 0 and desired_qty > 0 and desired_qty < current_qty:
                target_qty = desired_qty
                action = "REDUCE"
                target_weight = round(current_weight * (target_qty / current_qty), 2)
                notes.append("reduce_from_hold_target")
            else:
                target_qty = current_qty
                action = "HOLD"

        delta_qty = target_qty - current_qty
        invalidation_rule, invalidation_description, requires_confirmation = _resolve_invalidation_payload(
            list(getattr(recommendation, "source_signal_ids", []) or []),
            signal_payload_map,
        )
        stop_loss_price = getattr(recommendation, "stop_loss_price", None)
        if action != "HOLD" and stop_loss_price in [None, Decimal("0"), "0"]:
            notes.append("missing_stop_loss")
        price_band_low = (
            getattr(recommendation, "entry_price_low", Decimal("0"))
            if action == "BUY"
            else getattr(recommendation, "target_price_low", Decimal("0"))
        )
        price_band_high = (
            getattr(recommendation, "entry_price_high", Decimal("0"))
            if action == "BUY"
            else getattr(recommendation, "target_price_high", Decimal("0"))
        )
        order = TransitionOrder(
            security_code=security_code,
            action=action,
            current_qty=current_qty,
            target_qty=target_qty,
            delta_qty=delta_qty,
            current_weight=round(current_weight, 2),
            target_weight=round(target_weight, 2),
            price_band_low=Decimal(str(price_band_low or "0")),
            price_band_high=Decimal(str(price_band_high or "0")),
            max_capital=Decimal(str(getattr(recommendation, "max_capital", "0") or "0")),
            stop_loss_price=(
                Decimal(str(stop_loss_price))
                if stop_loss_price not in [None, ""]
                else None
            ),
            invalidation_rule=invalidation_rule,
            invalidation_description=invalidation_description,
            requires_user_confirmation=requires_confirmation,
            review_by=(as_of_time + timedelta(days=5)).date().isoformat(),
            source_recommendation_id=recommendation.recommendation_id,
            notes=notes,
        )
        orders.append(order)
        target_positions.append(
            {
                "security_code": security_code,
                "target_qty": target_qty,
                "target_weight": round(target_weight, 2),
                "action": action,
                "source_recommendation_id": recommendation.recommendation_id,
            }
        )

    default_risk_contract = {
        "max_single_position_pct": 20.0,
        "max_total_turnover_pct": 50.0,
        "cash_floor": 10.0,
        "portfolio_drawdown_guard": 12.0,
        "gate_snapshot": "decision_workspace_v2",
        "quota_snapshot": "weekly",
    }
    if risk_contract:
        default_risk_contract.update(risk_contract)

    summary = {
        "orders_count": len(orders),
        "buy_count": sum(1 for order in orders if order.action == "BUY"),
        "reduce_count": sum(1 for order in orders if order.action == "REDUCE"),
        "exit_count": sum(1 for order in orders if order.action == "EXIT"),
        "hold_count": sum(1 for order in orders if order.action == "HOLD"),
        "filtered_out": filtered_out,
    }

    plan = PortfolioTransitionPlan(
        plan_id=f"plan_{uuid4().hex[:12]}",
        account_id=account_id,
        as_of=as_of_time,
        source_recommendation_ids=[recommendation.recommendation_id for recommendation in recommendations],
        current_positions_snapshot=current_positions,
        target_positions_snapshot=target_positions,
        orders=orders,
        risk_contract=default_risk_contract,
        summary=summary,
        status=TransitionPlanStatus.DRAFT,
    )

    if plan.can_enter_approval:
        return replace(plan, status=TransitionPlanStatus.READY_FOR_APPROVAL)
    return plan


# ============================================================================
# 统一推荐对象（Top-down + Bottom-up 融合）
# ============================================================================


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
        return (
            self.status == RecommendationStatus.APPROVED
            and self.beta_gate_passed
        )


class ModelParamConfig:
    """
    模型参数配置

    保存推荐模型参数（按环境/版本）。

    Attributes:
        config_id: 配置唯一标识
        param_key: 参数键
        param_value: 参数值
        param_type: 参数类型 (float/int/str/bool)
        env: 环境 (dev/test/prod)
        version: 版本号
        is_active: 是否激活
        description: 参数描述
        updated_by: 最后修改人
        updated_reason: 变更说明
        created_at: 创建时间
        updated_at: 更新时间
    """

    config_id: str
    param_key: str
    param_value: str
    param_type: str
    env: str
    version: int
    is_active: bool
    description: str
    updated_by: str
    updated_reason: str
    created_at: datetime
    updated_at: datetime

    def __init__(
        self,
        config_id: str,
        param_key: str,
        param_value: str,
        param_type: str = "float",
        env: str = "dev",
        version: int = 1,
        is_active: bool = True,
        description: str = "",
        updated_by: str = "",
        updated_reason: str = "",
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ):
        self.config_id = config_id
        self.param_key = param_key
        self.param_value = param_value
        self.param_type = param_type
        self.env = env
        self.version = version
        self.is_active = is_active
        self.description = description
        self.updated_by = updated_by
        self.updated_reason = updated_reason
        self.created_at = created_at or datetime.now(UTC)
        self.updated_at = updated_at or datetime.now(UTC)

    def __repr__(self) -> str:
        return f"ModelParamConfig({self.param_key}={self.param_value}, env={self.env})"

    def get_typed_value(self) -> Any:
        """
        获取类型化的参数值

        Returns:
            根据参数类型转换后的值
        """
        if self.param_type == "float":
            return float(self.param_value)
        elif self.param_type == "int":
            return int(self.param_value)
        elif self.param_type == "bool":
            return self.param_value.lower() in ("true", "1", "yes")
        else:
            return self.param_value


class ModelParamAuditLog:
    """
    模型参数审计日志

    保存参数变更审计日志（前后值、操作者、时间、备注）。

    Attributes:
        log_id: 日志唯一标识
        param_key: 参数键
        old_value: 旧值
        new_value: 新值
        env: 环境
        changed_by: 变更人
        change_reason: 变更原因
        changed_at: 变更时间
    """

    log_id: str
    param_key: str
    old_value: str
    new_value: str
    env: str
    changed_by: str
    change_reason: str
    changed_at: datetime

    def __init__(
        self,
        log_id: str,
        param_key: str,
        old_value: str,
        new_value: str,
        env: str = "dev",
        changed_by: str = "",
        change_reason: str = "",
        changed_at: datetime | None = None,
    ):
        self.log_id = log_id
        self.param_key = param_key
        self.old_value = old_value
        self.new_value = new_value
        self.env = env
        self.changed_by = changed_by
        self.change_reason = change_reason
        self.changed_at = changed_at or datetime.now(UTC)

    def __repr__(self) -> str:
        return (
            f"ModelParamAuditLog({self.param_key}, "
            f"{self.old_value} -> {self.new_value}, by={self.changed_by})"
        )


# ============================================================================
# 便捷工厂函数
# ============================================================================


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
