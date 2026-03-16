"""
Unit Tests for M4 WP-M4-03: Failure Classification And Recovery.

Tests verify:
- All 6 failure types are classified correctly
- Retryability flags are accurate
- Recovery advice is deterministic
- Unknown errors default to unknown_system_error
"""

import pytest

from apps.agent_runtime.domain.failure_classifier import (
    FailureType,
    FailureClassification,
    classify_failure,
)


class TestValidationError:
    def test_invalid_keyword(self):
        result = classify_failure("Invalid task_domain. Must be one of: [...]")
        assert result.failure_type == FailureType.VALIDATION_ERROR
        assert result.retryable is False
        assert result.human_required is False

    def test_required_field_keyword(self):
        result = classify_failure("required field missing: proposal_type")
        assert result.failure_type == FailureType.VALIDATION_ERROR

    def test_validation_error_code(self):
        result = classify_failure("Bad request", error_code="validation_error")
        assert result.failure_type == FailureType.VALIDATION_ERROR


class TestDependencyUnavailable:
    def test_connection_keyword(self):
        result = classify_failure("Connection refused to regime API")
        assert result.failure_type == FailureType.DEPENDENCY_UNAVAILABLE
        assert result.retryable is True
        assert result.human_required is False

    def test_timeout_keyword(self):
        result = classify_failure("Request timeout after 30s")
        assert result.failure_type == FailureType.DEPENDENCY_UNAVAILABLE

    def test_503_keyword(self):
        result = classify_failure("HTTP 503 Service Unavailable")
        assert result.failure_type == FailureType.DEPENDENCY_UNAVAILABLE


class TestDataStale:
    def test_stale_keyword(self):
        result = classify_failure("Macro data is stale (last update: 3 days ago)")
        assert result.failure_type == FailureType.DATA_STALE
        assert result.retryable is True

    def test_freshness_keyword(self):
        result = classify_failure("Data freshness check failed for sentiment")
        assert result.failure_type == FailureType.DATA_STALE


class TestAuthorizationBlocked:
    def test_permission_keyword(self):
        result = classify_failure("Permission denied for signal_create")
        assert result.failure_type == FailureType.AUTHORIZATION_BLOCKED
        assert result.retryable is False
        assert result.human_required is True

    def test_forbidden_keyword(self):
        result = classify_failure("403 Forbidden")
        assert result.failure_type == FailureType.AUTHORIZATION_BLOCKED

    def test_guardrail_blocked_keyword(self):
        result = classify_failure("Action blocked", error_code="guardrail_blocked")
        assert result.failure_type == FailureType.AUTHORIZATION_BLOCKED


class TestExecutionFailure:
    def test_execution_keyword(self):
        result = classify_failure("Failed to execute trade order")
        assert result.failure_type == FailureType.EXECUTION_FAILURE
        assert result.retryable is True
        assert result.human_required is True

    def test_execution_failed_keyword(self):
        result = classify_failure("Task execution_failed during position adjustment")
        assert result.failure_type == FailureType.EXECUTION_FAILURE


class TestUnknownSystemError:
    def test_unrecognized_error(self):
        result = classify_failure("Something completely unexpected happened")
        assert result.failure_type == FailureType.UNKNOWN_SYSTEM_ERROR
        assert result.retryable is False
        assert result.human_required is True

    def test_empty_error(self):
        result = classify_failure("")
        assert result.failure_type == FailureType.UNKNOWN_SYSTEM_ERROR


class TestClassificationOutput:
    def test_to_dict_has_all_fields(self):
        result = classify_failure("Connection timeout", evidence={"service": "regime"})
        d = result.to_dict()
        assert "failure_type" in d
        assert "retryable" in d
        assert "recommended_action" in d
        assert "human_required" in d
        assert "original_error" in d
        assert "evidence" in d
        assert d["evidence"]["service"] == "regime"

    def test_original_error_preserved(self):
        msg = "Very specific error: XYZ"
        result = classify_failure(msg)
        assert result.original_error == msg

    def test_evidence_defaults_empty(self):
        result = classify_failure("test")
        assert result.to_dict()["evidence"] == {}
