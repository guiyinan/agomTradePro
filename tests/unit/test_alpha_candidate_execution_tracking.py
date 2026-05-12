"""
Unit tests for alpha_trigger AlphaCandidate execution tracking fields.

Tests for:
- AlphaCandidate new fields (last_decision_request_id, last_execution_status)
- AlphaCandidate new properties (is_executed, has_decision_request)
- AlphaCandidate serialization with new fields
"""



from apps.alpha_trigger.domain.entities import (
    AlphaCandidate,
    CandidateStatus,
    SignalStrength,
)


def _create_candidate(**kwargs) -> AlphaCandidate:
    """创建测试用的 AlphaCandidate 实例"""
    defaults = {
        "candidate_id": "cand_001",
        "trigger_id": "trigger_001",
        "asset_code": "000001.SH",
        "asset_class": "a_share_financial",
        "direction": "LONG",
        "strength": SignalStrength.STRONG,
        "confidence": 0.75,
        "thesis": "PMI 回升，经济复苏预期增强",
    }
    defaults.update(kwargs)
    return AlphaCandidate(**defaults)


class TestAlphaCandidateNewFields:
    """测试 AlphaCandidate 新字段"""

    def test_default_last_decision_request_id_is_none(self):
        """测试默认 last_decision_request_id 是 None"""
        candidate = _create_candidate()
        assert candidate.last_decision_request_id is None

    def test_default_last_execution_status_is_none(self):
        """测试默认 last_execution_status 是 None"""
        candidate = _create_candidate()
        assert candidate.last_execution_status is None

    def test_can_set_last_decision_request_id(self):
        """测试可以设置 last_decision_request_id"""
        candidate = _create_candidate(last_decision_request_id="req_001")
        assert candidate.last_decision_request_id == "req_001"

    def test_can_set_last_execution_status(self):
        """测试可以设置 last_execution_status"""
        candidate = _create_candidate(last_execution_status="EXECUTED")
        assert candidate.last_execution_status == "EXECUTED"

    def test_can_set_both_new_fields(self):
        """测试可以同时设置两个新字段"""
        candidate = _create_candidate(
            last_decision_request_id="req_001",
            last_execution_status="EXECUTED",
        )
        assert candidate.last_decision_request_id == "req_001"
        assert candidate.last_execution_status == "EXECUTED"


class TestAlphaCandidateNewProperties:
    """测试 AlphaCandidate 新属性"""

    def test_is_executed_when_status_is_executed(self):
        """测试状态为 EXECUTED 时 is_executed 为 True"""
        candidate = _create_candidate(status=CandidateStatus.EXECUTED)
        assert candidate.is_executed is True

    def test_is_executed_when_status_is_actionable(self):
        """测试状态为 ACTIONABLE 时 is_executed 为 False"""
        candidate = _create_candidate(status=CandidateStatus.ACTIONABLE)
        assert candidate.is_executed is False

    def test_is_executed_when_status_is_watch(self):
        """测试状态为 WATCH 时 is_executed 为 False"""
        candidate = _create_candidate(status=CandidateStatus.WATCH)
        assert candidate.is_executed is False

    def test_is_executed_with_string_status(self):
        """测试字符串状态 EXECUTED 时 is_executed 为 True"""
        candidate = _create_candidate(status="EXECUTED")
        # 注意：__post_init__ 会尝试转换为枚举
        assert candidate.is_executed is True

    def test_has_decision_request_when_set(self):
        """测试有决策请求时 has_decision_request 为 True"""
        candidate = _create_candidate(last_decision_request_id="req_001")
        assert candidate.has_decision_request is True

    def test_has_decision_request_when_not_set(self):
        """测试没有决策请求时 has_decision_request 为 False"""
        candidate = _create_candidate()
        assert candidate.has_decision_request is False

    def test_has_decision_request_when_empty_string(self):
        """测试空字符串时 has_decision_request 为 False"""
        candidate = _create_candidate(last_decision_request_id="")
        # 空字符串被视为 None/False
        assert candidate.has_decision_request is False


class TestAlphaCandidateToDict:
    """测试 AlphaCandidate 序列化包含新字段"""

    def test_to_dict_includes_new_fields(self):
        """测试 to_dict 包含新字段"""
        candidate = _create_candidate(
            last_decision_request_id="req_001",
            last_execution_status="EXECUTED",
        )
        result = candidate.to_dict()

        assert result["last_decision_request_id"] == "req_001"
        assert result["last_execution_status"] == "EXECUTED"
        assert result["is_executed"] is False  # status 不是 EXECUTED
        assert result["has_decision_request"] is True

    def test_to_dict_includes_is_executed(self):
        """测试 to_dict 包含 is_executed"""
        candidate = _create_candidate(status=CandidateStatus.EXECUTED)
        result = candidate.to_dict()

        assert result["is_executed"] is True

    def test_to_dict_includes_has_decision_request(self):
        """测试 to_dict 包含 has_decision_request"""
        candidate = _create_candidate(last_decision_request_id="req_001")
        result = candidate.to_dict()

        assert result["has_decision_request"] is True

    def test_to_dict_with_none_values(self):
        """测试 to_dict 处理 None 值"""
        candidate = _create_candidate()
        result = candidate.to_dict()

        assert result["last_decision_request_id"] is None
        assert result["last_execution_status"] is None
        assert result["has_decision_request"] is False


class TestAlphaCandidateStatusTransition:
    """测试 AlphaCandidate 状态转换规则"""

    def test_actionable_can_become_executed(self):
        """测试 ACTIONABLE 可以变成 EXECUTED"""
        candidate = _create_candidate(status=CandidateStatus.ACTIONABLE)
        # 在实际应用中，状态转换由 Application 层控制
        # 这里只测试实体层面的状态值
        assert candidate.status == CandidateStatus.ACTIONABLE
        assert candidate.is_actionable is True

    def test_executed_candidate_has_is_executed_true(self):
        """测试 EXECUTED 状态的候选 is_executed 为 True"""
        candidate = _create_candidate(
            status=CandidateStatus.EXECUTED,
            last_execution_status="EXECUTED",
        )
        assert candidate.is_executed is True

    def test_candidate_with_decision_request_can_track_it(self):
        """测试有决策请求的候选可以追踪请求 ID"""
        candidate = _create_candidate(
            status=CandidateStatus.ACTIONABLE,
            last_decision_request_id="req_001",
        )
        assert candidate.has_decision_request is True
        assert candidate.last_decision_request_id == "req_001"


class TestAlphaCandidateExecutionStatusValues:
    """测试 AlphaCandidate 执行状态的有效值"""

    def test_execution_status_pending(self):
        """测试 PENDING 执行状态"""
        candidate = _create_candidate(last_execution_status="PENDING")
        assert candidate.last_execution_status == "PENDING"

    def test_execution_status_executed(self):
        """测试 EXECUTED 执行状态"""
        candidate = _create_candidate(last_execution_status="EXECUTED")
        assert candidate.last_execution_status == "EXECUTED"

    def test_execution_status_failed(self):
        """测试 FAILED 执行状态"""
        candidate = _create_candidate(last_execution_status="FAILED")
        assert candidate.last_execution_status == "FAILED"

    def test_execution_status_cancelled(self):
        """测试 CANCELLED 执行状态"""
        candidate = _create_candidate(last_execution_status="CANCELLED")
        assert candidate.last_execution_status == "CANCELLED"

    def test_execution_status_unknown_legacy(self):
        """测试 UNKNOWN_LEGACY 执行状态（历史数据回填）"""
        candidate = _create_candidate(last_execution_status="UNKNOWN_LEGACY")
        assert candidate.last_execution_status == "UNKNOWN_LEGACY"
