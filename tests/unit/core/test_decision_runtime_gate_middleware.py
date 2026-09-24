"""Decision maintenance middleware contracts."""

import json
from datetime import UTC, datetime

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from apps.config_center.domain.entities import DecisionRuntimeState, DecisionRuntimeStatus
from core.middleware.decision_gate import DecisionRuntimeGateMiddleware


def test_non_decision_path_remains_available_during_maintenance(mocker) -> None:
    execute = mocker.patch("core.middleware.decision_gate.GetDecisionRuntimeStateUseCase.execute")
    middleware = DecisionRuntimeGateMiddleware(lambda request: HttpResponse("ok"))

    response = middleware(RequestFactory().get("/api/ready/"))

    assert response.status_code == 200
    execute.assert_not_called()


def test_decision_path_is_blocked_during_maintenance(mocker) -> None:
    mocker.patch(
        "core.middleware.decision_gate.GetDecisionRuntimeStateUseCase.execute",
        return_value=DecisionRuntimeState(
            status=DecisionRuntimeStatus.MAINTENANCE,
            reason="全市场数据重建中",
            changed_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            changed_by="deploy:test",
        ),
    )
    downstream = mocker.Mock(return_value=HttpResponse("unsafe"))
    middleware = DecisionRuntimeGateMiddleware(downstream)

    response = middleware(RequestFactory().post("/api/terminal/chat/"))

    assert response.status_code == 503
    payload = json.loads(response.content)
    assert payload["block_reason_code"] == "decision_runtime_maintenance"
    assert payload["block_reason"] == (
        "系统正在维护决策数据，当前结果不可用于投资决策。请等待维护完成后重试。"
    )
    assert payload["next_action"] == "等待系统维护完成后重试"
    assert payload["responsible_role"] == "系统运维"
    downstream.assert_not_called()


@pytest.mark.parametrize(
    ("status", "expected_role"),
    (
        (DecisionRuntimeStatus.MAINTENANCE, "系统运维"),
        (DecisionRuntimeStatus.VALIDATING, "数据运维"),
        (DecisionRuntimeStatus.BLOCKED, "系统管理员"),
    ),
)
def test_decision_gate_redacts_internal_runtime_reason(mocker, status, expected_role) -> None:
    """Public runtime errors keep stable guidance and never expose audit diagnostics."""

    internal_reason = "INTERNAL_DIAGNOSTIC_FIXTURE credential detail"
    mocker.patch(
        "core.middleware.decision_gate.GetDecisionRuntimeStateUseCase.execute",
        return_value=DecisionRuntimeState(
            status=status,
            reason=internal_reason,
            changed_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            changed_by="deploy:test",
            release_ref="release-test",
        ),
    )
    downstream = mocker.Mock(return_value=HttpResponse("unsafe"))

    response = DecisionRuntimeGateMiddleware(downstream)(
        RequestFactory().get("/api/regime/current/")
    )
    payload = json.loads(response.content)

    assert response.status_code == 503
    assert payload["block_reason_code"] == f"decision_runtime_{status.value}"
    assert internal_reason not in payload["block_reason"]
    assert payload["responsible_role"] == expected_role
    assert payload["next_action"]
    downstream.assert_not_called()


def test_decision_path_passes_when_runtime_is_active(mocker) -> None:
    mocker.patch(
        "core.middleware.decision_gate.GetDecisionRuntimeStateUseCase.execute",
        return_value=DecisionRuntimeState(status=DecisionRuntimeStatus.ACTIVE),
    )
    middleware = DecisionRuntimeGateMiddleware(lambda request: HttpResponse("ok"))

    response = middleware(RequestFactory().post("/api/ai-capability/route/"))

    assert response.status_code == 200
