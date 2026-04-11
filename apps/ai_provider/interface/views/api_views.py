"""
API views for AI provider management.
"""

from django.contrib.auth import get_user_model
from django.http import Http404
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
    TestProviderConnectionUseCase,
    ToggleProviderUseCase,
    UpdateProviderUseCase,
    UpdateUserFallbackQuotaUseCase,
)
from ..serializers import (
    AIProviderConfigSerializer,
    AIUsageLogSerializer,
    AdminProviderCreateSerializer,
    BatchQuotaApplySerializer,
    PersonalProviderCreateSerializer,
    UserFallbackQuotaSerializer,
    UserFallbackQuotaUpdateSerializer,
)


class AIProviderConfigViewSet(viewsets.GenericViewSet):
    """Admin-only CRUD for system providers."""

    permission_classes = [IsAdminUser]
    serializer_class = AIProviderConfigSerializer

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return AdminProviderCreateSerializer
        return AIProviderConfigSerializer

    def list(self, request, *args, **kwargs):
        items = ListProvidersUseCase().execute(scope="system")
        return Response([_provider_list_item_to_dict(item) for item in items])

    def retrieve(self, request, pk=None):
        item = _get_provider_or_404(pk=pk)
        return Response(_provider_list_item_to_dict(item))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = CreateProviderUseCase().execute(
            **serializer.validated_data,
            scope="system",
            owner_user=None,
        )
        item = _get_provider_or_404(pk=provider.id)
        return Response(_provider_list_item_to_dict(item), status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            provider = UpdateProviderUseCase().execute(int(pk), **serializer.validated_data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        item = _get_provider_or_404(pk=provider.id)
        return Response(_provider_list_item_to_dict(item))

    def partial_update(self, request, pk=None):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            provider = UpdateProviderUseCase().execute(int(pk), **serializer.validated_data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        item = _get_provider_or_404(pk=provider.id)
        return Response(_provider_list_item_to_dict(item))

    def destroy(self, request, pk=None):
        try:
            DeleteProviderUseCase().execute(int(pk))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="toggle_active")
    def toggle_active(self, request, pk=None):
        try:
            provider = ToggleProviderUseCase().execute(int(pk))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        item = _get_provider_or_404(pk=provider.id)
        return Response(_provider_list_item_to_dict(item))

    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request, pk=None):
        try:
            result = TestProviderConnectionUseCase().execute(int(pk))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        if result["status"] == "error":
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

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


class PersonalProviderViewSet(viewsets.GenericViewSet):
    """User-scoped CRUD for personal providers."""

    permission_classes = [IsAuthenticated]
    serializer_class = AIProviderConfigSerializer

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

    def retrieve(self, request, pk=None):
        item = _get_provider_or_404(pk=pk, owner_user=request.user)
        return Response(_provider_list_item_to_dict(item))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = CreateProviderUseCase().execute(
            **serializer.validated_data,
            scope="user",
            owner_user=request.user,
        )
        item = _get_provider_or_404(pk=provider.id, owner_user=request.user)
        return Response(_provider_list_item_to_dict(item), status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            provider = UpdateProviderUseCase().execute(
                int(pk),
                actor_user=request.user,
                **serializer.validated_data,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        item = _get_provider_or_404(pk=provider.id, owner_user=request.user)
        return Response(_provider_list_item_to_dict(item))

    def partial_update(self, request, pk=None):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            provider = UpdateProviderUseCase().execute(
                int(pk),
                actor_user=request.user,
                **serializer.validated_data,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        item = _get_provider_or_404(pk=provider.id, owner_user=request.user)
        return Response(_provider_list_item_to_dict(item))

    def destroy(self, request, pk=None):
        try:
            DeleteProviderUseCase().execute(int(pk), actor_user=request.user)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="toggle_active")
    def toggle_active(self, request, pk=None):
        try:
            provider = ToggleProviderUseCase().execute(int(pk), actor_user=request.user)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        item = _get_provider_or_404(pk=provider.id, owner_user=request.user)
        return Response(_provider_list_item_to_dict(item))


class AIUsageLogViewSet(viewsets.GenericViewSet):
    """Admin-only usage log listing."""

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
                return Response(
                    {"error": "provider 必须是整数"}, status=status.HTTP_400_BAD_REQUEST
                )
        else:
            provider_id_int = None
        logs = ListUsageLogsUseCase().execute(
            provider_id=provider_id_int,
            status=status_filter,
            limit=min(int(request.GET.get("limit", 100)), 500),
            provider_scope=provider_scope,
        )
        return Response([item.__dict__ for item in logs])


class MyUsageLogViewSet(viewsets.GenericViewSet):
    """Authenticated user's own usage logs."""

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
        current_quota = GetUserFallbackQuotaUseCase().execute(user=user)
        dto = UpdateUserFallbackQuotaUseCase().execute(
            user=user,
            daily_limit=(
                _decimal_to_float(serializer.validated_data["daily_limit"])
                if "daily_limit" in serializer.validated_data
                else current_quota.daily_limit
            ),
            monthly_limit=(
                _decimal_to_float(serializer.validated_data["monthly_limit"])
                if "monthly_limit" in serializer.validated_data
                else current_quota.monthly_limit
            ),
            is_active=(
                serializer.validated_data["is_active"]
                if "is_active" in serializer.validated_data
                else current_quota.is_active
            ),
            admin_note=(
                serializer.validated_data["admin_note"]
                if "admin_note" in serializer.validated_data
                else current_quota.admin_note
            ),
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


def _get_provider_or_404(*, pk, owner_user=None):
    scope = "user" if owner_user is not None else "system"
    items = ListProvidersUseCase().execute(
        scope=scope,
        owner_user=owner_user,
        include_inactive=True,
    )
    for item in items:
        if item.id == int(pk):
            return item
    raise Http404(f"Provider with id {pk} not found")


def _provider_list_item_to_dict(item):
    return {
        "id": item.id,
        "name": item.name,
        "provider_type": item.provider_type,
        "provider_type_label": item.provider_type_label,
        "scope": item.scope,
        "owner_user_id": item.owner_user_id,
        "owner_username": item.owner_username,
        "is_active": item.is_active,
        "priority": item.priority,
        "base_url": item.base_url,
        "default_model": item.default_model,
        "api_mode": item.api_mode,
        "fallback_enabled": item.fallback_enabled,
        "daily_budget_limit": item.daily_budget_limit,
        "monthly_budget_limit": item.monthly_budget_limit,
        "extra_config": item.extra_config,
        "description": item.description,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "last_used_at": item.last_used_at,
        "today_requests": item.today_requests,
        "today_cost": item.today_cost,
        "month_requests": item.month_requests,
        "month_cost": item.month_cost,
    }
