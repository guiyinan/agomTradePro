"""Canonical human and machine HTTP APIs for broker execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.conf import settings
from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer
from rest_framework.views import APIView

from apps.broker_execution.application.agent_auth import AuthenticateAgentRequestUseCase
from apps.broker_execution.application.agent_use_cases import (
    AcknowledgeSubmittingUseCase,
    AgentHeartbeatUseCase,
    CompleteAgentCommandUseCase,
    LeaseAgentCommandsUseCase,
    LeaseAgentOrdersUseCase,
    ReportAgentEventsUseCase,
    SyncAgentSnapshotUseCase,
)
from apps.broker_execution.application.authorization import action_permissions
from apps.broker_execution.application.management_use_cases import (
    ManageAccountAccessUseCase,
    ManageAgentBindingUseCase,
    PreviewOrResolveReconciliationUseCase,
    RequestAgentSyncUseCase,
    RevokeAgentCredentialUseCase,
    RotateAgentCredentialUseCase,
    UpdateExecutionSettingsUseCase,
)
from apps.broker_execution.application.query_services import BrokerExecutionQueryService
from apps.broker_execution.application.use_case_errors import (
    BrokerAgentAuthenticationError,
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
    BrokerExecutionPermissionError,
    BrokerExecutionValidationError,
)
from apps.broker_execution.application.use_cases import (
    PreviewOrCreateAdvisorLiveOrdersUseCase,
    PreviewOrMutateOrderUseCase,
    PreviewOrSetKillSwitchUseCase,
)

from .serializers import (
    AccountAccessSerializer,
    AdvisorDraftSerializer,
    AgentBindingSerializer,
    AgentCommandCompleteSerializer,
    AgentCommandsSerializer,
    AgentEventsSerializer,
    AgentHeartbeatSerializer,
    AgentLeaseSerializer,
    AgentSnapshotSerializer,
    AgentSubmittingSerializer,
    ConnectionSyncSerializer,
    CredentialRevokeSerializer,
    CredentialRotateSerializer,
    ExecutionSettingsSerializer,
    KillSwitchSerializer,
    OrderActionSerializer,
    ReconciliationResolutionSerializer,
)


def _error_response(exc: Exception) -> Response:
    if isinstance(exc, (BrokerAgentAuthenticationError, BrokerExecutionPermissionError)):
        return Response({"success": False, "error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, BrokerExecutionNotFoundError):
        return Response({"success": False, "error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, BrokerExecutionConflictError):
        return Response({"success": False, "error": str(exc)}, status=status.HTTP_409_CONFLICT)
    if isinstance(exc, (BrokerExecutionValidationError, ValueError)):
        return Response({"success": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    raise exc


def _success(data: Any, *, permissions: dict[str, bool] | None = None) -> Response:
    payload: dict[str, Any] = {"success": True, "data": data}
    if permissions is not None:
        payload["permissions"] = permissions
    return Response(payload)


def _request_context(request: Request) -> dict[str, str]:
    """Return a bounded, server-derived audit context without trusting body data."""

    authenticator = getattr(request, "successful_authenticator", None)
    return {
        "source_ip": str(request.META.get("REMOTE_ADDR") or "")[:64],
        "user_agent": str(request.META.get("HTTP_USER_AGENT") or "")[:256],
        "authenticator": (
            authenticator.__class__.__name__ if authenticator is not None else "unknown"
        )[:64],
    }


class BrokerExecutionOverviewView(APIView):
    """Return strict persisted-only live execution readiness."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            data = BrokerExecutionQueryService().overview(actor=request.user)
            return _success(data, permissions=action_permissions(request.user))
        except (BrokerExecutionPermissionError, BrokerExecutionValidationError) as exc:
            return _error_response(exc)


class BrokerExecutionOrderListView(APIView):
    """Return a scoped live-order catalog."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            account_id = request.query_params.get("account_id")
            data = BrokerExecutionQueryService().orders(
                actor=request.user,
                account_id=int(account_id) if account_id else None,
                status=request.query_params.get("status") or None,
                limit=int(request.query_params.get("limit", 100)),
            )
            return _success(data, permissions=action_permissions(request.user))
        except (BrokerExecutionPermissionError, BrokerExecutionValidationError, ValueError) as exc:
            return _error_response(exc)


class BrokerExecutionAdvisorDraftView(APIView):
    """Preview or create live drafts from the current server-generated advisor sheet."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = AdvisorDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return _success(
                PreviewOrCreateAdvisorLiveOrdersUseCase().execute(
                    actor=request.user,
                    account_id=serializer.validated_data["account_id"],
                    preview_only=serializer.validated_data["preview_only"],
                    expected_plan_digest=serializer.validated_data.get("expected_plan_digest", ""),
                    idempotency_key=serializer.validated_data.get("idempotency_key"),
                )
            )
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionConflictError,
            BrokerExecutionValidationError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionOrderDetailView(APIView):
    """Return one scoped order with events and fills."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, client_order_id: UUID) -> Response:
        try:
            data = BrokerExecutionQueryService().order_detail(
                actor=request.user, client_order_id=client_order_id
            )
            return _success(data, permissions=action_permissions(request.user))
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionValidationError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionOrderActionView(APIView):
    """Preview or commit approve, reject, and cancel actions."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, client_order_id: str, action: str) -> Response:
        serializer = OrderActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = PreviewOrMutateOrderUseCase().execute(
                actor=request.user,
                client_order_id=client_order_id,
                action=action,
                reason=serializer.validated_data.get("reason", ""),
                preview_only=serializer.validated_data["preview_only"],
                expected_version=serializer.validated_data.get("expected_version"),
                idempotency_key=serializer.validated_data.get("idempotency_key"),
            )
            return _success(data)
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionConflictError,
            BrokerExecutionValidationError,
            ValueError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionKillSwitchView(APIView):
    """Preview or commit stop/resume for an account or user-global scope."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = KillSwitchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = PreviewOrSetKillSwitchUseCase().execute(
                actor=request.user,
                account_id=serializer.validated_data["account_id"],
                active=serializer.validated_data["active"],
                reason=serializer.validated_data["reason"],
                preview_only=serializer.validated_data["preview_only"],
                idempotency_key=serializer.validated_data.get("idempotency_key"),
                reauth=serializer.validated_data.get("reauth"),
                request_context=_request_context(request),
            )
            return _success(data)
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionConflictError,
            BrokerExecutionValidationError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionConnectionView(APIView):
    """Return strict persisted-only Agent/QMT connection snapshots."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            return _success(
                BrokerExecutionQueryService().connections(actor=request.user),
                permissions=action_permissions(request.user),
            )
        except BrokerExecutionPermissionError as exc:
            return _error_response(exc)


class BrokerExecutionQmtOnboardingView(APIView):
    """Return administrator-only QMT setup guidance and persisted settings."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        public_base_url = str(getattr(settings, "APP_BASE_URL", "") or "").strip()
        server_address = public_base_url or request.build_absolute_uri("/").rstrip("/")
        try:
            return _success(
                BrokerExecutionQueryService().qmt_onboarding(
                    actor=request.user,
                    server_address=server_address,
                )
            )
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionValidationError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionConnectionSyncView(APIView):
    """Preview or request an asynchronous Agent/QMT full connection sync."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = ConnectionSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return _success(
                RequestAgentSyncUseCase().execute(
                    actor=request.user,
                    agent_id=serializer.validated_data["agent_id"],
                    reason=serializer.validated_data["reason"],
                    preview_only=serializer.validated_data["preview_only"],
                    idempotency_key=serializer.validated_data.get("idempotency_key"),
                )
            )
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionConflictError,
            BrokerExecutionValidationError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionReconciliationView(APIView):
    """Return strict persisted reconciliation runs."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            return _success(
                BrokerExecutionQueryService().reconciliations(
                    actor=request.user, limit=int(request.query_params.get("limit", 100))
                ),
                permissions=action_permissions(request.user),
            )
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionValidationError,
            ValueError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionReconciliationResolveView(APIView):
    """Preview or resolve one reconciliation batch."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, run_id: int) -> Response:
        serializer = ReconciliationResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return _success(
                PreviewOrResolveReconciliationUseCase().execute(
                    actor=request.user,
                    run_id=run_id,
                    resolution=serializer.validated_data["resolution"],
                    reason=serializer.validated_data["reason"],
                    preview_only=serializer.validated_data["preview_only"],
                    idempotency_key=serializer.validated_data.get("idempotency_key"),
                )
            )
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionConflictError,
            BrokerExecutionValidationError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionAuditView(APIView):
    """Return scoped append-only audit events."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            return _success(
                BrokerExecutionQueryService().audits(
                    actor=request.user, limit=int(request.query_params.get("limit", 100))
                ),
                permissions=action_permissions(request.user),
            )
        except (BrokerExecutionPermissionError, ValueError) as exc:
            return _error_response(exc)


class BrokerExecutionBindingView(APIView):
    """Admin-only Agent/account binding management."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = AgentBindingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return _success(
                ManageAgentBindingUseCase().execute(
                    actor=request.user,
                    payload={
                        key: value
                        for key, value in serializer.validated_data.items()
                        if key not in {"preview_only", "idempotency_key"}
                    },
                    preview_only=serializer.validated_data["preview_only"],
                    idempotency_key=serializer.validated_data.get("idempotency_key"),
                )
            )
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionConflictError,
            BrokerExecutionValidationError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionAccountAccessView(APIView):
    """Admin-only account grant management with preview and audit."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            return _success(BrokerExecutionQueryService().account_access_grants(actor=request.user))
        except BrokerExecutionPermissionError as exc:
            return _error_response(exc)

    def post(self, request: Request) -> Response:
        serializer = AccountAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return _success(
                ManageAccountAccessUseCase().execute(
                    actor=request.user,
                    payload={
                        key: value
                        for key, value in serializer.validated_data.items()
                        if key not in {"preview_only", "idempotency_key"}
                    },
                    preview_only=serializer.validated_data["preview_only"],
                    idempotency_key=serializer.validated_data.get("idempotency_key"),
                )
            )
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionConflictError,
            BrokerExecutionValidationError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionCredentialRotateView(APIView):
    """Admin-only one-time Agent credential issuance."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = CredentialRotateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return _success(
                RotateAgentCredentialUseCase().execute(
                    actor=request.user,
                    agent_id=serializer.validated_data["agent_id"],
                    scopes=serializer.validated_data["scopes"],
                    account_ids=serializer.validated_data["account_ids"],
                    expires_at=serializer.validated_data["expires_at"].isoformat(),
                    preview_only=serializer.validated_data["preview_only"],
                    idempotency_key=serializer.validated_data.get("idempotency_key"),
                )
            )
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionConflictError,
            BrokerExecutionValidationError,
        ) as exc:
            return _error_response(exc)


class BrokerExecutionCredentialRevokeView(APIView):
    """Admin-only immediate Agent credential revocation."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, credential_id: str) -> Response:
        serializer = CredentialRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return _success(
                RevokeAgentCredentialUseCase().execute(
                    actor=request.user,
                    credential_id=credential_id,
                    reason=serializer.validated_data["reason"],
                    preview_only=serializer.validated_data["preview_only"],
                    idempotency_key=serializer.validated_data.get("idempotency_key"),
                )
            )
        except (BrokerExecutionPermissionError, BrokerExecutionNotFoundError) as exc:
            return _error_response(exc)


class BrokerExecutionSettingsView(APIView):
    """Admin-only bounded account execution settings."""

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, account_id: int) -> Response:
        serializer = ExecutionSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return _success(
                UpdateExecutionSettingsUseCase().execute(
                    actor=request.user,
                    account_id=account_id,
                    payload={
                        key: value
                        for key, value in serializer.validated_data.items()
                        if key not in {"preview_only", "idempotency_key"}
                    },
                    preview_only=serializer.validated_data["preview_only"],
                    idempotency_key=serializer.validated_data.get("idempotency_key"),
                )
            )
        except (
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionConflictError,
        ) as exc:
            return _error_response(exc)


class AgentApiView(APIView):
    """Base for signed machine-only endpoints; no user auth or session cookies."""

    authentication_classes: list[type[BaseAuthentication]] = []
    permission_classes = [AllowAny]
    required_scope = ""
    serializer_class: type[Serializer[Any]] = AgentHeartbeatSerializer

    def handle_agent(
        self,
        request: Request,
        callback: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    ) -> Response:
        try:
            raw_body = request.body
            agent = AuthenticateAgentRequestUseCase().execute(
                headers=request.headers,
                body=raw_body,
                required_scope=self.required_scope,
                source_ip=_request_context(request)["source_ip"],
            )
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            return _success(callback(agent, dict(serializer.validated_data)))
        except (
            BrokerAgentAuthenticationError,
            BrokerExecutionPermissionError,
            BrokerExecutionNotFoundError,
            BrokerExecutionConflictError,
            BrokerExecutionValidationError,
            ValueError,
        ) as exc:
            return _error_response(exc)


class AgentHeartbeatView(AgentApiView):
    required_scope = "agent.heartbeat.write"
    serializer_class = AgentHeartbeatSerializer

    def post(self, request: Request) -> Response:
        return self.handle_agent(
            request,
            lambda agent, data: AgentHeartbeatUseCase().execute(agent=agent, payload=data),
        )


class AgentOrderLeaseView(AgentApiView):
    required_scope = "agent.orders.lease"
    serializer_class = AgentLeaseSerializer

    def post(self, request: Request) -> Response:
        return self.handle_agent(
            request,
            lambda agent, data: LeaseAgentOrdersUseCase().execute(
                agent=agent, limit=data["limit"], lease_seconds=data["lease_seconds"]
            ),
        )


class AgentSubmittingView(AgentApiView):
    required_scope = "agent.orders.submitting_ack"
    serializer_class = AgentSubmittingSerializer

    def post(self, request: Request) -> Response:
        return self.handle_agent(
            request,
            lambda agent, data: AcknowledgeSubmittingUseCase().execute(
                agent=agent,
                client_order_id=str(data["client_order_id"]),
                lease_token=data["lease_token"],
            ),
        )


class AgentEventsView(AgentApiView):
    required_scope = "agent.events.write"
    serializer_class = AgentEventsSerializer

    def post(self, request: Request) -> Response:
        return self.handle_agent(
            request,
            lambda agent, data: ReportAgentEventsUseCase().execute(
                agent=agent, events=data["events"]
            ),
        )


class AgentSnapshotView(AgentApiView):
    required_scope = "agent.snapshots.write"
    serializer_class = AgentSnapshotSerializer

    def post(self, request: Request) -> Response:
        return self.handle_agent(
            request,
            lambda agent, data: SyncAgentSnapshotUseCase().execute(agent=agent, payload=data),
        )


class AgentCommandsView(AgentApiView):
    required_scope = "agent.commands.lease"
    serializer_class = AgentCommandsSerializer

    def post(self, request: Request) -> Response:
        return self.handle_agent(
            request,
            lambda agent, data: LeaseAgentCommandsUseCase().execute(
                agent=agent, limit=data["limit"]
            ),
        )


class AgentCommandCompleteView(AgentApiView):
    required_scope = "agent.commands.lease"
    serializer_class = AgentCommandCompleteSerializer

    def post(self, request: Request) -> Response:
        return self.handle_agent(
            request,
            lambda agent, data: CompleteAgentCommandUseCase().execute(
                agent=agent,
                command_id=str(data["command_id"]),
                success=data["success"],
                result=data.get("result", {}),
            ),
        )
