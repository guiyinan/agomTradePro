"""
AI Capability Catalog Interface API Views.
"""

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..application.dtos import RouteRequestDTO
from ..application.use_cases import (
    GetCapabilityDetailUseCase,
    GetCapabilityListUseCase,
    GetCatalogStatsUseCase,
    RouteMessageUseCase,
    SyncCapabilitiesUseCase,
)
from ..infrastructure.repositories import DjangoCapabilityRepository
from .serializers import (
    CapabilityDetailSerializer,
    CapabilityPublicDetailSerializer,
    CapabilitySummarySerializer,
    CatalogStatsSerializer,
    RouteRequestSerializer,
    RouteResponseSerializer,
    SyncResultSerializer,
    WebChatRequestSerializer,
    WebChatResponseSerializer,
)

logger = logging.getLogger(__name__)


def _get_mcp_enabled(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    profile = getattr(user, "account_profile", None)
    if profile is not None:
        return bool(getattr(profile, "mcp_enabled", False))
    return bool(getattr(user, "mcp_enabled", False))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def route_message(request):
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
def web_chat(request):
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


def _extract_execute_action(context: dict) -> dict | None:
    """Normalize explicit action execution requests from web clients."""
    action = context.get("execute_action")
    if isinstance(action, dict) and action.get("action_type") == "execute_capability":
        capability_key = action.get("capability_key")
        if capability_key:
            return {
                "action_type": "execute_capability",
                "capability_key": capability_key,
            }

    capability_key = context.get("execute_capability")
    action_type = context.get("action_type")
    if action_type == "execute_capability" and capability_key:
        return {
            "action_type": "execute_capability",
            "capability_key": capability_key,
        }
    return None


def _build_web_chat_response(routed: dict, user_is_admin: bool) -> dict:
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
        "suggested_command": routed.get("suggested_command"),
        "suggested_intent": routed.get("suggested_intent"),
        "suggestion_prompt": routed.get("suggestion_prompt"),
        "suggested_action": suggested_action,
    }


def _mask_answer_chain(answer_chain: dict) -> dict:
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
    labels = {
        "builtin.system_status": "执行系统状态检查",
        "builtin.market_regime": "查看市场 Regime",
    }
    return labels.get(capability_key, f"执行 {capability_key.split('.')[-1]}")


def _get_capability_description(capability_key: str) -> str:
    """Get description for a capability."""
    descriptions = {
        "builtin.system_status": "读取当前系统健康状态并返回摘要",
        "builtin.market_regime": "获取当前市场 Regime 状态和 Policy 档位",
    }
    return descriptions.get(capability_key, f"执行能力: {capability_key}")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_capabilities(request):
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
    q = (request.query_params.get("q") or "").strip().lower()
    enabled_only = request.query_params.get("enabled_only", "true").lower() == "true"

    use_case = GetCapabilityListUseCase()

    try:
        capabilities = use_case.execute(
            source_type=source_type,
            route_group=route_group,
            enabled_only=enabled_only,
        )
        if q:
            capabilities = [
                item for item in capabilities
                if q in (item.get("capability_key", "") or "").lower()
                or q in (item.get("name", "") or "").lower()
                or q in (item.get("summary", "") or "").lower()
            ]
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
def get_capability(request, capability_key):
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
def sync_capabilities(request):
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

    sync_type = request.data.get("sync_type", "full")
    source = request.data.get("source")

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
def catalog_stats(request):
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


class CapabilityViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for capabilities."""

    serializer_class = CapabilitySummarySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        repo = DjangoCapabilityRepository()
        source_type = self.request.query_params.get("source_type")
        route_group = self.request.query_params.get("route_group")

        if source_type:
            return repo.get_by_source_type(source_type)
        elif route_group:
            return repo.get_by_route_group(route_group)
        else:
            return repo.get_all_enabled()

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
