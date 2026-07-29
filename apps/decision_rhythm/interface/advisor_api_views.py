"""Auto-advisor decision sheet API views."""

from __future__ import annotations

import logging
import re

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.decision_rhythm.application.advisor_services import (
    AdvisorAccessError,
    GenerateAdvisorDecisionSheetUseCase,
)

logger = logging.getLogger(__name__)
_ACCOUNT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AdvisorDecisionSheetView(APIView):
    """Return one account-level auto-advisor decision sheet."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Handle GET /api/decision/advisor/sheet/?account_id=<id>."""

        account_id = str(request.query_params.get("account_id") or "").strip()
        if not _ACCOUNT_ID_PATTERN.fullmatch(account_id):
            return Response(
                {"success": False, "error": "account_id is invalid"},
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
        except (
            DatabaseError,
            ImproperlyConfigured,
            LookupError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logger.error(
                "Failed to generate advisor decision sheet (error_type=%s)",
                type(exc).__name__,
            )
            return Response(
                {"success": False, "error": "advisor decision sheet generation failed"},
                status=500,
            )

        return Response({"success": True, "data": sheet})
