"""Fail-closed HTTP gate for decision-facing surfaces during data maintenance."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.config_center.application.use_cases import GetDecisionRuntimeStateUseCase

DECISION_PATH_PREFIXES = (
    "/api/terminal/chat/",
    "/api/ai-capability/route/",
    "/api/chat/web/",
    "/api/realtime/market-summary/",
    "/api/equity/",
    "/api/valuation/",
    "/api/regime/current/",
    "/api/regime/action/",
    "/api/pulse/current/",
    "/api/decision-funnel/",
    "/api/agent-runtime/context/decision/",
)


class DecisionRuntimeGateMiddleware:
    """Block decision responses while keeping operations and repair APIs available."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not request.path.startswith(DECISION_PATH_PREFIXES):
            return self.get_response(request)
        try:
            state = GetDecisionRuntimeStateUseCase().execute()
        except Exception:
            return JsonResponse(
                {
                    "status": "failed",
                    "must_not_use_for_decision": True,
                    "block_reason_code": "decision_runtime_state_unavailable",
                    "block_reason": "无法验证决策运行状态，已按安全策略阻断。",
                },
                status=503,
            )
        if not state.must_not_use_for_decision:
            return self.get_response(request)
        return JsonResponse(
            {
                "status": state.status.value,
                "must_not_use_for_decision": True,
                "block_reason_code": state.block_reason_code,
                "block_reason": state.reason,
                "changed_at": state.changed_at.isoformat() if state.changed_at else None,
                "release_ref": state.release_ref,
            },
            status=503,
        )
