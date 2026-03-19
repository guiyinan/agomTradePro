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
    GetCapabilityListUseCase,
    RouteMessageUseCase,
    SyncCapabilitiesUseCase,
)
from ..infrastructure.repositories import DjangoCapabilityRepository
from .serializers import (
    CatalogStatsSerializer,
    CapabilityDetailSerializer,
    CapabilityPublicDetailSerializer,
    CapabilitySummarySerializer,
    RouteRequestSerializer,
    RouteResponseSerializer,
    SyncResultSerializer,
)


logger = logging.getLogger(__name__)


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
    context["mcp_enabled"] = (
        getattr(request.user, "mcp_enabled", True) if request.user.is_authenticated else True
    )
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
    enabled_only = request.query_params.get("enabled_only", "true").lower() == "true"

    use_case = GetCapabilityListUseCase()

    try:
        capabilities = use_case.execute(
            source_type=source_type,
            route_group=route_group,
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
def get_capability(request, capability_key):
    """
    Get a specific capability by key.

    GET /api/ai-capability/capabilities/{capability_key}/
    """
    repo = DjangoCapabilityRepository()

    try:
        capability = repo.get_by_key(capability_key)
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
    repo = DjangoCapabilityRepository()

    try:
        stats = repo.get_stats()
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
