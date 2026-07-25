"""Rule-related API viewsets (position-management rules, rule conditions).

Interface层:
- 提供REST API接口，使用DRF ViewSet组织API
- 只做输入验证和输出格式化，禁止业务逻辑
"""

from collections.abc import Callable
from typing import Any, TypeVar, cast

from django_filters.rest_framework import DjangoFilterBackend  # type: ignore[import-untyped]
from drf_spectacular.utils import extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from apps.strategy.application.interface_services import (
    get_position_management_rule_queryset_for_access,
    get_rule_condition_queryset_for_access,
    set_rule_enabled,
    strategy_is_accessible,
)
from apps.strategy.application.position_management_service import (
    PositionManagementService,
    PositionRuleError,
)
from apps.strategy.interface.serializers import (
    PositionManagementEvaluateInputSerializer,
    PositionManagementEvaluateResultSerializer,
    PositionManagementRuleSerializer,
    RuleConditionListSerializer,
    RuleConditionSerializer,
)

ViewMethod = TypeVar("ViewMethod", bound=Callable[..., Any])
typed_action = cast(
    Callable[..., Callable[[ViewMethod], ViewMethod]],
    action,
)
typed_schema = cast(
    Callable[..., Callable[[ViewMethod], ViewMethod]],
    extend_schema,
)


def _access_context(request: Request) -> tuple[int | None, bool]:
    """Return the caller owner profile and staff override."""

    user = request.user
    owner_profile_id = getattr(getattr(user, "account_profile", None), "id", None)
    if (
        isinstance(owner_profile_id, bool)
        or not isinstance(owner_profile_id, int)
        or owner_profile_id <= 0
    ):
        owner_profile_id = None
    return owner_profile_id, bool(
        getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)
    )


def _require_strategy_reference_access(
    *,
    request: Request,
    serializer: BaseSerializer[Any],
) -> None:
    """Reject a rule create/update that references another owner's strategy."""

    strategy = serializer.validated_data.get("strategy")
    if strategy is None and serializer.instance is not None:
        strategy = getattr(serializer.instance, "strategy", None)
    strategy_id = getattr(strategy, "id", None)
    owner_profile_id, include_all = _access_context(request)
    if (
        isinstance(strategy_id, bool)
        or not isinstance(strategy_id, int)
        or strategy_id <= 0
        or not strategy_is_accessible(
            strategy_id=strategy_id,
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        )
    ):
        raise PermissionDenied("无权为该策略配置规则")


# ========================================================================
# Position Management Rule ViewSet
# ========================================================================


class PositionManagementRuleViewSet(viewsets.ModelViewSet[Any]):
    """仓位管理规则 CRUD + 评估 API"""

    serializer_class = PositionManagementRuleSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["strategy", "is_active"]
    search_fields = ["name", "strategy__name"]
    ordering_fields = ["updated_at", "created_at"]
    ordering = ["-updated_at"]

    def get_queryset(self) -> Any:
        """Return only position rules visible to the caller."""

        owner_profile_id, include_all = _access_context(self.request)
        return get_position_management_rule_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        )

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """Reject cross-owner strategy references during creation."""

        _require_strategy_reference_access(request=self.request, serializer=serializer)
        serializer.save()

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        """Reject cross-owner strategy references during updates."""

        _require_strategy_reference_access(request=self.request, serializer=serializer)
        serializer.save()

    @typed_schema(
        summary="评估仓位管理规则",
        description="按规则ID计算买卖价、止盈止损与仓位建议",
        request=PositionManagementEvaluateInputSerializer,
        responses={200: PositionManagementEvaluateResultSerializer},
    )
    @typed_action(detail=True, methods=["post"])
    def evaluate(self, request: Request, pk: str | None = None) -> Response:
        """Evaluate one active owner-scoped position rule."""

        rule = self.get_object()
        if not rule.is_active:
            return Response(
                {"detail": "仓位管理规则未启用"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        input_serializer = PositionManagementEvaluateInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        context = input_serializer.validated_data["context"]

        try:
            result = PositionManagementService.evaluate(rule=rule, context=context)
        except PositionRuleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = PositionManagementEvaluateResultSerializer(data=result.to_dict())
        output_serializer.is_valid(raise_exception=True)
        return Response(output_serializer.data)


# ========================================================================
# Rule Condition ViewSet
# ========================================================================


class RuleConditionViewSet(viewsets.ModelViewSet[Any]):
    """规则条件 CRUD API"""

    serializer_class = RuleConditionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["strategy", "rule_type", "is_enabled"]
    search_fields = ["rule_name"]
    ordering_fields = ["priority", "created_at"]
    ordering = ["-priority", "-created_at"]

    def get_queryset(self) -> Any:
        """Return only rule conditions visible to the caller."""

        owner_profile_id, include_all = _access_context(self.request)
        return get_rule_condition_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        )

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        """根据操作选择序列化器"""
        if self.action == "list":
            return cast(type[BaseSerializer[Any]], RuleConditionListSerializer)
        return cast(type[BaseSerializer[Any]], RuleConditionSerializer)

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """Reject cross-owner strategy references during creation."""

        _require_strategy_reference_access(request=self.request, serializer=serializer)
        serializer.save()

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        """Reject cross-owner strategy references during updates."""

        _require_strategy_reference_access(request=self.request, serializer=serializer)
        serializer.save()

    @typed_schema(
        summary="启用规则",
        description="启用指定的规则条件",
        responses={200: RuleConditionSerializer},
    )
    @typed_action(detail=True, methods=["post"])
    def enable(self, request: Request, pk: str | None = None) -> Response:
        """启用规则"""

        rule = self.get_object()
        updated_rule = set_rule_enabled(rule.id, True)
        if updated_rule is None:
            raise NotFound("规则不存在或状态更新失败")
        serializer = self.get_serializer(updated_rule)
        return Response(serializer.data)

    @typed_schema(
        summary="停用规则",
        description="停用指定的规则条件",
        responses={200: RuleConditionSerializer},
    )
    @typed_action(detail=True, methods=["post"])
    def disable(self, request: Request, pk: str | None = None) -> Response:
        """停用规则"""

        rule = self.get_object()
        updated_rule = set_rule_enabled(rule.id, False)
        if updated_rule is None:
            raise NotFound("规则不存在或状态更新失败")
        serializer = self.get_serializer(updated_rule)
        return Response(serializer.data)


__all__ = [
    "PositionManagementRuleViewSet",
    "RuleConditionViewSet",
]
