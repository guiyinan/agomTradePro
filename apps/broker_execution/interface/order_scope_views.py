"""Session-authenticated human consent and withdrawal for one order version."""

from uuid import UUID

from django.db import DatabaseError
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.broker_execution.application.order_scope_sources import OrderMaterialSelector
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.order_execution_scope_composition import (
    issue_order_execution_scope,
    preview_order_scope,
    revoke_order_execution_scope,
)
from core.exceptions import AuthenticationError, AuthorizationError, ExternalServiceError


class BrokerOrderExecutionScopeView(APIView):
    """Accept only an exact order selector and confirmation from its real owner."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(
        self,
        request: Request,
        client_order_id: UUID,
        *,
        withdrawal: bool = False,
        preview: bool = False,
    ) -> Response:
        """Sign displayed order economics or withdraw a previously seen exact mandate."""
        check = "expected_scope_hash" if withdrawal else "expected_review_hash"
        data = request.data
        required = {"account_id"} if preview else {"account_id", check}
        if (
            type(data) is not dict
            or (
                set(data) != required
                and (withdrawal or set(data) != required | {"research_material"})
            )
            or type(data["account_id"]) is not int
            or data["account_id"] <= 0
        ):
            return Response({"error": "invalid_order_scope_confirmation"}, status=400)
        selection = None
        if "research_material" in data:
            try:
                selection = OrderMaterialSelector.parse(data["research_material"])
            except ValueError:
                return Response({"error": "invalid_research_material"}, status=400)
        try:
            if preview:
                return Response(
                    preview_order_scope(
                        actor=request,
                        client_order_id=client_order_id,
                        account_id=data["account_id"],
                        selection=selection,
                        using="default",
                    )
                )
            digest = data.get(check)
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                return Response({"error": "invalid_order_scope_confirmation"}, status=400)
            if withdrawal:
                revoke_order_execution_scope(
                    actor=request,
                    client_order_id=client_order_id,
                    account_id=data["account_id"],
                    expected_content_hash=digest,
                    using="default",
                )
                return Response({"revoked": True})
            signed = issue_order_execution_scope(
                actor=request,
                client_order_id=client_order_id,
                account_id=data["account_id"],
                expected_review_hash=digest,
                selection=selection,
                using="default",
            )
            return Response(
                {
                    "execution_scope_id": signed.execution_scope_id,
                    "execution_scope_version": signed.execution_scope_version,
                    "execution_scope_hash": signed.execution_scope_hash,
                    "valid_until": signed.valid_until.isoformat(),
                }
            )
        except (AuthenticationError, AuthorizationError, BrokerExecutionPermissionError):
            return Response({"error": "broker_order_scope_permission_denied"}, status=403)
        except BrokerExecutionConflictError as exc:
            reason = str(exc)
            if reason not in {
                "broker_order_scope_issuance_closed",
                "broker_order_scope_review_changed",
            }:
                reason = "broker_order_scope_unavailable"
            return Response({"error": reason}, status=409)
        except (DatabaseError, ExternalServiceError, ValueError):
            return Response({"error": "broker_order_scope_unavailable"}, status=409)
