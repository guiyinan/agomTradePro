"""
Domain Services for Decision Rhythm

决策频率约束和配额管理的核心业务逻辑实现。
提供稀疏决策的调度、冷却控制和配额管理。

仅使用 Python 标准库。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from uuid import uuid4

if TYPE_CHECKING:
    from .entities import DecisionFeatureSnapshot, UnifiedRecommendation

from .entities import (
    ApprovalStatus,
    CooldownPeriod,
    DecisionPriority,
    DecisionQuota,
    DecisionRequest,
    DecisionResponse,
    ExecutionApprovalRequest,
    ExecutionStatus,
    ExecutionTarget,
    InvestmentRecommendation,
    QuotaPeriod,
    RhythmConfig,
    ValuationSnapshot,
    create_execution_approval_request,
    create_investment_recommendation,
    create_valuation_snapshot,
    get_default_rhythm_config,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuotaCheckResult:
    """
    配额检查结果

    Attributes:
        passed: 是否通过
        reason: 原因描述
        available_at: 可用时间（可选）
    """

    passed: bool
    reason: str
    available_at: datetime | None = None


@dataclass(frozen=True)
class CooldownCheckResult:
    """
    冷却检查结果

    Attributes:
        passed: 是否通过
        reason: 原因描述
        ready_at: 就绪时间（可选）
        wait_hours: 等待小时数
    """

    passed: bool
    reason: str
    ready_at: datetime | None = None
    wait_hours: float = 0.0


class QuotaManager:
    """
    配额管理器

    管理决策配额的创建、检查、消耗和重置。

    Attributes:
        quotas: 周期到配额的映射
        config: 节奏配置

    Example:
        >>> manager = QuotaManager()
        >>> result = manager.check_quota(request, QuotaPeriod.WEEKLY)
    """

    def __init__(self, config: RhythmConfig | None = None):
        """
        初始化配额管理器

        Args:
            config: 节奏配置
        """
        self.config = config or get_default_rhythm_config()
        self.quotas: dict[QuotaPeriod, DecisionQuota] = {
            QuotaPeriod.DAILY: self.config.daily_quota,
            QuotaPeriod.WEEKLY: self.config.weekly_quota,
            QuotaPeriod.MONTHLY: self.config.monthly_quota,
        }

    def check_quota(
        self,
        request: DecisionRequest,
        period: QuotaPeriod,
    ) -> QuotaCheckResult:
        """
        检查配额是否充足

        Args:
            request: 决策请求
            period: 配额周期

        Returns:
            配额检查结果
        """
        quota = self.quotas.get(period)
        if quota is None:
            return QuotaCheckResult(
                passed=False,
                reason=f"未配置 {period.value} 配额",
            )

        # 检查是否需要重置
        if quota.is_expired:
            self._reset_quota(period)
            quota = self.quotas[period]

        # CRITICAL 优先级总是允许
        if request.priority == DecisionPriority.CRITICAL:
            return QuotaCheckResult(
                passed=True,
                reason="紧急决策，允许执行",
            )

        # 检查决策配额
        if quota.is_decision_exceeded:
            return QuotaCheckResult(
                passed=False,
                reason=f"{period.value} 配额已耗尽 ({quota.used_decisions}/{quota.max_decisions})",
                available_at=quota.period_end,
            )

        # 检查执行配额（如果是执行请求）
        if request.priority != DecisionPriority.INFO and quota.is_execution_exceeded:
            return QuotaCheckResult(
                passed=False,
                reason=f"{period.value} 执行配额已耗尽 ({quota.used_executions}/{quota.max_execution_count})",
                available_at=quota.period_end,
            )

        return QuotaCheckResult(
            passed=True,
            reason=f"{period.value} 配额充足",
        )

    def consume_quota(
        self,
        request: DecisionRequest,
        period: QuotaPeriod,
    ) -> DecisionQuota:
        """
        消耗配额

        Args:
            request: 决策请求
            period: 配额周期

        Returns:
            更新后的配额
        """
        quota = self.quotas[period]

        # INFO 优先级只消耗决策配额，不消耗执行配额
        if request.priority == DecisionPriority.INFO:
            new_quota = quota.consume_decision(1)
        else:
            new_quota = quota.consume_decision(1).consume_execution(1)

        self.quotas[period] = new_quota
        logger.info(
            f"消耗配额: {period.value} "
            f"决策 {new_quota.used_decisions}/{new_quota.max_decisions}, "
            f"执行 {new_quota.used_executions}/{new_quota.max_execution_count}"
        )

        return new_quota

    def _reset_quota(self, period: QuotaPeriod) -> None:
        """重置配额"""
        old_quota = self.quotas[period]
        new_quota = old_quota.reset()
        self.quotas[period] = new_quota
        logger.info(f"配额重置: {period.value}")

    def reset_all_quotas(self) -> None:
        """重置所有配额"""
        for period in self.quotas:
            self._reset_quota(period)

    def get_quota_status(self, period: QuotaPeriod) -> dict[str, Any]:
        """获取配额状态"""
        quota = self.quotas.get(period)
        if quota is None:
            return {}

        return quota.to_dict()

    def get_all_quota_statuses(self) -> dict[str, dict[str, Any]]:
        """获取所有配额状态"""
        return {period.value: self.get_quota_status(period) for period in QuotaPeriod}


class CooldownManager:
    """
    冷却期管理器

    管理资产的决策和执行冷却期。

    Attributes:
        cooldowns: 资产代码到冷却期的映射
        default_config: 默认冷却配置

    Example:
        >>> manager = CooldownManager()
        >>> result = manager.check_cooldown("000001.SH")
    """

    def __init__(self, default_config: CooldownPeriod | None = None):
        """
        初始化冷却期管理器

        Args:
            default_config: 默认冷却配置
        """
        self.default_config = default_config or CooldownPeriod(asset_code="*")
        self.cooldowns: dict[str, CooldownPeriod] = {}

    def get_cooldown(self, asset_code: str) -> CooldownPeriod:
        """获取资产的冷却配置"""
        if asset_code not in self.cooldowns:
            return CooldownPeriod(
                asset_code=asset_code,
                min_decision_interval_hours=self.default_config.min_decision_interval_hours,
                min_execution_interval_hours=self.default_config.min_execution_interval_hours,
                same_asset_cooldown_hours=self.default_config.same_asset_cooldown_hours,
            )
        return self.cooldowns[asset_code]

    def check_cooldown(
        self,
        request: DecisionRequest,
        check_execution: bool = False,
    ) -> CooldownCheckResult:
        """
        检查冷却期

        Args:
            request: 决策请求
            check_execution: 是否检查执行冷却

        Returns:
            冷却检查结果
        """
        # CRITICAL 优先级跳过冷却检查
        if request.priority == DecisionPriority.CRITICAL:
            return CooldownCheckResult(
                passed=True,
                reason="紧急决策，跳过冷却检查",
            )

        cooldown = self.get_cooldown(request.asset_code)

        if check_execution:
            # 检查执行冷却
            if not cooldown.is_execution_ready:
                ready_at = cooldown.last_execution_at + timedelta(
                    hours=cooldown.min_execution_interval_hours
                )
                return CooldownCheckResult(
                    passed=False,
                    reason=f"执行冷却期内，剩余 {cooldown.execution_ready_in_hours:.1f} 小时",
                    ready_at=ready_at,
                    wait_hours=cooldown.execution_ready_in_hours,
                )
        else:
            # 检查决策冷却
            if not cooldown.is_decision_ready:
                ready_at = cooldown.last_decision_at + timedelta(
                    hours=cooldown.min_decision_interval_hours
                )
                return CooldownCheckResult(
                    passed=False,
                    reason=f"决策冷却期内，剩余 {cooldown.decision_ready_in_hours:.1f} 小时",
                    ready_at=ready_at,
                    wait_hours=cooldown.decision_ready_in_hours,
                )

        return CooldownCheckResult(
            passed=True,
            reason="冷却期已过",
        )

    def update_decision_time(self, asset_code: str) -> CooldownPeriod:
        """更新决策时间"""
        cooldown = self.get_cooldown(asset_code)
        new_cooldown = cooldown.update_decision_time()
        self.cooldowns[asset_code] = new_cooldown
        return new_cooldown

    def update_execution_time(self, asset_code: str) -> CooldownPeriod:
        """更新执行时间"""
        cooldown = self.get_cooldown(asset_code)
        new_cooldown = cooldown.update_execution_time()
        self.cooldowns[asset_code] = new_cooldown
        return new_cooldown

    def clear_cooldown(self, asset_code: str) -> None:
        """清除冷却期"""
        if asset_code in self.cooldowns:
            del self.cooldowns[asset_code]

    def clear_all_cooldowns(self) -> None:
        """清除所有冷却期"""
        self.cooldowns.clear()


class RhythmManager:
    """
    决策节奏管理器

    统一管理配额和冷却期，协调决策请求的审批。

    Attributes:
        quota_manager: 配额管理器
        cooldown_manager: 冷却期管理器
        config: 节奏配置

    Example:
        >>> manager = RhythmManager()
        >>> response = manager.submit_request(request)
    """

    def __init__(
        self,
        quota_manager: QuotaManager | None = None,
        cooldown_manager: CooldownManager | None = None,
        config: RhythmConfig | None = None,
    ):
        """
        初始化节奏管理器

        Args:
            quota_manager: 配额管理器
            cooldown_manager: 冷却期管理器
            config: 节奏配置
        """
        self.config = config or get_default_rhythm_config()
        self.quota_manager = quota_manager or QuotaManager(self.config)
        self.cooldown_manager = cooldown_manager or CooldownManager(self.config.default_cooldown)

    def submit_request(
        self,
        request: DecisionRequest,
        quota_period: QuotaPeriod = QuotaPeriod.WEEKLY,
    ) -> DecisionResponse:
        """
        提交决策请求

        完整的审批流程：
        1. 检查配额
        2. 检查冷却期
        3. 优先级排序
        4. 批准/拒绝

        Args:
            request: 决策请求
            quota_period: 使用的配额周期

        Returns:
            决策响应
        """
        # 1. 检查配额
        quota_check = self.quota_manager.check_quota(request, quota_period)
        if not quota_check.passed:
            return DecisionResponse(
                request_id=request.request_id,
                approved=False,
                approval_reason="配额不足",
                rejection_reason=quota_check.reason,
                wait_until=quota_check.available_at,
                quota_status=self.quota_manager.get_quota_status(quota_period),
            )

        # 2. 检查冷却期
        cooldown_check = self.cooldown_manager.check_cooldown(request)
        if not cooldown_check.passed:
            return DecisionResponse(
                request_id=request.request_id,
                approved=False,
                approval_reason="冷却期内",
                rejection_reason=cooldown_check.reason,
                wait_until=cooldown_check.ready_at,
                cooldown_status=f"需等待 {cooldown_check.wait_hours:.1f} 小时",
            )

        # 3. 批准
        scheduled_at = self._schedule_execution(request)
        self.quota_manager.consume_quota(request, quota_period)
        self.cooldown_manager.update_decision_time(request.asset_code)

        return DecisionResponse(
            request_id=request.request_id,
            approved=True,
            approval_reason="批准执行",
            scheduled_at=scheduled_at,
            estimated_execution_at=scheduled_at,
            quota_status=self.quota_manager.get_quota_status(quota_period),
        )

    def submit_batch(
        self,
        requests: list[DecisionRequest],
        quota_period: QuotaPeriod = QuotaPeriod.WEEKLY,
    ) -> list[DecisionResponse]:
        """
        批量提交决策请求

        按优先级排序后处理，高优先级先获批。

        Args:
            requests: 决策请求列表
            quota_period: 使用的配额周期

        Returns:
            决策响应列表
        """
        # 按优先级排序
        sorted_requests = sorted(
            requests,
            key=lambda r: r.priority_level,
            reverse=True,
        )

        responses = []
        for request in sorted_requests:
            response = self.submit_request(request, quota_period)
            responses.append(response)

        return responses

    def _schedule_execution(self, request: DecisionRequest) -> datetime:
        """调度执行时间"""
        # 立即执行（实际应该考虑交易时间等）
        return datetime.now(UTC)

    def get_summary(self) -> dict[str, Any]:
        """获取决策节奏摘要"""
        return {
            "quota_statuses": self.quota_manager.get_all_quota_statuses(),
            "cooldown_count": len(self.cooldown_manager.cooldowns),
            "config": self.config.to_dict(),
        }


class DecisionScheduler:
    """
    决策调度器

    对决策请求进行优先级排序和调度。

    Attributes:
        queue: 决策请求队列
        max_queue_size: 最大队列长度

    Example:
        >>> scheduler = DecisionScheduler()
        >>> scheduler.add_request(request)
        >>> next_request = scheduler.get_next()
    """

    def __init__(self, max_queue_size: int = 100):
        """
        初始化调度器

        Args:
            max_queue_size: 最大队列长度
        """
        self.queue: list[DecisionRequest] = []
        self.max_queue_size = max_queue_size

    def add_request(self, request: DecisionRequest) -> bool:
        """
        添加请求到队列

        Args:
            request: 决策请求

        Returns:
            是否成功添加
        """
        if len(self.queue) >= self.max_queue_size:
            logger.warning("决策队列已满")
            return False

        self.queue.append(request)
        return True

    def get_next(self) -> DecisionRequest | None:
        """
        获取下一个待处理的请求

        返回优先级最高的请求。

        Returns:
            决策请求，如果队列为空则返回 None
        """
        if not self.queue:
            return None

        # 按优先级和请求时间排序
        self.queue.sort(
            key=lambda r: (r.priority_level, r.requested_at.timestamp()),
            reverse=True,
        )

        return self.queue[0]

    def remove_request(self, request_id: str) -> bool:
        """
        从队列移除请求

        Args:
            request_id: 请求 ID

        Returns:
            是否成功移除
        """
        for i, request in enumerate(self.queue):
            if request.request_id == request_id:
                self.queue.pop(i)
                return True
        return False

    def clear(self) -> None:
        """清空队列"""
        self.queue.clear()

    def get_queue_summary(self) -> dict[str, Any]:
        """获取队列摘要"""
        if not self.queue:
            return {"size": 0, "by_priority": {}}

        by_priority = {}
        for request in self.queue:
            priority = request.priority.value
            by_priority[priority] = by_priority.get(priority, 0) + 1

        return {
            "size": len(self.queue),
            "by_priority": by_priority,
        }


# ========== 便捷函数 ==========


def submit_decision_request(
    asset_code: str,
    asset_class: str,
    direction: str,
    priority: DecisionPriority,
    reason: str = "",
    quota_period: QuotaPeriod = QuotaPeriod.WEEKLY,
) -> DecisionResponse:
    """
    提交决策请求的便捷函数

    Args:
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向
        priority: 优先级
        reason: 原因
        quota_period: 配额周期

    Returns:
        决策响应
    """
    from .entities import create_request

    request = create_request(
        asset_code=asset_code,
        asset_class=asset_class,
        direction=direction,
        priority=priority,
        reason=reason,
    )

    manager = RhythmManager()
    return manager.submit_request(request, quota_period)


def check_quota_status(period: QuotaPeriod) -> dict[str, Any]:
    """
    检查配额状态的便捷函数

    Args:
        period: 配额周期

    Returns:
        配额状态
    """
    manager = QuotaManager()
    return manager.get_quota_status(period)


def check_cooldown_status(asset_code: str) -> dict[str, Any]:
    """
    检查冷却状态的便捷函数

    Args:
        asset_code: 资产代码

    Returns:
        冷却状态
    """
    manager = CooldownManager()
    cooldown = manager.get_cooldown(asset_code)
    return cooldown.to_dict()


# ========== 预检查相关（WP-2: 决策编排与新 API）==========


@dataclass(frozen=True)
class PrecheckResult:
    """
    预检查结果

    Attributes:
        candidate_id: 候选 ID
        beta_gate_passed: Beta Gate 是否通过
        quota_ok: 配额是否充足
        cooldown_ok: 冷却期是否就绪
        candidate_valid: 候选是否有效（非过期/证伪）
        warnings: 警告列表
        errors: 错误列表（非空表示阻断）
        details: 详细信息
    """

    candidate_id: str
    beta_gate_passed: bool = True
    quota_ok: bool = True
    cooldown_ok: bool = True
    candidate_valid: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def can_proceed(self) -> bool:
        """是否可以继续提交决策"""
        return len(self.errors) == 0 and self.candidate_valid


@dataclass(frozen=True)
class ExecutionResult:
    """
    执行结果

    Attributes:
        request_id: 决策请求 ID
        execution_status: 执行状态
        executed_at: 执行时间
        execution_ref: 执行引用（如 trade_id, position_id）
        candidate_status: 候选状态
        error: 错误信息
    """

    request_id: str
    execution_status: str  # "EXECUTED", "FAILED", "CANCELLED"
    executed_at: datetime | None = None
    execution_ref: dict[str, Any] | None = None
    candidate_status: str | None = None
    error: str | None = None

    @property
    def is_success(self) -> bool:
        """是否执行成功"""
        return self.execution_status == "EXECUTED"


class ExecutionStatusStateMachine:
    """
    DecisionRequest 执行状态机

    状态迁移规则：
    - 创建后: execution_status=PENDING
    - 执行成功: PENDING -> EXECUTED
    - 执行失败: PENDING -> FAILED
    - 手动取消: PENDING/FAILED -> CANCELLED

    非法迁移（禁止）:
    - EXECUTED -> PENDING
    - CANCELLED -> EXECUTED
    """

    # 允许的状态迁移映射
    ALLOWED_TRANSITIONS = {
        "PENDING": ["EXECUTED", "FAILED", "CANCELLED"],
        "FAILED": ["CANCELLED"],
        "EXECUTED": [],  # 终态
        "CANCELLED": [],  # 终态
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        """
        检查状态迁移是否合法

        Args:
            from_status: 当前状态
            to_status: 目标状态

        Returns:
            是否允许迁移
        """
        if from_status == to_status:
            return True  # 相同状态允许

        allowed = cls.ALLOWED_TRANSITIONS.get(from_status, [])
        return to_status in allowed

    @classmethod
    def validate_transition(cls, from_status: str, to_status: str) -> tuple[bool, str]:
        """
        验证状态迁移并返回原因

        Args:
            from_status: 当前状态
            to_status: 目标状态

        Returns:
            (是否合法, 错误原因)
        """
        if cls.can_transition(from_status, to_status):
            return True, ""
        return False, f"非法状态迁移: {from_status} -> {to_status}"


class CandidateStatusStateMachine:
    """
    AlphaCandidate 状态机

    状态迁移规则：
    - CANDIDATE -> ACTIONABLE（候选通过）
    - ACTIONABLE -> EXECUTED（仅当执行 API 成功）
    - ACTIONABLE/CANDIDATE -> CANCELLED（人工取消）
    - 任意活跃态 -> INVALIDATED/EXPIRED（规则触发）

    硬约束：仅"状态按钮"不能直接把候选置 EXECUTED，必须经过执行 API。
    """

    # 允许的状态迁移映射
    ALLOWED_TRANSITIONS = {
        "WATCH": ["CANDIDATE", "ACTIONABLE", "CANCELLED", "INVALIDATED", "EXPIRED"],
        "CANDIDATE": ["ACTIONABLE", "CANCELLED", "INVALIDATED", "EXPIRED"],
        "ACTIONABLE": ["EXECUTED", "CANCELLED", "INVALIDATED", "EXPIRED"],
        "EXECUTED": [],  # 终态
        "CANCELLED": [],  # 终态
        "INVALIDATED": [],  # 终态
        "EXPIRED": [],  # 终态
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        """
        检查状态迁移是否合法

        Args:
            from_status: 当前状态
            to_status: 目标状态

        Returns:
            是否允许迁移
        """
        if from_status == to_status:
            return True  # 相同状态允许

        allowed = cls.ALLOWED_TRANSITIONS.get(from_status, [])
        return to_status in allowed

    @classmethod
    def can_execute(cls, from_status: str) -> bool:
        """
        检查是否可以执行（只有 ACTIONABLE 可以执行）

        Args:
            from_status: 当前状态

        Returns:
            是否可以执行
        """
        return from_status == "ACTIONABLE"

    @classmethod
    def validate_transition(
        cls, from_status: str, to_status: str, via_api: bool = False
    ) -> tuple[bool, str]:
        """
        验证状态迁移并返回原因

        Args:
            from_status: 当前状态
            to_status: 目标状态
            via_api: 是否通过执行 API

        Returns:
            (是否合法, 错误原因)
        """
        # 特殊处理：EXECUTED 只能通过执行 API 从 ACTIONABLE 迁移
        if to_status == "EXECUTED":
            if not via_api:
                return False, "候选不能直接标记为 EXECUTED，必须通过执行 API"
            if from_status != "ACTIONABLE":
                return False, f"只有 ACTIONABLE 状态可以执行，当前状态: {from_status}"
            return True, ""

        if cls.can_transition(from_status, to_status):
            return True, ""
        return False, f"非法状态迁移: {from_status} -> {to_status}"


# ========== 估值定价引擎服务 ==========


class ApprovalStatusStateMachine:
    """
    执行审批状态机

    状态迁移规则：
    - DRAFT -> PENDING（提交审批）
    - PENDING -> APPROVED（批准）
    - PENDING -> REJECTED（拒绝）
    - APPROVED -> EXECUTED（执行成功）
    - APPROVED/EXECUTED -> FAILED（执行失败）

    终态：REJECTED, FAILED
    """

    # 允许的状态迁移映射
    ALLOWED_TRANSITIONS = {
        ApprovalStatus.DRAFT: [ApprovalStatus.PENDING],
        ApprovalStatus.PENDING: [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED],
        ApprovalStatus.APPROVED: [ApprovalStatus.EXECUTED, ApprovalStatus.FAILED],
        ApprovalStatus.REJECTED: [],  # 终态
        ApprovalStatus.EXECUTED: [],  # 终态
        ApprovalStatus.FAILED: [ApprovalStatus.PENDING],  # 允许重试
    }

    @classmethod
    def can_transition(cls, from_status: ApprovalStatus, to_status: ApprovalStatus) -> bool:
        """
        检查状态迁移是否合法

        Args:
            from_status: 当前状态
            to_status: 目标状态

        Returns:
            是否允许迁移
        """
        if from_status == to_status:
            return True  # 相同状态允许

        allowed = cls.ALLOWED_TRANSITIONS.get(from_status, [])
        return to_status in allowed

    @classmethod
    def validate_transition(
        cls, from_status: ApprovalStatus, to_status: ApprovalStatus
    ) -> tuple[bool, str]:
        """
        验证状态迁移并返回原因

        Args:
            from_status: 当前状态
            to_status: 目标状态

        Returns:
            (是否合法, 错误原因)
        """
        if cls.can_transition(from_status, to_status):
            return True, ""
        return False, f"非法审批状态迁移: {from_status.value} -> {to_status.value}"

    @classmethod
    def get_valid_next_statuses(cls, current_status: ApprovalStatus) -> list[ApprovalStatus]:
        """
        获取有效的下一状态列表

        Args:
            current_status: 当前状态

        Returns:
            有效下一状态列表
        """
        return cls.ALLOWED_TRANSITIONS.get(current_status, [])


class ValuationSnapshotService:
    """
    估值快照服务

    提供估值快照的创建和管理功能。

    Example:
        >>> service = ValuationSnapshotService()
        >>> snapshot = service.create_from_comprehensive_valuation(
        ...     stock_code="000001.SH",
        ...     valuation_result=comprehensive_result,
        ...     current_price=Decimal("10.80"),
        ... )
    """

    # 止损比例（入场价下方）
    DEFAULT_STOP_LOSS_PCT = 0.10  # 10%

    # 目标收益比例（入场价上方）
    DEFAULT_TARGET_UPSIDE_PCT = 0.20  # 20%

    # 入场价格容差
    ENTRY_PRICE_TOLERANCE = 0.05  # 5%

    def create_snapshot(
        self,
        security_code: str,
        valuation_method: str,
        fair_value: Decimal,
        current_price: Decimal,
        input_parameters: dict[str, Any],
        stop_loss_pct: float | None = None,
        target_upside_pct: float | None = None,
    ) -> ValuationSnapshot:
        """
        创建估值快照

        Args:
            security_code: 证券代码
            valuation_method: 估值方法
            fair_value: 公允价值
            current_price: 当前价格
            input_parameters: 输入参数
            stop_loss_pct: 止损比例（默认 10%）
            target_upside_pct: 目标收益比例（默认 20%）

        Returns:
            ValuationSnapshot 实例
        """
        stop_loss_pct = stop_loss_pct or self.DEFAULT_STOP_LOSS_PCT
        target_upside_pct = target_upside_pct or self.DEFAULT_TARGET_UPSIDE_PCT

        # 计算入场价格区间（基于公允价值和容差）
        entry_price_low = fair_value * Decimal(str(1 - self.ENTRY_PRICE_TOLERANCE))
        entry_price_high = fair_value * Decimal(str(1 + self.ENTRY_PRICE_TOLERANCE))

        # 如果当前价格低于公允价值，扩大入场区间
        if current_price < fair_value:
            entry_price_high = max(entry_price_high, current_price * Decimal("1.02"))
            entry_price_low = min(entry_price_low, current_price * Decimal("0.98"))

        # 计算目标价格区间
        target_price_low = fair_value * Decimal(str(1 + target_upside_pct * 0.8))
        target_price_high = fair_value * Decimal(str(1 + target_upside_pct * 1.2))

        # 计算止损价格
        stop_loss_price = entry_price_low * Decimal(str(1 - stop_loss_pct))

        return create_valuation_snapshot(
            security_code=security_code,
            valuation_method=valuation_method,
            fair_value=fair_value,
            entry_price_low=entry_price_low,
            entry_price_high=entry_price_high,
            target_price_low=target_price_low,
            target_price_high=target_price_high,
            stop_loss_price=stop_loss_price,
            input_parameters=input_parameters,
        )

    def create_from_comprehensive_valuation(
        self,
        stock_code: str,
        valuation_result,  # ComprehensiveValuationResult
        current_price: Decimal,
    ) -> ValuationSnapshot:
        """
        从综合估值结果创建快照

        Args:
            stock_code: 股票代码
            valuation_result: 综合估值结果
            current_price: 当前价格

        Returns:
            ValuationSnapshot 实例
        """
        # 将综合评分转换为公允价值
        # 评分越高，公允价值相对当前价格的溢价越高
        score = valuation_result.overall_score
        if score >= 80:
            # 强烈低估：公允价值 = 当前价格 * 1.3
            fair_value_multiplier = 1.3
        elif score >= 60:
            # 中度低估：公允价值 = 当前价格 * 1.15
            fair_value_multiplier = 1.15
        elif score >= 40:
            # 合理：公允价值 = 当前价格
            fair_value_multiplier = 1.0
        else:
            # 高估：公允价值 = 当前价格 * 0.9
            fair_value_multiplier = 0.9

        fair_value = current_price * Decimal(str(fair_value_multiplier))

        # 提取输入参数
        input_parameters = {
            "overall_score": score,
            "overall_signal": valuation_result.overall_signal,
            "confidence": valuation_result.confidence,
            "scores": [
                {"method": s.method, "score": s.score, "signal": s.signal}
                for s in valuation_result.scores
            ],
        }

        return self.create_snapshot(
            security_code=stock_code,
            valuation_method="COMPOSITE",
            fair_value=fair_value,
            current_price=current_price,
            input_parameters=input_parameters,
        )

    def create_legacy_snapshot(
        self,
        security_code: str,
        estimated_fair_value: Decimal,
        current_price: Decimal,
    ) -> ValuationSnapshot:
        """
        创建历史数据的估值快照

        用于数据迁移，为历史建议创建缺失的估值快照。

        Args:
            security_code: 证券代码
            estimated_fair_value: 估算的公允价值
            current_price: 当前价格

        Returns:
            ValuationSnapshot 实例（标记为 legacy）
        """
        # 历史数据使用保守的参数
        snapshot = self.create_snapshot(
            security_code=security_code,
            valuation_method="LEGACY",
            fair_value=estimated_fair_value or current_price,
            current_price=current_price,
            input_parameters={"source": "legacy_migration"},
        )
        return replace(snapshot, is_legacy=True)

    def create_current_price_fallback_snapshot(
        self,
        security_code: str,
        current_price: Decimal,
        *,
        source: str = "current_price",
    ) -> ValuationSnapshot:
        """
        Create a conservative valuation snapshot from the latest observable price.

        This is only a fallback for recommendation contracts when no formal
        valuation is available; it must stay explicitly marked as FALLBACK.
        """
        return create_valuation_snapshot(
            security_code=security_code,
            valuation_method="FALLBACK",
            fair_value=current_price,
            entry_price_low=current_price * Decimal("0.95"),
            entry_price_high=current_price * Decimal("1.02"),
            target_price_low=current_price * Decimal("1.15"),
            target_price_high=current_price * Decimal("1.25"),
            stop_loss_price=current_price * Decimal("0.90"),
            input_parameters={
                "source": source,
                "fallback_type": "current_price_based",
                "fair_value_formula": "current_price",
                "entry_band": "current_price * 0.95..1.02",
                "target_band": "current_price * 1.15..1.25",
                "stop_loss": "current_price * 0.90",
            },
        )


class RecommendationConsolidationService:
    """
    建议聚合服务

    按账户+证券代码+方向聚合多个投资建议。

    聚合规则：
    1. 相同 (account_id, security_code, side) 的建议归并为一条
    2. 置信度取加权平均（按 position_size_pct 加权）
    3. 价格区间取并集（扩大范围）
    4. reason_codes 取并集
    5. source_recommendation_ids 保留所有来源

    Example:
        >>> service = RecommendationConsolidationService()
        >>> aggregated = service.consolidate(recommendations, account_id="account_1")
    """

    def consolidate(
        self,
        recommendations: list[InvestmentRecommendation],
        account_id: str,
    ) -> list[InvestmentRecommendation]:
        """
        聚合投资建议

        Args:
            recommendations: 投资建议列表
            account_id: 账户 ID

        Returns:
            聚合后的建议列表
        """
        if not recommendations:
            return []

        # 按 (security_code, side) 分组
        groups: dict[str, list[InvestmentRecommendation]] = {}
        for rec in recommendations:
            key = f"{rec.security_code}:{rec.side}"
            if key not in groups:
                groups[key] = []
            groups[key].append(rec)

        # 对每个分组进行聚合
        consolidated = []
        for key, group in groups.items():
            if len(group) == 1:
                # 单条建议不需要聚合
                consolidated.append(group[0])
            else:
                # 多条建议聚合
                merged = self._merge_recommendations(group, account_id)
                consolidated.append(merged)

        return consolidated

    def _merge_recommendations(
        self,
        recommendations: list[InvestmentRecommendation],
        account_id: str,
    ) -> InvestmentRecommendation:
        """
        合并多条建议

        Args:
            recommendations: 建议列表（同一 security_code 和 side）
            account_id: 账户 ID

        Returns:
            合并后的建议
        """
        first = recommendations[0]

        # 加权平均置信度
        total_weight = sum(rec.position_size_pct for rec in recommendations)
        if total_weight > 0:
            weighted_confidence = (
                sum(rec.confidence * rec.position_size_pct for rec in recommendations)
                / total_weight
            )
        else:
            weighted_confidence = sum(rec.confidence for rec in recommendations) / len(
                recommendations
            )

        # 价格区间取并集（扩大范围）
        entry_price_low = min(rec.entry_price_low for rec in recommendations)
        entry_price_high = max(rec.entry_price_high for rec in recommendations)
        target_price_low = min(rec.target_price_low for rec in recommendations)
        target_price_high = max(rec.target_price_high for rec in recommendations)
        stop_loss_price = max(
            rec.stop_loss_price for rec in recommendations
        )  # 止损价取最高（最保守）

        # 公允价值取加权平均
        fair_value = (
            sum(rec.fair_value * rec.position_size_pct for rec in recommendations) / total_weight
            if total_weight > 0
            else first.fair_value
        )

        # 仓位比例累加（但有上限）
        total_position_pct = min(
            sum(rec.position_size_pct for rec in recommendations),
            20.0,  # 单只股票最大 20% 仓位
        )

        # 最大资金取最大值
        max_capital = max(rec.max_capital for rec in recommendations)

        # reason_codes 取并集
        all_reason_codes = []
        for rec in recommendations:
            for code in rec.reason_codes:
                if code not in all_reason_codes:
                    all_reason_codes.append(code)

        # source_recommendation_ids 收集所有
        all_source_ids = []
        for rec in recommendations:
            all_source_ids.append(rec.recommendation_id)
            all_source_ids.extend(rec.source_recommendation_ids)

        # 合并人类可读理由
        rationales = [
            rec.human_readable_rationale for rec in recommendations if rec.human_readable_rationale
        ]
        merged_rationale = " | ".join(rationales[:3])  # 最多取 3 条
        if len(rationales) > 3:
            merged_rationale += f" ... (共 {len(rationales)} 条理由)"

        return InvestmentRecommendation(
            recommendation_id=f"rec_merged_{uuid4().hex[:8]}",
            security_code=first.security_code,
            side=first.side,
            confidence=round(weighted_confidence, 3),
            valuation_method="CONSOLIDATED",
            fair_value=fair_value,
            entry_price_low=entry_price_low,
            entry_price_high=entry_price_high,
            target_price_low=target_price_low,
            target_price_high=target_price_high,
            stop_loss_price=stop_loss_price,
            position_size_pct=total_position_pct,
            max_capital=max_capital,
            reason_codes=all_reason_codes,
            human_readable_rationale=merged_rationale,
            account_id=account_id,
            valuation_snapshot_id=first.valuation_snapshot_id,  # 使用第一条的快照
            source_recommendation_ids=all_source_ids,
            created_at=datetime.now(UTC),
            status="CONSOLIDATED",
        )


class ExecutionApprovalService:
    """
    执行审批服务

    处理执行审批的业务逻辑。

    Example:
        >>> service = ExecutionApprovalService()
        >>> result = service.approve(approval_request, reviewer_comments="审批通过")
    """

    def __init__(self):
        self.state_machine = ApprovalStatusStateMachine()

    def can_approve(
        self,
        approval_request: ExecutionApprovalRequest,
        market_price: Decimal,
    ) -> tuple[bool, str]:
        """
        检查是否可以批准执行

        Args:
            approval_request: 执行审批请求
            market_price: 当前市场价格

        Returns:
            (是否可以批准, 原因)
        """
        # 检查状态
        if not approval_request.is_pending:
            return (
                False,
                f"审批状态不是 PENDING，当前状态: {approval_request.approval_status.value}",
            )

        # 检查价格
        price_valid, price_reason = approval_request.validate_price_for_approval(market_price)
        if not price_valid:
            return False, price_reason

        # 检查风控
        risk_checks = approval_request.risk_check_results
        for check_name, check_result in risk_checks.items():
            if isinstance(check_result, dict) and not check_result.get("passed", True):
                return False, f"风控检查未通过: {check_name} - {check_result.get('reason', '')}"

        return True, "可以批准"

    def approve(
        self,
        approval_request: ExecutionApprovalRequest,
        reviewer_comments: str,
        market_price: Decimal | None = None,
    ) -> ExecutionApprovalRequest:
        """
        批准执行

        Args:
            approval_request: 执行审批请求
            reviewer_comments: 审批评论
            market_price: 当前市场价格（可选）

        Returns:
            更新后的 ExecutionApprovalRequest
        """
        # 验证状态迁移
        can_transition, reason = self.state_machine.validate_transition(
            approval_request.approval_status, ApprovalStatus.APPROVED
        )
        if not can_transition:
            raise ValueError(reason)

        return ExecutionApprovalRequest(
            request_id=approval_request.request_id,
            recommendation_id=approval_request.recommendation_id,
            plan_id=approval_request.plan_id,
            account_id=approval_request.account_id,
            security_code=approval_request.security_code,
            side=approval_request.side,
            approval_status=ApprovalStatus.APPROVED,
            suggested_quantity=approval_request.suggested_quantity,
            market_price_at_review=market_price or approval_request.market_price_at_review,
            price_range_low=approval_request.price_range_low,
            price_range_high=approval_request.price_range_high,
            stop_loss_price=approval_request.stop_loss_price,
            risk_check_results=approval_request.risk_check_results,
            reviewer_comments=reviewer_comments,
            regime_source=approval_request.regime_source,
            created_at=approval_request.created_at,
            reviewed_at=datetime.now(UTC),
            executed_at=None,
        )

    def reject(
        self,
        approval_request: ExecutionApprovalRequest,
        reviewer_comments: str,
    ) -> ExecutionApprovalRequest:
        """
        拒绝执行

        Args:
            approval_request: 执行审批请求
            reviewer_comments: 拒绝原因

        Returns:
            更新后的 ExecutionApprovalRequest
        """
        # 验证状态迁移
        can_transition, reason = self.state_machine.validate_transition(
            approval_request.approval_status, ApprovalStatus.REJECTED
        )
        if not can_transition:
            raise ValueError(reason)

        return ExecutionApprovalRequest(
            request_id=approval_request.request_id,
            recommendation_id=approval_request.recommendation_id,
            plan_id=approval_request.plan_id,
            account_id=approval_request.account_id,
            security_code=approval_request.security_code,
            side=approval_request.side,
            approval_status=ApprovalStatus.REJECTED,
            suggested_quantity=approval_request.suggested_quantity,
            market_price_at_review=approval_request.market_price_at_review,
            price_range_low=approval_request.price_range_low,
            price_range_high=approval_request.price_range_high,
            stop_loss_price=approval_request.stop_loss_price,
            risk_check_results=approval_request.risk_check_results,
            reviewer_comments=reviewer_comments,
            regime_source=approval_request.regime_source,
            created_at=approval_request.created_at,
            reviewed_at=datetime.now(UTC),
            executed_at=None,
        )

    def mark_executed(
        self,
        approval_request: ExecutionApprovalRequest,
    ) -> ExecutionApprovalRequest:
        """
        标记为已执行

        Args:
            approval_request: 执行审批请求

        Returns:
            更新后的 ExecutionApprovalRequest
        """
        # 验证状态迁移
        can_transition, reason = self.state_machine.validate_transition(
            approval_request.approval_status, ApprovalStatus.EXECUTED
        )
        if not can_transition:
            raise ValueError(reason)

        return ExecutionApprovalRequest(
            request_id=approval_request.request_id,
            recommendation_id=approval_request.recommendation_id,
            plan_id=approval_request.plan_id,
            account_id=approval_request.account_id,
            security_code=approval_request.security_code,
            side=approval_request.side,
            approval_status=ApprovalStatus.EXECUTED,
            suggested_quantity=approval_request.suggested_quantity,
            market_price_at_review=approval_request.market_price_at_review,
            price_range_low=approval_request.price_range_low,
            price_range_high=approval_request.price_range_high,
            stop_loss_price=approval_request.stop_loss_price,
            risk_check_results=approval_request.risk_check_results,
            reviewer_comments=approval_request.reviewer_comments,
            regime_source=approval_request.regime_source,
            created_at=approval_request.created_at,
            reviewed_at=approval_request.reviewed_at,
            executed_at=datetime.now(UTC),
        )

    def mark_failed(
        self,
        approval_request: ExecutionApprovalRequest,
        error_message: str,
    ) -> ExecutionApprovalRequest:
        """
        标记为执行失败

        Args:
            approval_request: 执行审批请求
            error_message: 错误信息

        Returns:
            更新后的 ExecutionApprovalRequest
        """
        # 验证状态迁移
        can_transition, reason = self.state_machine.validate_transition(
            approval_request.approval_status, ApprovalStatus.FAILED
        )
        if not can_transition:
            raise ValueError(reason)

        # 更新风控结果记录错误
        updated_risk_checks = dict(approval_request.risk_check_results)
        updated_risk_checks["execution_error"] = {
            "passed": False,
            "reason": error_message,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        return ExecutionApprovalRequest(
            request_id=approval_request.request_id,
            recommendation_id=approval_request.recommendation_id,
            plan_id=approval_request.plan_id,
            account_id=approval_request.account_id,
            security_code=approval_request.security_code,
            side=approval_request.side,
            approval_status=ApprovalStatus.FAILED,
            suggested_quantity=approval_request.suggested_quantity,
            market_price_at_review=approval_request.market_price_at_review,
            price_range_low=approval_request.price_range_low,
            price_range_high=approval_request.price_range_high,
            stop_loss_price=approval_request.stop_loss_price,
            risk_check_results=updated_risk_checks,
            reviewer_comments=approval_request.reviewer_comments,
            regime_source=approval_request.regime_source,
            created_at=approval_request.created_at,
            reviewed_at=approval_request.reviewed_at,
            executed_at=None,
        )


# ============================================================================
# 统一推荐模型参数管理（Top-down + Bottom-up 融合）
# ============================================================================

# 默认参数常量（仅用于兜底，不作为主配置）
DEFAULT_MODEL_PARAMS = {
    "alpha_model_weight": 0.40,
    "sentiment_weight": 0.15,
    "flow_weight": 0.15,
    "technical_weight": 0.15,
    "fundamental_weight": 0.15,
    "gate_penalty_cooldown": 0.10,
    "gate_penalty_quota": 0.10,
    "gate_penalty_volatility": 0.10,
    "composite_score_threshold": 0.60,
    "confidence_threshold": 0.70,
    "buy_score_threshold": 0.65,
    "buy_alpha_threshold": 0.60,
    "sell_score_threshold": 0.35,
    "sell_alpha_threshold": 0.30,
    "default_position_pct": 5.0,
    "max_capital_per_trade": 50000.0,
}


@dataclass(frozen=True)
class ModelWeights:
    """
    模型权重配置

    用于综合分计算的权重参数。

    Attributes:
        alpha_model_weight: Alpha 模型权重
        sentiment_weight: 舆情权重
        flow_weight: 资金流向权重
        technical_weight: 技术面权重
        fundamental_weight: 基本面权重
    """

    alpha_model_weight: float = 0.40
    sentiment_weight: float = 0.15
    flow_weight: float = 0.15
    technical_weight: float = 0.15
    fundamental_weight: float = 0.15

    def validate(self) -> tuple[bool, str]:
        """
        验证权重配置

        Returns:
            (是否有效, 错误消息)
        """
        weights = [
            self.alpha_model_weight,
            self.sentiment_weight,
            self.flow_weight,
            self.technical_weight,
            self.fundamental_weight,
        ]

        # 检查非负
        for w in weights:
            if w < 0:
                return False, "权重不能为负数"

        # 检查总和接近 1
        total = sum(weights)
        if abs(total - 1.0) > 0.01:
            return False, f"权重总和应为 1.0，当前为 {total:.2f}"

        return True, ""


@dataclass(frozen=True)
class GatePenalties:
    """
    Gate 惩罚参数

    用于风险惩罚项计算的参数。

    Attributes:
        cooldown_penalty: 冷却期不足惩罚
        quota_penalty: 配额紧张惩罚
        volatility_penalty: 波动超阈值惩罚
    """

    cooldown_penalty: float = 0.10
    quota_penalty: float = 0.10
    volatility_penalty: float = 0.10


class CompositeScoreCalculator:
    """
    综合分计算器

    实现"模型分数主导 + 规则约束兜底"的评分逻辑。

    综合分计算（默认）:
        composite_score = 0.40*alpha_model + 0.15*sentiment + 0.15*flow +
                         0.15*technical + 0.15*fundamental - penalties

    Hard Gate（必须通过）:
        - Beta Gate 不通过 -> 直接过滤
        - Regime/Policy 明确禁止 -> 直接过滤

    风险惩罚项（扣分）:
        - 冷却期不足、配额紧张、波动超阈值
    """

    def __init__(
        self,
        weights: ModelWeights | None = None,
        penalties: GatePenalties | None = None,
    ):
        """
        初始化综合分计算器

        Args:
            weights: 模型权重配置
            penalties: Gate 惩罚参数
        """
        self.weights = weights or ModelWeights()
        self.penalties = penalties or GatePenalties()

    def calculate(
        self,
        alpha_model_score: float,
        sentiment_score: float,
        flow_score: float,
        technical_score: float,
        fundamental_score: float,
        cooldown_violation: bool = False,
        quota_tight: bool = False,
        volatility_high: bool = False,
    ) -> tuple[float, list[str]]:
        """
        计算综合分

        Args:
            alpha_model_score: Alpha 模型分数
            sentiment_score: 舆情分数
            flow_score: 资金流向分数
            technical_score: 技术面分数
            fundamental_score: 基本面分数
            cooldown_violation: 是否违反冷却期
            quota_tight: 配额是否紧张
            volatility_high: 波动是否过高

        Returns:
            (综合分, 惩罚原因列表)
        """
        # 基础分数计算
        base_score = (
            self.weights.alpha_model_weight * alpha_model_score
            + self.weights.sentiment_weight * sentiment_score
            + self.weights.flow_weight * flow_score
            + self.weights.technical_weight * technical_score
            + self.weights.fundamental_weight * fundamental_score
        )

        # 风险惩罚项
        penalty = 0.0
        penalty_reasons = []

        if cooldown_violation:
            penalty += self.penalties.cooldown_penalty
            penalty_reasons.append("COOLDOWN_VIOLATION")

        if quota_tight:
            penalty += self.penalties.quota_penalty
            penalty_reasons.append("QUOTA_TIGHT")

        if volatility_high:
            penalty += self.penalties.volatility_penalty
            penalty_reasons.append("VOLATILITY_HIGH")

        # 最终分数（不低于 0）
        composite_score = max(0.0, base_score - penalty)

        return composite_score, penalty_reasons

    def calculate_from_snapshot(
        self,
        snapshot: "DecisionFeatureSnapshot",
        cooldown_violation: bool = False,
        quota_tight: bool = False,
        volatility_high: bool = False,
    ) -> tuple[float, list[str]]:
        """
        从特征快照计算综合分

        Args:
            snapshot: 决策特征快照
            cooldown_violation: 是否违反冷却期
            quota_tight: 配额是否紧张
            volatility_high: 波动是否过高

        Returns:
            (综合分, 惩罚原因列表)
        """
        return self.calculate(
            alpha_model_score=snapshot.alpha_model_score,
            sentiment_score=snapshot.sentiment_score,
            flow_score=snapshot.flow_score,
            technical_score=snapshot.technical_score,
            fundamental_score=snapshot.fundamental_score,
            cooldown_violation=cooldown_violation,
            quota_tight=quota_tight,
            volatility_high=volatility_high,
        )


class RecommendationAggregator:
    """
    推荐聚合器

    实现按 account_id + security_code + side 去重和冲突处理。

    聚合规则:
        1. 同键多来源: 合并 reason/source，保留最高置信/最近快照
        2. 同证券方向冲突: 不落可执行区，入 conflict_queue
    """

    def aggregate(
        self,
        recommendations: list["UnifiedRecommendation"],
    ) -> tuple[list["UnifiedRecommendation"], list["UnifiedRecommendation"], list["ConflictPair"]]:
        """
        聚合推荐列表

        Args:
            recommendations: 原始推荐列表

        Returns:
            (去重后的推荐列表, 冲突推荐列表, 冲突对列表)
        """
        from .entities import RecommendationStatus

        # 按聚合键分组
        groups: dict[str, list[UnifiedRecommendation]] = {}
        for rec in recommendations:
            key = rec.get_aggregation_key()
            if key not in groups:
                groups[key] = []
            groups[key].append(rec)

        # 处理每个分组
        deduplicated: list[UnifiedRecommendation] = []
        conflicts: list[UnifiedRecommendation] = []
        conflict_pairs: list[ConflictPair] = []

        for key, group in groups.items():
            if len(group) == 1:
                # 只有一个推荐，直接加入
                deduplicated.append(group[0])
            else:
                # 多个同键推荐，合并
                merged = self._merge_recommendations(group)
                deduplicated.append(merged)

        # 检测 BUY/SELL 冲突
        account_security_groups: dict[str, dict[str, list[UnifiedRecommendation]]] = {}
        for rec in deduplicated:
            as_key = f"{rec.account_id}|{rec.security_code}"
            if as_key not in account_security_groups:
                account_security_groups[as_key] = {}
            if rec.side not in account_security_groups[as_key]:
                account_security_groups[as_key][rec.side] = []
            account_security_groups[as_key][rec.side].append(rec)

        # 处理冲突
        final_recommendations: list[UnifiedRecommendation] = []
        for as_key, side_groups in account_security_groups.items():
            has_buy = "BUY" in side_groups and side_groups["BUY"]
            has_sell = "SELL" in side_groups and side_groups["SELL"]

            if has_buy and has_sell:
                # BUY/SELL 冲突
                buy_recs = side_groups["BUY"]
                sell_recs = side_groups["SELL"]

                for buy_rec in buy_recs:
                    conflicts.append(buy_rec)
                    for sell_rec in sell_recs:
                        conflict_pairs.append(
                            ConflictPair(
                                buy_recommendation=buy_rec,
                                sell_recommendation=sell_rec,
                            )
                        )

                for sell_rec in sell_recs:
                    if sell_rec not in conflicts:
                        conflicts.append(sell_rec)
            else:
                # 无冲突，加入最终列表
                for recs in side_groups.values():
                    final_recommendations.extend(recs)

        return final_recommendations, conflicts, conflict_pairs

    def _merge_recommendations(
        self,
        recommendations: list["UnifiedRecommendation"],
    ) -> "UnifiedRecommendation":
        """
        合并多个同键推荐

        策略: 保留最高置信/最近快照

        Args:
            recommendations: 同键推荐列表

        Returns:
            合并后的推荐
        """
        if len(recommendations) == 1:
            return recommendations[0]

        # 按置信度排序，取最高的
        sorted_recs = sorted(
            recommendations,
            key=lambda r: (r.confidence, r.created_at),
            reverse=True,
        )

        best = sorted_recs[0]

        # 合并 reason_codes 和 source
        all_reason_codes: list[str] = []
        all_source_signal_ids: list[str] = []
        all_source_candidate_ids: list[str] = []

        for rec in recommendations:
            all_reason_codes.extend(rec.reason_codes)
            all_source_signal_ids.extend(rec.source_signal_ids)
            all_source_candidate_ids.extend(rec.source_candidate_ids)

        # 去重
        unique_reason_codes = list(set(all_reason_codes))
        unique_source_signal_ids = list(set(all_source_signal_ids))
        unique_source_candidate_ids = list(set(all_source_candidate_ids))

        # 创建合并后的推荐（使用 best 的其他属性）
        from .entities import UnifiedRecommendation

        return UnifiedRecommendation(
            recommendation_id=best.recommendation_id,
            account_id=best.account_id,
            security_code=best.security_code,
            side=best.side,
            regime=best.regime,
            regime_confidence=best.regime_confidence,
            policy_level=best.policy_level,
            beta_gate_passed=best.beta_gate_passed,
            sentiment_score=best.sentiment_score,
            flow_score=best.flow_score,
            technical_score=best.technical_score,
            fundamental_score=best.fundamental_score,
            alpha_model_score=best.alpha_model_score,
            composite_score=best.composite_score,
            confidence=best.confidence,
            reason_codes=unique_reason_codes,
            human_rationale=best.human_rationale,
            fair_value=best.fair_value,
            entry_price_low=best.entry_price_low,
            entry_price_high=best.entry_price_high,
            target_price_low=best.target_price_low,
            target_price_high=best.target_price_high,
            stop_loss_price=best.stop_loss_price,
            position_pct=best.position_pct,
            suggested_quantity=best.suggested_quantity,
            max_capital=best.max_capital,
            source_signal_ids=unique_source_signal_ids,
            source_candidate_ids=unique_source_candidate_ids,
            feature_snapshot_id=best.feature_snapshot_id,
            status=best.status,
            created_at=best.created_at,
            updated_at=datetime.now(UTC),
        )


@dataclass
class ConflictPair:
    """
    冲突对

    表示同证券 BUY/SELL 冲突。

    Attributes:
        buy_recommendation: BUY 方向的推荐
        sell_recommendation: SELL 方向的推荐
    """

    buy_recommendation: "UnifiedRecommendation"
    sell_recommendation: "UnifiedRecommendation"
