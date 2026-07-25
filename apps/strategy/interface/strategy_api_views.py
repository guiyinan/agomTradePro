"""Strategy aggregate API viewsets (strategy, script config, AI config).

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
    get_ai_strategy_config_queryset_for_access,
    get_script_config_queryset_for_access,
    get_strategy_ai_config,
    get_strategy_execution_logs_page,
    get_strategy_position_rule,
    get_strategy_queryset_for_access,
    get_strategy_queryset_for_owner,
    get_strategy_script_config,
    set_strategy_active,
    strategy_is_accessible,
)
from apps.strategy.application.position_management_service import (
    PositionManagementService,
    PositionRuleError,
)
from apps.strategy.interface.sdk_contract_actions import StrategySDKContractActionsMixin
from apps.strategy.interface.serializers import (
    AIStrategyConfigSerializer,
    PositionManagementEvaluateInputSerializer,
    PositionManagementEvaluateResultSerializer,
    PositionManagementRuleSerializer,
    RuleConditionListSerializer,
    ScriptConfigSerializer,
    StrategyDetailSerializer,
    StrategyExecutionLogListSerializer,
    StrategyExecutionLogQuerySerializer,
    StrategySerializer,
)

ViewMethod = TypeVar("ViewMethod", bound=Callable[..., Any])


def typed_action(*args: Any, **kwargs: Any) -> Callable[[ViewMethod], ViewMethod]:
    """Expose DRF's runtime action decorator with a type-preserving contract."""

    return cast(Callable[[ViewMethod], ViewMethod], action(*args, **kwargs))


def typed_schema(*args: Any, **kwargs: Any) -> Callable[[ViewMethod], ViewMethod]:
    """Expose drf-spectacular schema metadata without erasing method types."""

    return cast(Callable[[ViewMethod], ViewMethod], extend_schema(*args, **kwargs))


def _request_access_context(request: Request) -> tuple[int | None, bool]:
    """Return the caller's owner profile and staff override."""

    user = request.user
    profile = getattr(user, "account_profile", None)
    profile_id = getattr(profile, "id", None)
    include_all = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    return profile_id, include_all


def _require_config_strategy_access(
    *,
    request: Request,
    serializer: BaseSerializer[Any],
) -> None:
    """Reject cross-owner strategy references in config writes."""

    strategy = serializer.validated_data.get("strategy")
    if strategy is None and serializer.instance is not None:
        strategy = getattr(serializer.instance, "strategy", None)
    strategy_id = getattr(strategy, "id", None)
    owner_profile_id, include_all = _request_access_context(request)
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
        raise PermissionDenied("无权为该策略配置运行参数")


# ========================================================================
# Strategy ViewSet
# ========================================================================


class StrategyViewSet(StrategySDKContractActionsMixin, viewsets.ModelViewSet[Any]):
    """策略 CRUD API"""

    serializer_class = StrategySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["strategy_type", "is_active"]
    search_fields = ["name", "description"]
    ordering_fields = ["created_at", "name", "version"]
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        """Return only strategies visible to the authenticated caller."""

        owner_profile_id, include_all = _request_access_context(self.request)
        return get_strategy_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        )

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        """根据操作选择序列化器"""
        if self.action == "retrieve":
            return cast(type[BaseSerializer[Any]], StrategyDetailSerializer)
        return cast(type[BaseSerializer[Any]], StrategySerializer)

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """创建时自动设置创建者"""

        owner_profile = getattr(self.request.user, "account_profile", None)
        if owner_profile is None:
            raise PermissionDenied("当前用户缺少账户档案")
        serializer.save(created_by=owner_profile)

    @typed_schema(
        summary="获取我的策略列表",
        description="获取当前用户创建的所有策略",
        responses={200: StrategySerializer(many=True)},
    )
    @typed_action(detail=False, methods=["get"])
    def my_strategies(self, request: Request) -> Response:
        """获取我的策略列表"""

        owner_profile_id, _ = _request_access_context(request)
        if owner_profile_id is None:
            raise PermissionDenied("当前用户缺少账户档案")
        strategies = get_strategy_queryset_for_owner(owner_profile_id)
        serializer = self.get_serializer(strategies, many=True)
        return Response(serializer.data)

    @typed_schema(
        summary="激活策略",
        description="激活指定的策略",
        responses={200: StrategySerializer},
    )
    @typed_action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        """激活策略"""

        strategy = self.get_object()
        updated_strategy = set_strategy_active(strategy.id, True)
        if updated_strategy is None:
            raise NotFound("策略不存在或状态更新失败")
        serializer = self.get_serializer(updated_strategy)
        return Response(serializer.data)

    @typed_schema(
        summary="停用策略",
        description="停用指定的策略",
        responses={200: StrategySerializer},
    )
    @typed_action(detail=True, methods=["post"])
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        """停用策略"""

        strategy = self.get_object()
        updated_strategy = set_strategy_active(strategy.id, False)
        if updated_strategy is None:
            raise NotFound("策略不存在或状态更新失败")
        serializer = self.get_serializer(updated_strategy)
        return Response(serializer.data)

    @typed_schema(
        summary="获取策略的规则列表",
        description="获取指定策略的所有规则条件",
        responses={200: RuleConditionListSerializer(many=True)},
    )
    @typed_action(detail=True, methods=["get"])
    def rules(self, request: Request, pk: str | None = None) -> Response:
        """获取策略的规则列表"""
        strategy = self.get_object()
        rules = strategy.rules.all()
        serializer = RuleConditionListSerializer(rules, many=True)
        return Response(serializer.data)

    @typed_schema(
        summary="获取策略的脚本配置",
        description="获取指定策略的脚本配置",
        responses={200: ScriptConfigSerializer},
    )
    @typed_action(detail=True, methods=["get"])
    def script_config(self, request: Request, pk: str | None = None) -> Response:
        """获取策略的脚本配置"""
        strategy = self.get_object()
        config = get_strategy_script_config(strategy.id)
        if config is None:
            return Response(
                {"detail": "该策略没有脚本配置"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ScriptConfigSerializer(config)
        return Response(serializer.data)

    @typed_schema(
        summary="获取策略的 AI 配置",
        description="获取指定策略的 AI 配置",
        responses={200: AIStrategyConfigSerializer},
    )
    @typed_action(detail=True, methods=["get"])
    def ai_config(self, request: Request, pk: str | None = None) -> Response:
        """获取策略的 AI 配置"""
        strategy = self.get_object()
        config = get_strategy_ai_config(strategy.id)
        if config is None:
            return Response(
                {"detail": "该策略没有 AI 配置"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = AIStrategyConfigSerializer(config)
        return Response(serializer.data)

    @typed_schema(
        summary="获取策略的执行日志",
        description="获取指定策略的执行日志（支持分页）",
        responses={200: StrategyExecutionLogListSerializer(many=True)},
    )
    @typed_action(detail=True, methods=["get"])
    def execution_logs(self, request: Request, pk: str | None = None) -> Response:
        """获取策略的执行日志（支持分页）"""
        strategy = self.get_object()

        query_serializer = StrategyExecutionLogQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        offset = query_serializer.validated_data["offset"]
        limit = query_serializer.validated_data["limit"]

        logs, total = get_strategy_execution_logs_page(strategy.id, offset, limit)

        serializer = StrategyExecutionLogListSerializer(logs, many=True)
        return Response(
            {
                "results": serializer.data,
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": offset + limit < total,
            }
        )

    @typed_schema(
        summary="获取策略仓位管理规则",
        description="获取指定策略绑定的仓位管理规则",
        responses={200: PositionManagementRuleSerializer},
    )
    @typed_action(detail=True, methods=["get"])
    def position_rule(self, request: Request, pk: str | None = None) -> Response:
        strategy = self.get_object()
        rule = get_strategy_position_rule(strategy.id)
        if rule is None:
            return Response(
                {"detail": "该策略尚未配置仓位管理规则"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(PositionManagementRuleSerializer(rule).data)

    @typed_schema(
        summary="按策略计算仓位管理建议",
        description="基于策略绑定规则与上下文变量计算买卖价、止盈止损与仓位建议",
        request=PositionManagementEvaluateInputSerializer,
        responses={200: PositionManagementEvaluateResultSerializer},
    )
    @typed_action(detail=True, methods=["post"])
    def evaluate_position_management(self, request: Request, pk: str | None = None) -> Response:
        strategy = self.get_object()
        rule = get_strategy_position_rule(strategy.id)
        if rule is None:
            return Response(
                {"detail": "该策略尚未配置仓位管理规则"},
                status=status.HTTP_404_NOT_FOUND,
            )

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
# Script Config ViewSet
# ========================================================================


class ScriptConfigViewSet(viewsets.ModelViewSet[Any]):
    """脚本配置 CRUD API"""

    serializer_class = ScriptConfigSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["strategy", "is_active"]
    search_fields = ["strategy__name"]

    def get_queryset(self) -> Any:
        """Return only script configs visible to the caller."""

        owner_profile_id, include_all = _request_access_context(self.request)
        return get_script_config_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        )

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """Reject cross-owner strategy references during creation."""

        _require_config_strategy_access(request=self.request, serializer=serializer)
        serializer.save()

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        """Reject cross-owner strategy references during updates."""

        _require_config_strategy_access(request=self.request, serializer=serializer)
        serializer.save()


# ========================================================================
# AI Strategy Config ViewSet
# ========================================================================


class AIStrategyConfigViewSet(viewsets.ModelViewSet[Any]):
    """AI策略配置 CRUD API"""

    serializer_class = AIStrategyConfigSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["strategy", "approval_mode", "ai_provider"]
    search_fields = ["strategy__name"]

    def get_queryset(self) -> Any:
        """Return only AI configs visible to the caller."""

        owner_profile_id, include_all = _request_access_context(self.request)
        return get_ai_strategy_config_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        )

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """Reject cross-owner strategy references during creation."""

        _require_config_strategy_access(request=self.request, serializer=serializer)
        serializer.save()

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        """Reject cross-owner strategy references during updates."""

        _require_config_strategy_access(request=self.request, serializer=serializer)
        serializer.save()


__all__ = [
    "AIStrategyConfigViewSet",
    "ScriptConfigViewSet",
    "StrategyViewSet",
]
