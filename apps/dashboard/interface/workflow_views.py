"""Dashboard workflow interaction views."""

from __future__ import annotations

import logging

from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from rest_framework.request import Request

from apps.dashboard.application.queries import get_dashboard_detail_query
from apps.dashboard.interface.api_auth import dashboard_api_view

logger = logging.getLogger(__name__)


@dashboard_api_view(["POST"])
def workflow_refresh_candidates(request: Request) -> HttpResponse:
    """
    主流程候选刷新：从活跃触发器补齐候选，并尝试提升高置信候选为 ACTIONABLE。
    """

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        result = get_dashboard_detail_query().generate_alpha_candidates()
        return JsonResponse({"success": True, "result": result})
    except Exception as exc:
        logger.error(
            "Failed to refresh workflow candidates (error_type=%s)",
            type(exc).__name__,
        )
        return JsonResponse(
            {"success": False, "error": "workflow_candidate_refresh_failed"},
            status=500,
        )
