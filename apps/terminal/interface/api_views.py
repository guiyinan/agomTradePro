"""Terminal interface API views."""

import json
import logging
import uuid

from django.http import StreamingHttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.rbac import get_user_role
from apps.agent_runtime.application.repository_provider import get_terminal_agent_service
from apps.agent_runtime.application.terminal_agent import (
    RunTerminalAgentChatUseCase,
    StreamTerminalAgentChatUseCase,
    TerminalAgentChatRequestDTO,
)

from ..application.repository_provider import (
    get_terminal_audit_repository,
    get_tui_action_executor,
    get_tui_metadata_repository,
)
from ..application.tui_operator_services import (
    build_operator_governance_queue_payload,
    build_operator_home_payload,
    build_operator_home_section_payload,
)
from ..application.tui_workbench import TuiWorkbenchRegistry, TuiWorkbenchService
from .permissions import IsStaffOrAdmin
from .serializers import (
    TerminalAuditEntrySerializer,
    TerminalChatRequestSerializer,
    TerminalChatResponseSerializer,
)

logger = logging.getLogger(__name__)


def _get_mcp_enabled(user) -> bool:
    """获取用户 MCP 启用状态"""
    profile = getattr(user, "account_profile", None)
    return getattr(profile, "mcp_enabled", False) if profile else False


def _deprecated_command_response() -> Response:
    """Return the standard 410 response for legacy terminal command APIs."""

    return Response(
        {
            "error": "Legacy terminal command APIs have been retired.",
            "detail": "Use the terminal agent chat endpoints backed by MCP/Agents instead.",
        },
        status=status.HTTP_410_GONE,
    )


def _build_terminal_agent_request(request, data) -> TerminalAgentChatRequestDTO:
    """Build the application DTO for terminal agent execution."""

    provider_ref = data.get("provider_ref", data.get("provider_name"))
    return TerminalAgentChatRequestDTO(
        message=str(data["message"]),
        session_id=str(data.get("session_id") or uuid.uuid4()),
        user_id=request.user.id,
        username=request.user.username,
        user_role=get_user_role(request.user),
        user_is_admin=bool(getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False)),
        mcp_enabled=_get_mcp_enabled(request.user),
        provider_ref=provider_ref,
        model=data.get("model") or None,
        context=dict(data.get("context") or {}),
    )


def _format_sse_event(event_type: str, data: dict) -> str:
    """Encode one SSE event payload."""

    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class DeprecatedTerminalCommandViewSet(viewsets.ViewSet):
    """Legacy terminal command routes retained as explicit 410 endpoints."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        return _deprecated_command_response()

    def retrieve(self, request, pk=None):
        return _deprecated_command_response()

    def create(self, request):
        return _deprecated_command_response()

    def update(self, request, pk=None):
        return _deprecated_command_response()

    def partial_update(self, request, pk=None):
        return _deprecated_command_response()

    def destroy(self, request, pk=None):
        return _deprecated_command_response()

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        return _deprecated_command_response()

    @action(detail=False, methods=["post"])
    def execute_by_name(self, request):
        return _deprecated_command_response()

    @action(detail=False, methods=["post"])
    def confirm_execute(self, request):
        return _deprecated_command_response()

    @action(detail=False, methods=["get"])
    def available(self, request):
        return _deprecated_command_response()

    @action(detail=False, methods=["get"])
    def capabilities(self, request):
        return _deprecated_command_response()

    @action(detail=False, methods=["get"])
    def by_category(self, request):
        return _deprecated_command_response()


class TerminalSessionView(APIView):
    """终端会话管理"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Create a new terminal agent session id."""

        session_id = str(uuid.uuid4())
        return Response(
            {
                "success": True,
                "session_id": session_id,
                "username": request.user.username,
            }
        )


class TerminalChatView(APIView):
    """Non-stream terminal agent chat endpoint."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Run one terminal agent request and return a compact JSON payload."""

        serializer = TerminalChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            request_dto = _build_terminal_agent_request(
                request,
                serializer.validated_data,
            )
            response_dto = RunTerminalAgentChatUseCase(
                get_terminal_agent_service()
            ).execute(request_dto)
            response_data = {
                "reply": response_dto.reply,
                "session_id": response_dto.session_id,
                "metadata": response_dto.metadata,
                "approval_required": bool(response_dto.metadata.get("status") == "approval_required"),
                "selected_capability_key": response_dto.metadata.get("capability_key"),
            }
        except Exception as exc:
            logger.exception("Terminal agent chat failed")
            return Response(
                {"error": f"AI 调用异常: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response_serializer = TerminalChatResponseSerializer(response_data)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class TerminalChatStreamView(APIView):
    """Stream terminal agent events as SSE."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Return a text/event-stream response for one terminal agent request."""

        serializer = TerminalChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_dto = _build_terminal_agent_request(request, serializer.validated_data)

        def _event_stream():
            use_case = StreamTerminalAgentChatUseCase(get_terminal_agent_service())
            try:
                for event in use_case.execute(request_dto):
                    yield _format_sse_event(event.event_type, event.data)
            except Exception as exc:
                logger.exception("Terminal agent stream failed")
                yield _format_sse_event(
                    "error",
                    {
                        "session_id": request_dto.session_id,
                        "message": str(exc),
                    },
                )

        return StreamingHttpResponse(
            streaming_content=_event_stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


class TerminalAuditView(APIView):
    """终端审计日志 API（仅 staff）"""

    permission_classes = [IsStaffOrAdmin]

    def get(self, request):
        """
        获取终端审计日志

        GET /api/terminal/audit/?username=&command=&status=&limit=50
        """
        repository = get_terminal_audit_repository()
        username = request.query_params.get("username")
        command_name = request.query_params.get("command")
        result_status = request.query_params.get("status")
        limit = min(int(request.query_params.get("limit", 50)), 200)

        entries = repository.get_recent(
            limit=limit,
            username=username,
            command_name=command_name,
            result_status=result_status,
        )

        serializer = TerminalAuditEntrySerializer(
            [e.__dict__ for e in entries],
            many=True,
        )
        return Response(
            {
                "success": True,
                "count": len(entries),
                "entries": serializer.data,
            }
        )


class TuiWorkbenchRegistryView(APIView):
    """Expose TUI workbench module registry."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return all modules that the standalone TUI shell can render."""

        return Response(
            TuiWorkbenchRegistry(
                metadata_repository=get_tui_metadata_repository(),
            ).list_modules(user=request.user)
        )


class TuiWorkbenchModuleSnapshotView(APIView):
    """Expose one API-driven module UI specification."""

    permission_classes = [IsAuthenticated]

    def get(self, request, module_key: str):
        """Return the renderable spec for one TUI module."""

        return Response(
            TuiWorkbenchRegistry(
                metadata_repository=get_tui_metadata_repository(),
            ).get_module_snapshot(module_key, user=request.user)
        )


class TuiWorkbenchCatalogView(APIView):
    """Expose the V2 API-native TUI catalog."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return grouped modules, screens, and safe actions."""

        service = TuiWorkbenchService(metadata_repository=get_tui_metadata_repository())
        return Response(service.get_catalog(user=request.user))


class TuiWorkbenchScreenView(APIView):
    """Expose one renderable PC tools screen contract."""

    permission_classes = [IsAuthenticated]

    def get(self, request, screen_key: str):
        """Return a screen spec with actions and layout policy."""

        service = TuiWorkbenchService(metadata_repository=get_tui_metadata_repository())
        return Response(service.get_screen(screen_key, user=request.user))


class TuiOperatorHomeView(APIView):
    """Expose the unified TUI operator home summary."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the fixed six-section home payload."""

        return Response(build_operator_home_payload(user=request.user))


class TuiOperatorHomeSectionView(APIView):
    """Expose one operator-home section payload."""

    permission_classes = [IsAuthenticated]

    def get(self, request, section_key: str):
        """Return one fixed section without rebuilding unrelated summaries."""

        try:
            payload = build_operator_home_section_payload(
                user=request.user,
                section_key=section_key,
            )
        except KeyError:
            return Response(
                {"error": "Unknown operator home section"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(payload)


class TuiOperatorGovernanceQueueView(APIView):
    """Expose sortable governance rows for TUI drilldown."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return governance rows ordered by severity and recency."""

        domain = str(request.query_params.get("domain") or "").strip()
        return Response(
            build_operator_governance_queue_payload(
                user=request.user,
                domain=domain,
            )
        )


class TuiWorkbenchActionRunView(APIView):
    """Execute one TUI action and return a business view model."""

    permission_classes = [IsAuthenticated]

    def post(self, request, action_key: str):
        """Run a published safe action for the current user."""

        service = TuiWorkbenchService(
            metadata_repository=get_tui_metadata_repository(),
            action_executor=get_tui_action_executor(),
            audit_repository=get_terminal_audit_repository(),
            require_audit_sink=True,
        )
        try:
            payload = service.run_action(
                action_key=action_key,
                params=request.data.get("params", {}) if isinstance(request.data, dict) else {},
                user=request.user,
                session=getattr(request, "session", None),
                confirmed=(
                    bool(request.data.get("confirmed", False))
                    if isinstance(request.data, dict)
                    else False
                ),
                confirmation=(
                    request.data.get("confirmation") if isinstance(request.data, dict) else None
                ),
                reauth=request.data.get("reauth") if isinstance(request.data, dict) else None,
            )
        except KeyError:
            return Response({"error": "Unknown TUI action"}, status=status.HTTP_404_NOT_FOUND)
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as exc:
            logger.exception("TUI action failed: %s", exc)
            return Response({"error": "TUI action failed"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload)
