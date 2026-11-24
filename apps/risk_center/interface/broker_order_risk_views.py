"""Session-only HTTP contract for an order's human Risk decisions."""

from datetime import datetime
from uuid import UUID

from django.db import DatabaseError
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.risk_center.application.broker_order_execution_policy import (
    BrokerOrderExecutionPolicyActivation,
)
from apps.risk_center.application.broker_order_risk_authorization import (
    ApproveBrokerOrderRiskAuthorizationCommand,
    RegisterBrokerOrderRiskAuthorizationSubjectCommand,
)
from apps.risk_center.domain.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationSubject,
)
from core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BusinessLogicError,
    ExternalServiceError,
)
from core.integration.broker_order_risk_authority import (
    ActivateSignedOrderPolicy,
    issue_order_risk_from_request,
)


def _command(
    operation: str, raw: object
) -> (
    ActivateSignedOrderPolicy
    | RegisterBrokerOrderRiskAuthorizationSubjectCommand
    | ApproveBrokerOrderRiskAuthorizationCommand
):
    fields = {
        "policy": ("policy_id", "policy_version", "valid_until"),
        "subject": (
            "subject_id",
            "execution_scope_id",
            "execution_scope_version",
            "policy_id",
            "policy_version",
        ),
        "approval": ("subject_id", "authorization_id"),
    }[operation]
    if not isinstance(raw, dict) or set(raw) != set(fields):
        raise ValueError("invalid_fields")

    def token(name: str) -> str:
        value = raw[name]
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 192
            or any(char.isspace() for char in value)
        ):
            raise ValueError("invalid_token")
        return value

    if operation == "policy":
        deadline = datetime.fromisoformat(token("valid_until"))
        if deadline.utcoffset() is None:
            raise ValueError("timezone_required")
        return ActivateSignedOrderPolicy(token("policy_id"), token("policy_version"), deadline)
    if operation == "subject":
        return RegisterBrokerOrderRiskAuthorizationSubjectCommand(
            *(token(field) for field in fields)
        )
    return ApproveBrokerOrderRiskAuthorizationCommand(
        token("subject_id"), token("authorization_id")
    )


class BrokerOrderRiskDecisionView(APIView):
    """Accept identifiers only from an approved human staff session."""

    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[BasePermission]] = [IsAuthenticated, IsAdminUser]
    parser_classes = [JSONParser]
    http_method_names = ["post", "options"]

    def post(
        self, request: Request, account_id: int, client_order_id: UUID, operation: str
    ) -> Response:
        """Issue a bounded receipt for the immutable, server-resolved decision."""
        try:
            command = _command(operation, request.data)
        except ValueError:
            return Response({"code": "invalid_broker_risk_command"}, status=400)
        try:
            item = issue_order_risk_from_request(
                request=request,
                account_id=account_id,
                client_order_id=client_order_id,
                command=command,
            )
        except (AuthenticationError, AuthorizationError):
            return Response({"code": "broker_risk_actor_unavailable"}, status=403)
        except (ValueError, BusinessLogicError):
            return Response({"code": "broker_risk_decision_unavailable"}, status=409)
        except (DatabaseError, ExternalServiceError):
            return Response({"code": "broker_risk_storage_unavailable"}, status=503)
        if isinstance(item, BrokerOrderExecutionPolicyActivation):
            identifier, version, deadline = (
                item.policy.policy_id,
                item.policy.policy_version,
                item.policy.valid_until,
            )
        elif isinstance(item, BrokerOrderRiskAuthorizationSubject):
            identifier, version, deadline = item.subject_id, item.subject_version, item.valid_until
        else:
            identifier, version, deadline = (
                item.authorization_id,
                item.authorization_version,
                item.valid_until,
            )
        return Response(
            {
                "data": {
                    "id": identifier,
                    "version": version,
                    "content_hash": item.content_hash,
                    "valid_until": deadline.isoformat(),
                }
            },
            status=201,
        )
