"""Terminal interface API views."""

import json
import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any, cast

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import OperationalError, ProgrammingError
from django.http import StreamingHttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.rbac import get_user_role
from apps.agent_runtime.application.proposal_use_cases import (
    ApproveProposalUseCase,
    ExecuteProposalUseCase,
    GetProposalUseCase,
    GuardrailBlockedError,
    InvalidProposalTransitionError,
    ProposalExecutionError,
    RejectProposalUseCase,
)
from apps.agent_runtime.application.repository_provider import (
    get_approved_mcp_capability_executor,
    get_terminal_agent_service,
)
from apps.agent_runtime.application.terminal_agent import (
    RunTerminalAgentChatUseCase,
    StreamTerminalAgentChatUseCase,
    TerminalAgentChatRequestDTO,
    TerminalAgentService,
)
from apps.agent_runtime.application.terminal_approval import (
    TERMINAL_MCP_PROPOSAL_TYPE,
)
from apps.ai_capability.application.facade import CapabilityRoutingFacade

from ..application.repository_provider import (
    get_terminal_audit_repository,
    get_tui_action_executor,
    get_tui_metadata_repository,
)
from ..application.tui_errors import TuiScreenForbiddenError, TuiScreenNotFoundError
from ..application.tui_operator_services import (
    build_operator_governance_queue_payload,
    build_operator_home_payload,
    build_operator_home_section_payload,
)
from ..application.tui_workbench import TuiWorkbenchRegistry, TuiWorkbenchService
from .permissions import IsStaffOrAdmin, IsStaffOrOperator
from .serializers import (
    TerminalApprovalDecisionSerializer,
    TerminalAuditEntrySerializer,
    TerminalChatRequestSerializer,
    TerminalChatResponseSerializer,
    TuiAgentActionSearchQuerySerializer,
)

logger = logging.getLogger(__name__)


def _tui_timed_response(
    payload: Any,
    *,
    metric: str,
    started_at: float,
    response_status: int = status.HTTP_200_OK,
) -> Response:
    """Return a TUI response with a browser-readable server timing metric."""

    response = Response(payload, status=response_status)
    duration_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
    response["Server-Timing"] = f"{metric};dur={duration_ms:.2f}"
    return response


def _get_terminal_agent_service() -> TerminalAgentService:
    """Compose Terminal Agent with the owning AI capability facade."""

    return cast(
        TerminalAgentService,
        get_terminal_agent_service(capability_gateway=CapabilityRoutingFacade()),
    )


def _get_mcp_enabled(user: Any) -> bool:
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


def _build_terminal_agent_request(
    request: Request,
    data: dict[str, Any],
) -> TerminalAgentChatRequestDTO:
    """Build the application DTO for terminal agent execution."""

    provider_ref = data.get("provider_ref", data.get("provider_name"))
    return TerminalAgentChatRequestDTO(
        message=str(data["message"]),
        session_id=str(data.get("session_id") or uuid.uuid4()),
        user_id=request.user.id,
        username=request.user.username,
        user_role=get_user_role(request.user),
        user_is_admin=bool(
            getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False)
        ),
        mcp_enabled=_get_mcp_enabled(request.user),
        provider_ref=provider_ref,
        model=data.get("model") or None,
        context=dict(data.get("context") or {}),
    )


def _format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Encode one SSE event payload."""

    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class DeprecatedTerminalCommandViewSet(viewsets.ViewSet):
    """Legacy terminal command routes retained as explicit 410 endpoints."""

    permission_classes = [IsAuthenticated]

    def list(self, request: Request) -> Response:
        return _deprecated_command_response()

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        return _deprecated_command_response()

    def create(self, request: Request) -> Response:
        return _deprecated_command_response()

    def update(self, request: Request, pk: str | None = None) -> Response:
        return _deprecated_command_response()

    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        return _deprecated_command_response()

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        return _deprecated_command_response()

    @action(detail=True, methods=["post"])
    def execute(self, request: Request, pk: str | None = None) -> Response:
        return _deprecated_command_response()

    @action(detail=False, methods=["post"])
    def execute_by_name(self, request: Request) -> Response:
        return _deprecated_command_response()

    @action(detail=False, methods=["post"])
    def confirm_execute(self, request: Request) -> Response:
        return _deprecated_command_response()

    @action(detail=False, methods=["get"])
    def available(self, request: Request) -> Response:
        return _deprecated_command_response()

    @action(detail=False, methods=["get"])
    def capabilities(self, request: Request) -> Response:
        return _deprecated_command_response()

    @action(detail=False, methods=["get"])
    def by_category(self, request: Request) -> Response:
        return _deprecated_command_response()


class TuiWorkbenchApiRootView(APIView):
    """Discoverable root for the user-facing TUI runtime API."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """List the stable TUI runtime endpoints."""

        return Response(
            {
                "endpoints": {
                    "catalog": "/api/tui/catalog/",
                    "bootstrap": "/api/tui/bootstrap/",
                    "operator-home": "/api/tui/operator/home/",
                    "governance-queue": "/api/tui/operator/governance-queue/",
                    "screens": "/api/tui/screens/{screen_key}/",
                    "actions": "/api/tui/actions/{action_key}/run/",
                    "registry": "/api/tui/registry/",
                    "module-snapshot": "/api/tui/modules/{module_key}/snapshot/",
                }
            }
        )


class TerminalSessionView(APIView):
    """终端会话管理"""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
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

    def post(self, request: Request) -> Response:
        """Run one terminal agent request and return a compact JSON payload."""

        serializer = TerminalChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            request_dto = _build_terminal_agent_request(
                request,
                serializer.validated_data,
            )
            response_dto = RunTerminalAgentChatUseCase(_get_terminal_agent_service()).execute(
                request_dto
            )
            response_data = {
                "reply": response_dto.reply,
                "session_id": response_dto.session_id,
                "metadata": response_dto.metadata,
                "approval_required": bool(
                    response_dto.metadata.get("status") == "approval_required"
                ),
                "selected_capability_key": response_dto.metadata.get("capability_key"),
                "proposal_id": response_dto.metadata.get("proposal_id"),
            }
        except RuntimeError as exc:
            if str(exc) in {
                "No active AI providers configured",
                "No available AI providers",
            }:
                logger.info("Terminal agent provider configuration is unavailable")
                return Response(
                    {
                        "error": "AI 服务尚未配置，请先配置可用服务商。",
                        "code": "AI_PROVIDER_UNAVAILABLE",
                        "setup_required": True,
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            logger.exception("Terminal agent chat failed")
            return Response(
                {"error": f"AI 调用异常: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
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

    def post(self, request: Request) -> StreamingHttpResponse:
        """Return a text/event-stream response for one terminal agent request."""

        serializer = TerminalChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_dto = _build_terminal_agent_request(request, serializer.validated_data)

        def _event_stream() -> Iterator[str]:
            use_case = StreamTerminalAgentChatUseCase(_get_terminal_agent_service())
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


class TerminalApprovalDecisionView(APIView):
    """Approve-and-execute or reject one persisted Terminal MCP proposal."""

    permission_classes = [IsStaffOrOperator]

    def post(self, request: Request, proposal_id: int) -> Response:
        """Apply an operator decision to a Terminal MCP proposal."""

        serializer = TerminalApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = {
            "user_id": request.user.id,
            "username": request.user.username,
            "is_staff": bool(request.user.is_staff or request.user.is_superuser),
            "roles": list(request.user.groups.values_list("name", flat=True)),
        }
        decision = serializer.validated_data["decision"]
        reason = serializer.validated_data.get("reason") or None

        try:
            proposal = GetProposalUseCase().execute(proposal_id=proposal_id).proposal
            if proposal.proposal_type != TERMINAL_MCP_PROPOSAL_TYPE:
                return Response(
                    {"error": "Proposal is not a Terminal MCP approval"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if decision == "reject":
                reject_output = RejectProposalUseCase().execute(
                    proposal_id=proposal_id,
                    reason=reason,
                    actor=actor,
                )
                return Response(
                    {
                        "request_id": reject_output.request_id,
                        "proposal_id": proposal_id,
                        "status": "rejected",
                    }
                )

            ApproveProposalUseCase().execute(
                proposal_id=proposal_id,
                reason=reason,
                actor=actor,
            )
            execution_output = ExecuteProposalUseCase(
                approved_capability_executor=get_approved_mcp_capability_executor(),
            ).execute(
                proposal_id=proposal_id,
                actor=actor,
                context={},
            )
            return Response(
                {
                    "request_id": execution_output.request_id,
                    "proposal_id": proposal_id,
                    "status": "executed",
                    "execution_record_id": execution_output.execution_record_id,
                    "guardrail_decision": execution_output.guardrail_decision,
                }
            )
        except ObjectDoesNotExist:
            return Response(
                {"error": "Approval proposal not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except InvalidProposalTransitionError as exc:
            return Response(
                {"error": exc.message},
                status=status.HTTP_409_CONFLICT,
            )
        except GuardrailBlockedError as exc:
            return Response(
                {"error": exc.guardrail_message, "reason_code": exc.reason_code},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ProposalExecutionError as exc:
            return Response(
                {
                    "error": str(exc),
                    "execution_record_id": exc.execution_record_id,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )


class TerminalAuditView(APIView):
    """终端审计日志 API（仅 staff）"""

    permission_classes = [IsStaffOrAdmin]

    def get(self, request: Request) -> Response:
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

    def get(self, request: Request) -> Response:
        """Return all modules that the standalone TUI shell can render."""

        return Response(
            TuiWorkbenchRegistry(
                metadata_repository=get_tui_metadata_repository(),
            ).list_modules(user=request.user)
        )


class TuiWorkbenchModuleSnapshotView(APIView):
    """Expose one API-driven module UI specification."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, module_key: str) -> Response:
        """Return the renderable spec for one TUI module."""

        return Response(
            TuiWorkbenchRegistry(
                metadata_repository=get_tui_metadata_repository(),
            ).get_module_snapshot(module_key, user=request.user)
        )


class TuiWorkbenchCatalogView(APIView):
    """Expose the V2 API-native TUI catalog."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return grouped modules, screens, and safe actions."""

        started_at = time.perf_counter()
        service = TuiWorkbenchService(metadata_repository=get_tui_metadata_repository())
        return _tui_timed_response(
            service.get_catalog(user=request.user),
            metric="tui_catalog",
            started_at=started_at,
        )


class TuiWorkbenchBootstrapView(APIView):
    """Expose catalog and initial screen from one runtime snapshot."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return the optional optimized bootstrap contract."""

        if not bool(getattr(settings, "TUI_OPTIMIZED_BOOTSTRAP_ENABLED", True)):
            return Response(
                {"error": "Optimized TUI bootstrap is disabled"},
                status=status.HTTP_404_NOT_FOUND,
            )
        started_at = time.perf_counter()
        requested_screen = str(request.query_params.get("screen_key") or "").strip()[:200]
        service = TuiWorkbenchService(metadata_repository=get_tui_metadata_repository())
        try:
            payload = service.get_bootstrap(
                requested_screen=requested_screen,
                user=request.user,
            )
        except TuiScreenForbiddenError:
            return _tui_timed_response(
                _tui_error_payload(
                    request=request,
                    error_code="tui_screen_forbidden",
                    title="无权访问",
                    detail="当前账号不能打开这个工作区。",
                    recovery_actions=[{"label": "返回首页", "screen_key": "home"}],
                ),
                metric="tui_bootstrap",
                started_at=started_at,
                response_status=status.HTTP_403_FORBIDDEN,
            )
        return _tui_timed_response(
            payload,
            metric="tui_bootstrap",
            started_at=started_at,
        )


def _tui_error_payload(
    *,
    request: Request,
    error_code: str,
    title: str,
    detail: str,
    recovery_actions: list[dict[str, str]],
) -> dict[str, Any]:
    """Build a bounded user-facing TUI error payload without exception text."""

    trace_id = str(request.headers.get("X-Request-ID") or uuid.uuid4().hex)
    return {
        "error_code": error_code,
        "title": title,
        "detail": detail,
        "recovery_actions": recovery_actions,
        "trace_id": trace_id,
    }


class TuiWorkbenchScreenView(APIView):
    """Expose one renderable PC tools screen contract."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, screen_key: str) -> Response:
        """Return a screen spec with actions and layout policy."""

        started_at = time.perf_counter()
        service = TuiWorkbenchService(metadata_repository=get_tui_metadata_repository())
        try:
            payload = service.get_screen(screen_key, user=request.user)
        except TuiScreenNotFoundError:
            return Response(
                _tui_error_payload(
                    request=request,
                    error_code="tui_screen_not_found",
                    title="页面不存在",
                    detail="这个工作区没有发布，或已被移除。",
                    recovery_actions=[{"label": "返回首页", "screen_key": "home"}],
                ),
                status=status.HTTP_404_NOT_FOUND,
            )
        except TuiScreenForbiddenError:
            return Response(
                _tui_error_payload(
                    request=request,
                    error_code="tui_screen_forbidden",
                    title="无权访问",
                    detail="当前账号不能打开这个工作区。",
                    recovery_actions=[
                        {
                            "label": "返回我的 MCP 接入",
                            "screen_key": "capability-router.self-service",
                        }
                    ],
                ),
                status=status.HTTP_403_FORBIDDEN,
            )
        return _tui_timed_response(
            payload,
            metric="tui_screen",
            started_at=started_at,
        )


class TuiAgentActionSearchView(APIView):
    """Expose bounded published-action discovery to authenticated Agents."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return compact action summaries matching one query."""

        serializer = TuiAgentActionSearchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        service = TuiWorkbenchService(metadata_repository=get_tui_metadata_repository())
        return Response(
            service.search_agent_actions(
                query=serializer.validated_data["query"],
                limit=serializer.validated_data["limit"],
                user=request.user,
            )
        )


class TuiAgentActionSchemaView(APIView):
    """Expose one published action schema to authenticated Agents."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, action_key: str) -> Response:
        """Return one visible action contract or 404."""

        service = TuiWorkbenchService(metadata_repository=get_tui_metadata_repository())
        try:
            payload = service.get_agent_action_schema(action_key, user=request.user)
        except KeyError:
            return Response({"error": "Unknown TUI action"}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)


class TuiOperatorHomeView(APIView):
    """Expose the unified TUI operator home summary."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return the fixed six-section home payload."""

        started_at = time.perf_counter()
        return _tui_timed_response(
            build_operator_home_payload(user=request.user),
            metric="tui_operator_home",
            started_at=started_at,
        )


class TuiOperatorHomeSectionView(APIView):
    """Expose one operator-home section payload."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, section_key: str) -> Response:
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

    def get(self, request: Request) -> Response:
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

    def post(self, request: Request, action_key: str) -> Response:
        """Run a published safe action for the current user."""

        service = TuiWorkbenchService(
            metadata_repository=get_tui_metadata_repository(),
            action_executor=get_tui_action_executor(),
            audit_repository=get_terminal_audit_repository(),
            require_audit_sink=True,
        )
        task_label = "当前任务"
        task_recovery_actions: list[dict[str, str]] = [{"label": "返回首页", "screen_key": "home"}]
        try:
            error_context = service.get_action_error_context(action_key, user=request.user)
            task_label = str(error_context.get("label") or task_label)
            recovery_screen = str(error_context.get("screen_key") or "")
            if recovery_screen:
                task_recovery_actions = [
                    {"label": f"返回{task_label}", "screen_key": recovery_screen}
                ]
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
            return Response(
                _tui_error_payload(
                    request=request,
                    error_code="tui_action_not_found",
                    title="任务不存在",
                    detail="这个任务没有发布，或已被移除。",
                    recovery_actions=[{"label": "返回首页", "screen_key": "home"}],
                ),
                status=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError:
            return Response(
                _tui_error_payload(
                    request=request,
                    error_code="tui_action_forbidden",
                    title="无权执行",
                    detail="当前账号不能执行这个任务。",
                    recovery_actions=task_recovery_actions,
                ),
                status=status.HTTP_403_FORBIDDEN,
            )
        except (OperationalError, ProgrammingError) as exc:
            logger.exception("TUI action database readiness failed: %s", exc)
            return Response(
                _tui_error_payload(
                    request=request,
                    error_code="tui_action_not_ready",
                    title="服务正在恢复",
                    detail=f"“{task_label}”所需的数据结构尚未就绪，请稍后重试。",
                    recovery_actions=task_recovery_actions,
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:
            logger.exception("TUI action failed: %s", exc)
            return Response(
                _tui_error_payload(
                    request=request,
                    error_code="tui_action_unavailable",
                    title="任务暂时不可用",
                    detail=f"“{task_label}”暂时无法完成，请稍后重试。",
                    recovery_actions=task_recovery_actions,
                ),
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(payload)
