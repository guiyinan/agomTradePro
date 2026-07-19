"""
Workflow state machines and precheck results for Decision Rhythm.

决策编排的预检查结果、执行结果与状态机（执行状态、候选状态、审批状态）。

仅使用 Python 标准库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .entities import ApprovalStatus


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


__all__ = [
    "ApprovalStatusStateMachine",
    "CandidateStatusStateMachine",
    "ExecutionResult",
    "ExecutionStatusStateMachine",
    "PrecheckResult",
]
