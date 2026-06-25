"""Auto-advisor decision sheet API views."""

from __future__ import annotations

import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.decision_rhythm.application.advisor_services import (
    AdvisorAccessError,
    GenerateAdvisorDecisionSheetUseCase,
)

logger = logging.getLogger(__name__)


class AdvisorDecisionSheetView(APIView):
    """Return one account-level auto-advisor decision sheet."""

    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        """Handle GET /api/decision/advisor/sheet/?account_id=<id>."""

        account_id = str(request.query_params.get("account_id") or "").strip()
        if not account_id:
            return Response(
                {"success": False, "error": "account_id is required"},
                status=400,
            )

        try:
            sheet = GenerateAdvisorDecisionSheetUseCase().execute(
                account_id=account_id,
                user=request.user,
            )
        except AdvisorAccessError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=exc.status_code,
            )
        except Exception as exc:
            logger.error("Failed to generate advisor decision sheet: %s", exc, exc_info=True)
            return Response(
                {"success": False, "error": "advisor decision sheet generation failed"},
                status=500,
            )

        return Response({"success": True, "data": sheet})
