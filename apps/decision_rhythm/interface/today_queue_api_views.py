"""API views for the daily decision queue."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.decision_rhythm.application.today_queue import TodayDecisionQueueQueryService
from apps.simulated_trading.application.interface_services import get_account_access


class TodayDecisionQueueView(APIView):
    """GET /api/decision/workspace/today-queue/"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return the current user's account-level daily decision queue."""

        account_id = str(request.query_params.get("account_id") or "default").strip() or "default"
        if account_id != "default" and not account_id.isdigit():
            return Response(
                {"success": False, "error": "account_id is invalid"},
                status=400,
            )
        if len(account_id) > 64:
            return Response(
                {"success": False, "error": "account_id is invalid"},
                status=400,
            )
        if account_id.isdigit():
            access = get_account_access(request.user, int(account_id), action="查看")
            if access.error:
                return Response(
                    {"success": False, "error": access.error},
                    status=access.status_code,
                )
        # System health has dedicated TUI governance panels. Keeping those remote
        # probes out of the P0 business queue avoids blocking the first useful
        # paint on Celery and Alpha readiness checks.
        result = TodayDecisionQueueQueryService().execute(
            account_id=account_id,
            include_system_health=False,
        )
        return Response({"success": True, **result.to_dict()})
