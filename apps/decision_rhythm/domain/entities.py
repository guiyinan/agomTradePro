"""
Decision Rhythm Domain Entities

决策频率约束和配额管理的核心实体定义。
实现稀疏决策的工程化约束。

仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


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
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    quota_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Backward compatibility fields
    max_executions: Optional[int] = None
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
        return datetime.now() > self.period_end

    @property
    def days_remaining(self) -> Optional[int]:
        """剩余天数"""
        if self.period_end is None:
            return None
        delta = self.period_end - datetime.now()
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
            created_at=self.created_at,
            updated_at=datetime.now(),
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
            created_at=self.created_at,
            updated_at=datetime.now(),
        )

    def reset(self) -> "DecisionQuota":
        """重置配额，返回新的配额对象"""
        return DecisionQuota(
            period=self.period,
            max_decisions=self.max_decisions,
            max_execution_count=self.max_execution_count,
            used_decisions=0,
            used_executions=0,
            period_start=datetime.now(),
            period_end=self._calculate_period_end(),
            quota_id=self.quota_id,
            created_at=self.created_at,
            updated_at=datetime.now(),
        )

    def _calculate_period_end(self, now: Optional[datetime] = None) -> Optional[datetime]:
        """计算周期结束时间

        Args:
            now: 可选的时间戳，用于避免竞态条件
        """
        if now is None:
            now = datetime.now()
        if self.period == QuotaPeriod.DAILY:
            return now.replace(hour=23, minute=59, second=59)
        elif self.period == QuotaPeriod.WEEKLY:
            # 下周一
            days_ahead = 7 - now.weekday()
            if days_ahead == 7:
                days_ahead = 0
            return now + timedelta(days=days_ahead)
        elif self.period == QuotaPeriod.MONTHLY:
            # 下月第一天
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)
            return next_month
        return None

    def to_dict(self) -> Dict[str, Any]:
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
    last_decision_at: Optional[datetime] = None
    last_execution_at: Optional[datetime] = None
    min_decision_interval_hours: int = 24
    min_execution_interval_hours: int = 48
    same_asset_cooldown_hours: int = 72
    cooldown_id: Optional[str] = None

    @property
    def is_decision_ready(self) -> bool:
        """是否可以决策"""
        if self.last_decision_at is None:
            return True

        elapsed = (datetime.now() - self.last_decision_at).total_seconds() / 3600
        return elapsed >= self.min_decision_interval_hours

    @property
    def is_execution_ready(self) -> bool:
        """是否可以执行"""
        if self.last_execution_at is None:
            return True

        elapsed = (datetime.now() - self.last_execution_at).total_seconds() / 3600
        return elapsed >= self.min_execution_interval_hours

    @property
    def decision_ready_in_hours(self) -> float:
        """距离可决策的小时数"""
        if self.last_decision_at is None:
            return 0.0

        elapsed = (datetime.now() - self.last_decision_at).total_seconds() / 3600
        remaining = self.min_decision_interval_hours - elapsed
        return max(0.0, remaining)

    @property
    def execution_ready_in_hours(self) -> float:
        """距离可执行的小时数"""
        if self.last_execution_at is None:
            return 0.0

        elapsed = (datetime.now() - self.last_execution_at).total_seconds() / 3600
        remaining = self.min_execution_interval_hours - elapsed
        return max(0.0, remaining)

    def update_decision_time(self) -> "CooldownPeriod":
        """更新决策时间，返回新的冷却期对象"""
        return CooldownPeriod(
            asset_code=self.asset_code,
            last_decision_at=datetime.now(),
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
            last_execution_at=datetime.now(),
            min_decision_interval_hours=self.min_decision_interval_hours,
            min_execution_interval_hours=self.min_execution_interval_hours,
            same_asset_cooldown_hours=self.same_asset_cooldown_hours,
            cooldown_id=self.cooldown_id,
        )

    def to_dict(self) -> Dict[str, Any]:
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
    trigger_id: Optional[str] = None
    reason: str = ""
    expected_confidence: float = 0.0
    quota_period: Optional[QuotaPeriod] = None
    quantity: Optional[int] = None
    notional: Optional[float] = None
    status: DecisionStatus = DecisionStatus.PENDING
    created_at: Optional[datetime] = None
    requested_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    # 新增字段：首页主流程闭环改造
    candidate_id: Optional[str] = None
    execution_target: ExecutionTarget = ExecutionTarget.NONE
    execution_status: ExecutionStatus = ExecutionStatus.PENDING
    executed_at: Optional[datetime] = None
    execution_ref: Optional[Dict[str, Any]] = None

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
        return datetime.now() > self.expires_at

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

    def to_dict(self) -> Dict[str, Any]:
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
    scheduled_at: Optional[datetime] = None
    estimated_execution_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    wait_until: Optional[datetime] = None
    alternative_suggestions: List[str] = field(default_factory=list)
    quota_status: Optional[str] = None
    cooldown_status: Optional[str] = None
    responded_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
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
    priority_weights: Dict[DecisionPriority, float] = field(default_factory=lambda: {
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

    def to_dict(self) -> Dict[str, Any]:
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

    now = datetime.now()
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
