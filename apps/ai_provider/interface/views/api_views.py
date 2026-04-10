"""
API views for AI provider management.
"""

import logging

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from ...application.use_cases import (
    BatchApplyUserFallbackQuotaUseCase,
    CheckBudgetUseCase,
    CreateProviderUseCase,
    DeleteProviderUseCase,
    GetOverallStatsUseCase,
    GetProviderStatsUseCase,
    GetUserFallbackQuotaUseCase,
    ListProvidersUseCase,
    ListUsageLogsUseCase,
    ListUserFallbackQuotasUseCase,
    ToggleProviderUseCase,
    UpdateProviderUseCase,
    UpdateUserFallbackQuotaUseCase,
)
from ...infrastructure.adapters import OpenAICompatibleAdapter
from ...infrastructure.models import AIProviderConfig, AIUsageLog, AIUserFallbackQuota
from ...infrastructure.repositories import AIProviderRepository
from ..serializers import (
    AIProviderConfigSerializer,
    AIUsageLogSerializer,
    AdminProviderCreateSerializer,
    BatchQuotaApplySerializer,
    PersonalProviderCreateSerializer,
    UserFallbackQuotaSerializer,
    UserFallbackQuotaUpdateSerializer,
)

logger = logging.getLogger(__name__)


class AIProviderConfigViewSet(viewsets.ModelViewSet):
    """Admin-only CRUD for system providers."""

    queryset = AIProviderConfig._default_manager.filter(scope="system").order_by("priority", "name")
    permission_classes = [IsAdminUser]
    serializer_class = AIProviderConfigSerializer
    _provider_repo = AIProviderRepository()

    def get_queryset(self):
        return AIProviderConfig._default_manager.filter(scope="system").order_by("priority", "name")

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return AdminProviderCreateSerializer
        return AIProviderConfigSerializer

    def list(self, request, *args, **kwargs):
        items = ListProvidersUseCase().execute(scope="system")
        return Response([_provider_list_item_to_dict(item) for item in items])

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = CreateProviderUseCase().execute(
            **serializer.validated_data,
            scope="system",
            owner_user=None,
        )
        return Response(
            AIProviderConfigSerializer(provider).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            provider = UpdateProviderUseCase().execute(
                int(kwargs["pk"]),
                **serializer.validated_data,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(AIProviderConfigSerializer(provider).data)

    def partial_update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            provider = UpdateProviderUseCase().execute(
                int(kwargs["pk"]),
                **serializer.validated_data,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(AIProviderConfigSerializer(provider).data)

    def destroy(self, request, *args, **kwargs):
        try:
            DeleteProviderUseCase().execute(int(kwargs["pk"]))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="toggle_active")
    def toggle_active(self, request, pk=None):
        try:
            provider = ToggleProviderUseCase().execute(int(pk))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(AIProviderConfigSerializer(provider).data)

    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request, pk=None):
        provider = self._provider_repo.get_by_id(int(pk))
        if provider is None or provider.scope != "system":
            return Response({"error": f"Provider with id {pk} not found"}, status=status.HTTP_404_NOT_FOUND)

        api_key = self._provider_repo.get_api_key(provider)
        if not api_key:
            return Response(
                {"status": "error", "error": "API key not available in current environment"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            adapter = OpenAICompatibleAdapter(
                base_url=provider.base_url,
                api_key=api_key,
                default_model=provider.default_model,
                api_mode=provider.api_mode,
                fallback_enabled=provider.fallback_enabled,
            )
            available = adapter.is_available()
        except Exception as exc:
            logger.exception("Provider test connection failed")
            return Response(
                {"status": "error", "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not available:
            return Response(
                {"status": "error", "error": "Provider health check failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"status": "success", "provider": provider.name})

    @action(detail=True, methods=["get"], url_path="usage_stats")
    def usage_stats(self, request, pk=None):
        try:
            stats = GetProviderStatsUseCase().execute(int(pk))
            budget = CheckBudgetUseCase().execute(int(pk))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "provider_id": stats.provider_id,
                "provider_name": stats.provider_name,
                "today_requests": stats.today_requests,
                "today_cost": stats.today_cost,
                "month_requests": stats.month_requests,
                "month_cost": stats.month_cost,
                "usage_by_date": stats.usage_by_date,
                "model_stats": stats.model_stats,
                "budget": budget.__dict__,
            }
        )

    @action(detail=False, methods=["get"], url_path="overall_stats")
    def overall_stats(self, request):
        stats = GetOverallStatsUseCase().execute()
        return Response(stats.__dict__)


class PersonalProviderViewSet(viewsets.ModelViewSet):
    """User-scoped CRUD for personal providers."""

    permission_classes = [IsAuthenticated]
    serializer_class = AIProviderConfigSerializer

    def get_queryset(self):
        return AIProviderConfig._default_manager.filter(
            scope="user",
            owner_user=self.request.user,
        ).order_by("priority", "name")

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return PersonalProviderCreateSerializer
        return AIProviderConfigSerializer

    def list(self, request, *args, **kwargs):
        items = ListProvidersUseCase().execute(
            scope="user",
            owner_user=request.user,
        )
        return Response([_provider_list_item_to_dict(item) for item in items])

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = CreateProviderUseCase().execute(
            **serializer.validated_data,
            scope="user",
            owner_user=request.user,
        )
        return Response(
            AIProviderConfigSerializer(provider).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            provider = UpdateProviderUseCase().execute(
                int(kwargs["pk"]),
                actor_user=request.user,
                **serializer.validated_data,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(AIProviderConfigSerializer(provider).data)

    def partial_update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            provider = UpdateProviderUseCase().execute(
                int(kwargs["pk"]),
                actor_user=request.user,
                **serializer.validated_data,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(AIProviderConfigSerializer(provider).data)

    def destroy(self, request, *args, **kwargs):
        try:
            DeleteProviderUseCase().execute(int(kwargs["pk"]), actor_user=request.user)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="toggle_active")
    def toggle_active(self, request, pk=None):
        try:
            provider = ToggleProviderUseCase().execute(int(pk), actor_user=request.user)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(AIProviderConfigSerializer(provider).data)


class AIUsageLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin-only usage log listing."""

    queryset = AIUsageLog._default_manager.select_related("provider", "user").order_by("-created_at")
    permission_classes = [IsAdminUser]
    serializer_class = AIUsageLogSerializer

    def list(self, request, *args, **kwargs):
        provider_id = request.GET.get("provider")
        status_filter = request.GET.get("status")
        provider_scope = request.GET.get("provider_scope")
        if provider_id:
            try:
                provider_id_int = int(provider_id)
            except ValueError:
                return Response({"error": "provider 必须是整数"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            provider_id_int = None
        logs = ListUsageLogsUseCase().execute(
            provider_id=provider_id_int,
            status=status_filter,
            limit=min(int(request.GET.get("limit", 100)), 500),
            provider_scope=provider_scope,
        )
        return Response([item.__dict__ for item in logs])


class MyUsageLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Authenticated user's own usage logs."""

    queryset = AIUsageLog._default_manager.select_related("provider", "user").order_by("-created_at")
    permission_classes = [IsAuthenticated]
    serializer_class = AIUsageLogSerializer

    def list(self, request, *args, **kwargs):
        status_filter = request.GET.get("status")
        provider_scope = request.GET.get("provider_scope")
        logs = ListUsageLogsUseCase().execute(
            user=request.user,
            status=status_filter,
            limit=min(int(request.GET.get("limit", 100)), 500),
            provider_scope=provider_scope,
        )
        return Response([item.__dict__ for item in logs])


class UserFallbackQuotaViewSet(viewsets.GenericViewSet):
    """Authenticated user's quota visibility."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserFallbackQuotaSerializer

    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request):
        dto = GetUserFallbackQuotaUseCase().execute(user=request.user)
        return Response(dto.__dict__)


class AdminUserFallbackQuotaViewSet(viewsets.GenericViewSet):
    """Admin management for user fallback quotas."""

    permission_classes = [IsAdminUser]
    serializer_class = UserFallbackQuotaSerializer

    def list(self, request, *args, **kwargs):
        quotas = ListUserFallbackQuotasUseCase().execute()
        return Response([item.__dict__ for item in quotas])

    def retrieve(self, request, pk=None):
        user = get_object_or_404(get_user_model(), pk=pk)
        dto = GetUserFallbackQuotaUseCase().execute(user=user)
        return Response(dto.__dict__)

    def partial_update(self, request, pk=None):
        serializer = UserFallbackQuotaUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = get_object_or_404(get_user_model(), pk=pk)
        dto = UpdateUserFallbackQuotaUseCase().execute(
            user=user,
            daily_limit=_decimal_to_float(serializer.validated_data.get("daily_limit")),
            monthly_limit=_decimal_to_float(serializer.validated_data.get("monthly_limit")),
            is_active=serializer.validated_data.get("is_active", True),
            admin_note=serializer.validated_data.get("admin_note", ""),
        )
        return Response(dto.__dict__)

    @action(detail=False, methods=["post"], url_path="batch_apply")
    def batch_apply(self, request):
        serializer = BatchQuotaApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = BatchApplyUserFallbackQuotaUseCase().execute(
            daily_limit=_decimal_to_float(serializer.validated_data.get("daily_limit")),
            monthly_limit=_decimal_to_float(serializer.validated_data.get("monthly_limit")),
            overwrite_existing=serializer.validated_data.get("overwrite_existing", False),
            is_active=serializer.validated_data.get("is_active", True),
            admin_note=serializer.validated_data.get("admin_note", ""),
        )
        return Response(result.__dict__, status=status.HTTP_200_OK)


def _decimal_to_float(value):
    if value is None:
        return None
    return float(value)


def _provider_list_item_to_dict(item):
    return {
        "id": item.id,
        "name": item.name,
        "provider_type": item.provider_type,
        "scope": item.scope,
        "owner_user_id": item.owner_user_id,
        "owner_username": item.owner_username,
        "is_active": item.is_active,
        "priority": item.priority,
        "base_url": item.base_url,
        "default_model": item.default_model,
        "api_mode": item.api_mode,
        "fallback_enabled": item.fallback_enabled,
        "description": item.description,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "last_used_at": item.last_used_at,
        "today_requests": item.today_requests,
        "today_cost": item.today_cost,
        "month_requests": item.month_requests,
        "month_cost": item.month_cost,
    }
