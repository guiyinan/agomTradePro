"""Decision maintenance middleware contracts."""

import json
from datetime import UTC, datetime

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
    assert json.loads(response.content)["block_reason_code"] == "decision_runtime_maintenance"
    downstream.assert_not_called()


def test_decision_path_passes_when_runtime_is_active(mocker) -> None:
    mocker.patch(
        "core.middleware.decision_gate.GetDecisionRuntimeStateUseCase.execute",
        return_value=DecisionRuntimeState(status=DecisionRuntimeStatus.ACTIVE),
    )
    middleware = DecisionRuntimeGateMiddleware(lambda request: HttpResponse("ok"))

    response = middleware(RequestFactory().post("/api/ai-capability/route/"))

    assert response.status_code == 200
