"""Public decision-runtime diagnostics must remain actionable and sanitized."""

from datetime import UTC, datetime

from apps.config_center.domain.entities import DecisionRuntimeState, DecisionRuntimeStatus
from core import health_checks


def test_readiness_runtime_projection_redacts_internal_reason(mocker) -> None:
    """The anonymous readiness payload must not expose the persisted audit reason."""

    internal_reason = "INTERNAL_DIAGNOSTIC_FIXTURE credential detail"
    mocker.patch(
        "apps.config_center.application.use_cases.GetDecisionRuntimeStateUseCase.execute",
        return_value=DecisionRuntimeState(
            status=DecisionRuntimeStatus.BLOCKED,
            reason=internal_reason,
            changed_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            changed_by="deploy:test",
            release_ref="release-test",
        ),
    )

    payload = health_checks.check_decision_runtime_state()

    assert payload["status"] == "blocked"
    assert payload["block_reason_code"] == "decision_runtime_blocked"
    assert internal_reason not in str(payload)
    assert payload["block_reason"]
    assert payload["next_action"]
    assert payload["responsible_role"] == "系统管理员"


def test_readiness_runtime_projection_redacts_read_failure(mocker) -> None:
    """A read failure keeps details in logs and returns only safe public guidance."""

    internal_error = "INTERNAL_DIAGNOSTIC_FIXTURE database credential"
    mocker.patch(
        "apps.config_center.application.use_cases.GetDecisionRuntimeStateUseCase.execute",
        side_effect=RuntimeError(internal_error),
    )

    payload = health_checks.check_decision_runtime_state()

    assert payload["status"] == "error"
    assert payload["block_reason_code"] == "decision_runtime_state_unavailable"
    assert internal_error not in str(payload)
    assert payload["block_reason"]
    assert payload["next_action"]
