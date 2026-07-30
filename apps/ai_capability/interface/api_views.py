"""
AI Capability Catalog Interface API Views.
"""

import logging
from typing import Any

from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from shared.request_payload import request_data_mapping

from ..application.dtos import RouteRequestDTO
from ..application.governance_services import CapabilityCatalogGovernanceService
from ..application.interface_services import (
    get_mcp_tools_catalog_payload,
    get_mcp_tools_stats_payload,
    list_capability_summary_payloads,
    search_capability_summary_payloads,
    toggle_mcp_tool_flag,
)
from ..application.use_cases import (
    GetCapabilityDetailUseCase,
    GetCatalogStatsUseCase,
    RouteMessageUseCase,
    SyncCapabilitiesUseCase,
)
from .serializers import (
    CapabilityDetailSerializer,
    CapabilityPublicDetailSerializer,
    CapabilitySummarySerializer,
    CatalogStatsSerializer,
    McpToolListSerializer,
    McpToolStatsSerializer,
    McpToolSyncResultSerializer,
    McpToolToggleResultSerializer,
    RouteRequestSerializer,
    SyncResultSerializer,
    WebChatRequestSerializer,
)

logger = logging.getLogger(__name__)


def _get_mcp_enabled(user: object) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    profile = getattr(user, "account_profile", None)
    if profile is not None:
        return bool(getattr(profile, "mcp_enabled", False))
    return bool(getattr(user, "mcp_enabled", False))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_root(request: Request) -> Response:
    """Return AI capability API endpoint directory."""
    return Response(
        {
            "module": "ai-capability",
            "endpoints": {
                "capabilities": "/api/ai-capability/capabilities/",
                "route": "/api/ai-capability/route/",
                "web": "/api/ai-capability/web/",
                "sync": "/api/ai-capability/sync/",
                "stats": "/api/ai-capability/stats/",
                "mcp_tools": "/api/ai-capability/mcp-tools/",
                "mcp_tools_stats": "/api/ai-capability/mcp-tools/stats/",
                "mcp_tools_sync": "/api/ai-capability/mcp-tools/sync/",
            },
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def route_message(request: Request) -> Response:
    """
    Route a message through the capability catalog.

    POST /api/ai-capability/route/

    Request body:
    {
        "message": "目前系统是什么状态",
        "entrypoint": "terminal",
        "session_id": "xxx",
        "provider_name": "openai-main",
        "model": "gpt-4.1",
        "context": {}
    }

    Response:
    {
        "decision": "capability",
        "selected_capability_key": "builtin.system_status",
        "confidence": 0.94,
        "candidate_capabilities": [...],
        "requires_confirmation": false,
        "reply": "## System Readiness...",
        "session_id": "xxx",
        "metadata": {...},
        "answer_chain": {}
    }
    """
    serializer = RouteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data

    context = data.get("context", {})
    context["user_id"] = request.user.id if request.user.is_authenticated else None
    context["user_is_admin"] = request.user.is_staff if request.user.is_authenticated else False
    context["mcp_enabled"] = _get_mcp_enabled(request.user)
    context["answer_chain_enabled"] = context.get("answer_chain_enabled", False)

    use_case = RouteMessageUseCase()

    request_dto = RouteRequestDTO(
        message=data["message"],
        entrypoint=data.get("entrypoint", "terminal"),
        session_id=data.get("session_id"),
        provider_name=data.get("provider_name"),
        model=data.get("model"),
        confirmation_id=data.get("confirmation_id"),
        approved=data.get("approved"),
        context=context,
    )

    try:
        response_dto = use_case.execute(request_dto)
        return Response(response_dto.to_dict())
    except Exception as e:
        logger.exception("Routing failed")
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def web_chat(request: Request) -> Response:
    """
    Shared web chat API for homepage and AgomChatWidget.

    POST /api/chat/web/

    This API provides a neutral entrypoint for web-based chat interfaces,
    reusing the capability routing system without terminal-specific logic.

    Request body:
    {
        "message": "当前系统是什么状态",
        "session_id": "optional-session-id",
        "provider_name": "openai-main",
        "model": "gpt-4.1",
        "context": {
            "history": []
        }
    }

    Response:
    {
        "reply": "## System Readiness: `ok`",
        "session_id": "uuid-string",
        "metadata": {
            "provider": "capability-router",
            "model": "router",
            "tokens": 0,
            "answer_chain": {
                "label": "View answer chain",
                "visibility": "masked",
                "steps": []
            }
        },
        "route_confirmation_required": false,
        "suggested_command": null,
        "suggested_intent": null,
        "suggestion_prompt": null,
        "suggested_action": null
    }

    When confirmation is required:
    {
        "reply": "检测到你可能想执行系统状态检查。",
        "session_id": "uuid-string",
        "metadata": {...},
        "route_confirmation_required": true,
        "suggested_command": "/status",
        "suggested_intent": "system_status",
        "suggestion_prompt": "检测到你可能想执行 /status。",
        "suggested_action": {
            "action_type": "execute_capability",
            "capability_key": "builtin.system_status",
            "command": "/status",
            "intent": "system_status",
            "label": "执行系统状态检查",
            "description": "读取当前系统健康状态并返回摘要",
            "payload": {}
        }
    }
    """
    from ..application.facade import CapabilityRoutingFacade

    serializer = WebChatRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    user_is_admin = request.user.is_staff if request.user.is_authenticated else False
    mcp_enabled = _get_mcp_enabled(request.user)

    facade = CapabilityRoutingFacade()
    action = _extract_execute_action(data.get("context") or {})

    try:
        if action:
            result = facade.execute_capability(
                capability_key=action["capability_key"],
                message=data["message"],
                entrypoint="web",
                session_id=data.get("session_id"),
                user_id=request.user.id if request.user.is_authenticated else None,
                user_is_admin=user_is_admin,
                mcp_enabled=mcp_enabled,
                provider_name=data.get("provider_name"),
                model=data.get("model"),
                context=data.get("context", {}),
                answer_chain_enabled=True,
            )
        else:
            result = facade.route(
                message=data["message"],
                entrypoint="web",
                session_id=data.get("session_id"),
                user_id=request.user.id if request.user.is_authenticated else None,
                user_is_admin=user_is_admin,
                mcp_enabled=mcp_enabled,
                provider_name=data.get("provider_name"),
                model=data.get("model"),
                confirmation_id=data.get("confirmation_id"),
                approved=data.get("approved"),
                context=data.get("context", {}),
                answer_chain_enabled=True,
            )

        response_data = _build_web_chat_response(result, user_is_admin)
        return Response(response_data)
    except PermissionError as e:
        return Response(
            {"error": str(e), "reply": str(e)},
            status=status.HTTP_403_FORBIDDEN,
        )
    except Exception as e:
        logger.exception("Web chat failed")
        return Response(
            {"error": str(e), "reply": f"聊天请求处理失败: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _extract_execute_action(context: dict[str, Any]) -> dict[str, str] | None:
    """Normalize explicit action execution requests from web clients."""
    action = context.get("execute_action")
    if isinstance(action, dict) and action.get("action_type") == "execute_capability":
        capability_key = action.get("capability_key")
        if isinstance(capability_key, str) and capability_key.strip():
            return {
                "action_type": "execute_capability",
                "capability_key": capability_key.strip(),
            }

    capability_key = context.get("execute_capability")
    action_type = context.get("action_type")
    if (
        action_type == "execute_capability"
        and isinstance(capability_key, str)
        and capability_key.strip()
    ):
        return {
            "action_type": "execute_capability",
            "capability_key": capability_key.strip(),
        }
    return None


def _build_web_chat_response(
    routed: dict[str, Any],
    user_is_admin: bool,
) -> dict[str, Any]:
    """Build web chat response from routing result."""
    answer_chain = routed.get("answer_chain", {})
    if answer_chain and not user_is_admin:
        answer_chain = _mask_answer_chain(answer_chain)

    suggested_action = None
    if routed.get("requires_confirmation") and routed.get("selected_capability_key"):
        suggested_action = {
            "action_type": "execute_capability",
            "capability_key": routed["selected_capability_key"],
            "command": routed.get("suggested_command", ""),
            "intent": routed.get("suggested_intent", ""),
            "label": _get_capability_label(routed["selected_capability_key"]),
            "description": _get_capability_description(routed["selected_capability_key"]),
            "payload": {},
        }

    return {
        "reply": routed.get("reply", ""),
        "session_id": routed.get("session_id", ""),
        "metadata": {
            "provider": routed.get("metadata", {}).get("provider", "unknown"),
            "model": routed.get("metadata", {}).get("model", "unknown"),
            "tokens": routed.get("metadata", {}).get("tokens", 0),
            "answer_chain": answer_chain,
        },
        "route_confirmation_required": routed.get("requires_confirmation", False),
        "selected_capability_key": routed.get("selected_capability_key"),
        "suggested_command": routed.get("suggested_command"),
        "suggested_intent": routed.get("suggested_intent"),
        "suggestion_prompt": routed.get("suggestion_prompt"),
        "suggested_action": suggested_action,
        "confirmation": routed.get("confirmation"),
        "result": routed.get("result"),
    }


def _mask_answer_chain(answer_chain: dict[str, Any]) -> dict[str, Any]:
    """Mask technical details in answer chain for non-admin users."""
    masked_steps = []
    for step in answer_chain.get("steps", []):
        masked_step = {
            "title": step.get("title", ""),
            "summary": step.get("summary", ""),
            "source": step.get("source", ""),
        }
        masked_steps.append(masked_step)

    return {
        "label": answer_chain.get("label", "Answer chain"),
        "visibility": "masked",
        "steps": masked_steps,
    }


def _get_capability_label(capability_key: str) -> str:
    """Get human-readable label for a capability."""
    labels: dict[str, str] = {
        "builtin.system_status": "执行系统状态检查",
        "builtin.market_regime": "查看市场 Regime",
    }
    return labels.get(capability_key, f"执行 {capability_key.split('.')[-1]}")


def _get_capability_description(capability_key: str) -> str:
    """Get description for a capability."""
    descriptions: dict[str, str] = {
        "builtin.system_status": "读取当前系统健康状态并返回摘要",
        "builtin.market_regime": "获取当前市场 Regime 状态和 Policy 档位",
    }
    return descriptions.get(capability_key, f"执行能力: {capability_key}")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_capabilities(request: Request) -> Response:
    """
    List capabilities in the catalog.

    GET /api/ai-capability/capabilities/

    Query params:
    - source_type: Filter by source type (builtin, terminal_command, mcp_tool, api)
    - route_group: Filter by route group (builtin, tool, read_api, write_api, unsafe_api)
    - enabled_only: Only return enabled capabilities (default: true)
    """
    source_type = request.query_params.get("source_type")
    route_group = request.query_params.get("route_group")
    category = request.query_params.get("category")
    q = (request.query_params.get("q") or "").strip()
    enabled_only_param = request.query_params.get("enabled_only", "true").lower()
    if enabled_only_param not in {"true", "false"}:
        return Response(
            {"error": "enabled_only must be 'true' or 'false'"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    enabled_only = enabled_only_param == "true"

    try:
        query = search_capability_summary_payloads if q else list_capability_summary_payloads
        capabilities = query(
            **({"query": q} if q else {}),
            source_type=source_type,
            route_group=route_group,
            category=category,
            enabled_only=enabled_only,
        )
        serializer = CapabilitySummarySerializer(capabilities, many=True)
        return Response(serializer.data)
    except Exception as e:
        logger.exception("Failed to list capabilities")
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_capability(request: Request, capability_key: str) -> Response:
    """
    Get a specific capability by key.

    GET /api/ai-capability/capabilities/{capability_key}/
    """
    use_case = GetCapabilityDetailUseCase()

    try:
        capability = use_case.execute(capability_key)
        if capability is None:
            return Response(
                {"error": "Capability not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer_class = (
            CapabilityDetailSerializer
            if request.user.is_staff or request.user.is_superuser
            else CapabilityPublicDetailSerializer
        )
        serializer = serializer_class(capability.to_dict())
        return Response(serializer.data)
    except Exception as e:
        logger.exception("Failed to get capability")
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sync_capabilities(request: Request) -> Response:
    """
    Sync capabilities from all sources.

    POST /api/ai-capability/sync/

    Requires admin privileges.
    """
    if not request.user.is_staff:
        return Response(
            {"error": "Admin privileges required"},
            status=status.HTTP_403_FORBIDDEN,
        )

    request_payload = request_data_mapping(request)
    sync_type = request_payload.get("sync_type", "full")
    source = request_payload.get("source")
    if not isinstance(sync_type, str) or sync_type not in {"full", "incremental"}:
        return Response(
            {"error": "sync_type must be 'full' or 'incremental'"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if source is not None and (
        not isinstance(source, str)
        or source
        not in {
            "builtin",
            "terminal_command",
            "mcp_tool",
            "api",
        }
    ):
        return Response(
            {"error": "Unsupported capability source"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    use_case = SyncCapabilitiesUseCase()

    try:
        result = use_case.execute(sync_type=sync_type, source=source)
        serializer = SyncResultSerializer(result.to_dict())
        return Response(serializer.data)
    except Exception as e:
        logger.exception("Sync failed")
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def catalog_stats(request: Request) -> Response:
    """
    Get catalog statistics.

    GET /api/ai-capability/stats/
    """
    use_case = GetCatalogStatsUseCase()

    try:
        stats = use_case.execute()
        serializer = CatalogStatsSerializer(stats)
        return Response(serializer.data)
    except Exception as e:
        logger.exception("Failed to get stats")
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _admin_forbidden_response() -> Response:
    return Response(
        {"error": "Admin privileges required"},
        status=status.HTTP_403_FORBIDDEN,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_mcp_tools(request: Request) -> Response:
    """List MCP capability governance rows for TUI and admin surfaces."""

    if not request.user.is_staff:
        return _admin_forbidden_response()

    q = (request.query_params.get("q") or "").strip()
    module_filter = (request.query_params.get("module") or "").strip()
    status_filter = (request.query_params.get("status") or "").strip()
    try:
        limit = int(request.query_params.get("limit") or 80)
    except (TypeError, ValueError):
        return Response(
            {"error": "limit must be an integer between 1 and 300"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not 1 <= limit <= 300:
        return Response(
            {"error": "limit must be an integer between 1 and 300"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    payload = get_mcp_tools_catalog_payload(
        search_query=q,
        module_filter=module_filter,
        status_filter=status_filter,
        limit=limit,
    )
    serializer = McpToolListSerializer(payload)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mcp_tools_stats(request: Request) -> Response:
    """Return MCP capability governance summary for TUI and admin surfaces."""

    if not request.user.is_staff:
        return _admin_forbidden_response()

    serializer = McpToolStatsSerializer(get_mcp_tools_stats_payload())
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sync_mcp_tools(request: Request) -> Response:
    """Sync MCP tools and apply governance in one admin action."""

    if not request.user.is_staff:
        return _admin_forbidden_response()

    try:
        sync_result = SyncCapabilitiesUseCase().execute(sync_type="incremental", source="mcp_tool")
        governance_result = CapabilityCatalogGovernanceService().execute(apply=True)
        serializer = McpToolSyncResultSerializer(
            {
                "sync": sync_result.to_dict(),
                "governance": governance_result.to_dict(),
            }
        )
        return Response(serializer.data)
    except Exception as e:
        logger.exception("Failed to sync MCP tools")
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_mcp_tool(request: Request, capability_key: str, flag: str) -> Response:
    """Toggle one MCP governance flag for a synced tool."""

    if not request.user.is_staff:
        return _admin_forbidden_response()
    if flag not in {"enabled_for_terminal", "enabled_for_routing"}:
        return Response(
            {"error": "Unsupported MCP flag"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        tool = toggle_mcp_tool_flag(capability_key=capability_key, flag=flag)
        if tool is None:
            return Response(
                {"error": "MCP tool not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = McpToolToggleResultSerializer(
            {
                "capability_key": tool.capability_key,
                "name": tool.name,
                "changed_flag": flag,
                "changed_value": bool(getattr(tool, flag)),
                "enabled_for_routing": bool(tool.enabled_for_routing),
                "enabled_for_terminal": bool(tool.enabled_for_terminal),
            }
        )
        return Response(serializer.data)
    except Exception as e:
        logger.exception("Failed to toggle MCP tool flag")
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class CapabilityViewSet(viewsets.ViewSet):
    """ViewSet for capabilities."""

    serializer_class = CapabilitySummarySerializer
    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def get_queryset(self) -> list[dict[str, Any]]:
        source_type = self.request.query_params.get("source_type")
        route_group = self.request.query_params.get("route_group")
        category = self.request.query_params.get("category")
        enabled_only = self.request.query_params.get("enabled_only", "true").lower() == "true"

        return list_capability_summary_payloads(
            source_type=source_type,
            route_group=route_group,
            category=category,
            enabled_only=enabled_only,
        )

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.get_queryset()
        serializer = CapabilitySummarySerializer(queryset, many=True)
        return Response(serializer.data)
