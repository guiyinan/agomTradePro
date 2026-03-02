"""
Unit tests for decision_rhythm execution tracking fields.

Tests for:
- ExecutionTarget enum values
- ExecutionStatus enum values
- DecisionRequest state machine consistency
- DecisionRequest new field validation
"""

from datetime import datetime, timezone

import pytest

from apps.decision_rhythm.domain.entities import (
    DecisionRequest,
    DecisionPriority,
    ExecutionTarget,
    ExecutionStatus,
)


class TestExecutionTargetEnum:
    """测试 ExecutionTarget 枚举"""

    def test_none_value(self):
        """测试 NONE 值"""
        assert ExecutionTarget.NONE.value == "NONE"

    def test_simulated_value(self):
        """测试 SIMULATED 值"""
        assert ExecutionTarget.SIMULATED.value == "SIMULATED"

    def test_account_value(self):
        """测试 ACCOUNT 值"""
        assert ExecutionTarget.ACCOUNT.value == "ACCOUNT"

    def test_all_values_are_uppercase(self):
        """测试所有值都是大写"""
        for member in ExecutionTarget:
            assert member.value == member.value.upper()

    def test_from_string(self):
        """测试从字符串创建枚举"""
        assert ExecutionTarget("NONE") == ExecutionTarget.NONE
        assert ExecutionTarget("SIMULATED") == ExecutionTarget.SIMULATED
        assert ExecutionTarget("ACCOUNT") == ExecutionTarget.ACCOUNT

    def test_invalid_string_raises_error(self):
        """测试无效字符串抛出错误"""
        with pytest.raises(ValueError):
            ExecutionTarget("INVALID")


class TestExecutionStatusEnum:
    """测试 ExecutionStatus 枚举"""

    def test_pending_value(self):
        """测试 PENDING 值"""
        assert ExecutionStatus.PENDING.value == "PENDING"

    def test_executed_value(self):
        """测试 EXECUTED 值"""
        assert ExecutionStatus.EXECUTED.value == "EXECUTED"

    def test_failed_value(self):
        """测试 FAILED 值"""
        assert ExecutionStatus.FAILED.value == "FAILED"

    def test_cancelled_value(self):
        """测试 CANCELLED 值"""
        assert ExecutionStatus.CANCELLED.value == "CANCELLED"

    def test_all_values_are_uppercase(self):
        """测试所有值都是大写"""
        for member in ExecutionStatus:
            assert member.value == member.value.upper()

    def test_from_string(self):
        """测试从字符串创建枚举"""
        assert ExecutionStatus("PENDING") == ExecutionStatus.PENDING
        assert ExecutionStatus("EXECUTED") == ExecutionStatus.EXECUTED
        assert ExecutionStatus("FAILED") == ExecutionStatus.FAILED
        assert ExecutionStatus("CANCELLED") == ExecutionStatus.CANCELLED

    def test_invalid_string_raises_error(self):
        """测试无效字符串抛出错误"""
        with pytest.raises(ValueError):
            ExecutionStatus("INVALID")


class TestDecisionRequestExecutionFields:
    """测试 DecisionRequest 新字段"""

    def test_default_execution_target_is_none(self):
        """测试默认执行目标是 NONE"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
        )
        assert request.execution_target == ExecutionTarget.NONE

    def test_default_execution_status_is_pending(self):
        """测试默认执行状态是 PENDING"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
        )
        assert request.execution_status == ExecutionStatus.PENDING

    def test_default_candidate_id_is_none(self):
        """测试默认候选 ID 是 None"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
        )
        assert request.candidate_id is None

    def test_default_executed_at_is_none(self):
        """测试默认执行时间是 None"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
        )
        assert request.executed_at is None

    def test_default_execution_ref_is_none(self):
        """测试默认执行引用是 None"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
        )
        assert request.execution_ref is None

    def test_can_set_candidate_id(self):
        """测试可以设置候选 ID"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            candidate_id="cand_001",
        )
        assert request.candidate_id == "cand_001"

    def test_can_set_execution_target(self):
        """测试可以设置执行目标"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_target=ExecutionTarget.SIMULATED,
        )
        assert request.execution_target == ExecutionTarget.SIMULATED

    def test_can_set_execution_status(self):
        """测试可以设置执行状态"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_status=ExecutionStatus.EXECUTED,
        )
        assert request.execution_status == ExecutionStatus.EXECUTED

    def test_can_set_execution_ref(self):
        """测试可以设置执行引用"""
        exec_ref = {"trade_id": "trade_001", "account_id": 1}
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_ref=exec_ref,
        )
        assert request.execution_ref == exec_ref


class TestDecisionRequestStateMachine:
    """测试 DecisionRequest 状态机一致性"""

    def test_validate_executed_status_with_executed_at_is_valid(self):
        """测试 EXECUTED 状态有 executed_at 是有效的"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_status=ExecutionStatus.EXECUTED,
            executed_at=datetime.now(timezone.utc),
        )
        assert request.validate_execution_consistency() is True

    def test_validate_executed_status_without_executed_at_is_invalid(self):
        """测试 EXECUTED 状态没有 executed_at 是无效的"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_status=ExecutionStatus.EXECUTED,
            executed_at=None,
        )
        assert request.validate_execution_consistency() is False

    def test_validate_none_target_without_execution_ref_is_valid(self):
        """测试 NONE 目标没有 execution_ref 是有效的"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_target=ExecutionTarget.NONE,
            execution_ref=None,
        )
        assert request.validate_execution_consistency() is True

    def test_validate_none_target_with_execution_ref_is_invalid(self):
        """测试 NONE 目标有 execution_ref 是无效的"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_target=ExecutionTarget.NONE,
            execution_ref={"trade_id": "trade_001"},
        )
        assert request.validate_execution_consistency() is False

    def test_validate_simulated_target_with_execution_ref_is_valid(self):
        """测试 SIMULATED 目标有 execution_ref 是有效的"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_target=ExecutionTarget.SIMULATED,
            execution_ref={"position_id": 123, "portfolio_id": 9},
        )
        assert request.validate_execution_consistency() is True

    def test_validate_account_target_with_execution_ref_is_valid(self):
        """测试 ACCOUNT 目标有 execution_ref 是有效的"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_target=ExecutionTarget.ACCOUNT,
            execution_ref={"trade_id": "trade_001", "account_id": 1},
        )
        assert request.validate_execution_consistency() is True

    def test_validate_pending_status_without_executed_at_is_valid(self):
        """测试 PENDING 状态没有 executed_at 是有效的"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_status=ExecutionStatus.PENDING,
            executed_at=None,
        )
        assert request.validate_execution_consistency() is True


class TestDecisionRequestProperties:
    """测试 DecisionRequest 新属性"""

    def test_is_executed_when_executed(self):
        """测试已执行状态"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_status=ExecutionStatus.EXECUTED,
        )
        assert request.is_executed is True

    def test_is_executed_when_pending(self):
        """测试待执行状态"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_status=ExecutionStatus.PENDING,
        )
        assert request.is_executed is False

    def test_is_execution_pending_when_pending(self):
        """测试待执行状态"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_status=ExecutionStatus.PENDING,
        )
        assert request.is_execution_pending is True

    def test_is_execution_pending_when_executed(self):
        """测试已执行不是待执行"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_status=ExecutionStatus.EXECUTED,
        )
        assert request.is_execution_pending is False

    def test_has_execution_target_when_none(self):
        """测试无执行目标"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_target=ExecutionTarget.NONE,
        )
        assert request.has_execution_target is False

    def test_has_execution_target_when_simulated(self):
        """测试有执行目标（模拟盘）"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_target=ExecutionTarget.SIMULATED,
        )
        assert request.has_execution_target is True

    def test_has_execution_target_when_account(self):
        """测试有执行目标（实盘）"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            execution_target=ExecutionTarget.ACCOUNT,
        )
        assert request.has_execution_target is True


class TestDecisionRequestToDict:
    """测试 DecisionRequest 序列化包含新字段"""

    def test_to_dict_includes_new_fields(self):
        """测试 to_dict 包含新字段"""
        request = DecisionRequest(
            request_id="req_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            candidate_id="cand_001",
            execution_target=ExecutionTarget.SIMULATED,
            execution_status=ExecutionStatus.EXECUTED,
            executed_at=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            execution_ref={"trade_id": "trade_001"},
        )
        result = request.to_dict()

        assert result["candidate_id"] == "cand_001"
        assert result["execution_target"] == "SIMULATED"
        assert result["execution_status"] == "EXECUTED"
        assert result["executed_at"] is not None
        assert result["execution_ref"] == {"trade_id": "trade_001"}
        assert result["is_executed"] is True
        assert result["is_execution_pending"] is False
        assert result["has_execution_target"] is True
