"""
Decision Rhythm Domain Services

决策频率约束和配额管理的核心业务逻辑实现。
提供稀疏决策的调度算法。

仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from .entities import (
    DecisionQuota,
    CooldownPeriod,
    DecisionRequest,
    DecisionResponse,
    RhythmConfig,
    DecisionPriority,
    QuotaPeriod,
    QuotaStatus,
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
    available_at: Optional[datetime] = None


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
    ready_at: Optional[datetime] = None
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

    def __init__(self, config: Optional[RhythmConfig] = None):
        """
        初始化配额管理器

        Args:
            config: 节奏配置
        """
        self.config = config or get_default_rhythm_config()
        self.quotas: Dict[QuotaPeriod, DecisionQuota] = {
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

    def get_quota_status(self, period: QuotaPeriod) -> Dict[str, Any]:
        """获取配额状态"""
        quota = self.quotas.get(period)
        if quota is None:
            return {}

        return quota.to_dict()

    def get_all_quota_statuses(self) -> Dict[str, Dict[str, Any]]:
        """获取所有配额状态"""
        return {
            period.value: self.get_quota_status(period)
            for period in QuotaPeriod
        }


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

    def __init__(self, default_config: Optional[CooldownPeriod] = None):
        """
        初始化冷却期管理器

        Args:
            default_config: 默认冷却配置
        """
        self.default_config = default_config or CooldownPeriod(asset_code="*")
        self.cooldowns: Dict[str, CooldownPeriod] = {}

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
                ready_at = cooldown.last_execution_at + timedelta(hours=cooldown.min_execution_interval_hours)
                return CooldownCheckResult(
                    passed=False,
                    reason=f"执行冷却期内，剩余 {cooldown.execution_ready_in_hours:.1f} 小时",
                    ready_at=ready_at,
                    wait_hours=cooldown.execution_ready_in_hours,
                )
        else:
            # 检查决策冷却
            if not cooldown.is_decision_ready:
                ready_at = cooldown.last_decision_at + timedelta(hours=cooldown.min_decision_interval_hours)
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
        quota_manager: Optional[QuotaManager] = None,
        cooldown_manager: Optional[CooldownManager] = None,
        config: Optional[RhythmConfig] = None,
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
        requests: List[DecisionRequest],
        quota_period: QuotaPeriod = QuotaPeriod.WEEKLY,
    ) -> List[DecisionResponse]:
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
        return datetime.now()

    def get_summary(self) -> Dict[str, Any]:
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
        self.queue: List[DecisionRequest] = []
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

    def get_next(self) -> Optional[DecisionRequest]:
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

    def get_queue_summary(self) -> Dict[str, Any]:
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


def check_quota_status(period: QuotaPeriod) -> Dict[str, Any]:
    """
    检查配额状态的便捷函数

    Args:
        period: 配额周期

    Returns:
        配额状态
    """
    manager = QuotaManager()
    return manager.get_quota_status(period)


def check_cooldown_status(asset_code: str) -> Dict[str, Any]:
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
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

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
    executed_at: Optional[datetime] = None
    execution_ref: Optional[Dict[str, Any]] = None
    candidate_status: Optional[str] = None
    error: Optional[str] = None

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
    def validate_transition(cls, from_status: str, to_status: str) -> Tuple[bool, str]:
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
    def validate_transition(cls, from_status: str, to_status: str, via_api: bool = False) -> Tuple[bool, str]:
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
