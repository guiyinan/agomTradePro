"""Dashboard workflow interaction views."""

from __future__ import annotations

from django.http import HttpResponseNotAllowed, JsonResponse

from apps.dashboard.interface.api_auth import dashboard_api_view


def _dashboard_views():
    from apps.dashboard.interface import views as dashboard_views

    return dashboard_views


@dashboard_api_view(["POST"])
def workflow_refresh_candidates(request):
    """
    主流程候选刷新：从活跃触发器补齐候选，并尝试提升高置信候选为 ACTIONABLE。
    """

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    dashboard_views = _dashboard_views()
    try:
        result = dashboard_views.get_dashboard_detail_query().generate_alpha_candidates()
        return JsonResponse({"success": True, "result": result})
    except Exception as exc:
        dashboard_views.logger.error(
            "Failed to refresh workflow candidates: %s",
            exc,
            exc_info=True,
        )
        return JsonResponse({"success": False, "error": str(exc)}, status=500)
