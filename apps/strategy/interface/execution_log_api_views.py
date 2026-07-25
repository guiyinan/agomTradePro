"""Strategy execution-log read-only API viewset.

Interface层:
- 提供REST API接口，使用DRF ViewSet组织API
- 只做输入验证和输出格式化，禁止业务逻辑
"""

from collections.abc import Callable
from typing import Any, TypeVar, cast

from django_filters.rest_framework import DjangoFilterBackend  # type: ignore[import-untyped]
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from apps.strategy.application.interface_services import (
    get_execution_log_queryset_for_access,
    list_execution_logs_by_portfolio_for_access,
    list_execution_logs_by_strategy_for_access,
)
from apps.strategy.interface.serializers import (
    StrategyExecutionLogByPortfolioQuerySerializer,
    StrategyExecutionLogByStrategyQuerySerializer,
    StrategyExecutionLogListSerializer,
    StrategyExecutionLogSerializer,
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


# ========================================================================
# Strategy Execution Log ViewSet
# ========================================================================


class StrategyExecutionLogViewSet(viewsets.ReadOnlyModelViewSet[Any]):
    """策略执行日志 API（只读）"""

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["strategy", "portfolio", "is_success"]
    ordering_fields = ["execution_time", "execution_duration_ms"]
    ordering = ["-execution_time"]

    def get_queryset(self) -> Any:
        """Return logs only when both linked resources belong to the caller."""

        owner_profile_id, include_all = _access_context(self.request)
        return get_execution_log_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        )

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        """根据操作选择序列化器"""
        if self.action == "list":
            return cast(type[BaseSerializer[Any]], StrategyExecutionLogListSerializer)
        return cast(type[BaseSerializer[Any]], StrategyExecutionLogSerializer)

    @typed_schema(
        summary="获取策略的执行日志",
        description="获取指定策略的执行日志",
        parameters=[
            OpenApiParameter(
                name="strategy_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="策略ID",
            )
        ],
        responses={200: StrategyExecutionLogListSerializer(many=True)},
    )
    @typed_action(detail=False, methods=["get"])
    def by_strategy(self, request: Request) -> Response:
        """获取策略的执行日志"""

        query_serializer = StrategyExecutionLogByStrategyQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        owner_profile_id, include_all = _access_context(request)
        logs = list_execution_logs_by_strategy_for_access(
            strategy_id=query_serializer.validated_data["strategy_id"],
            owner_profile_id=owner_profile_id,
            include_all=include_all,
            limit=100,
        )
        serializer = StrategyExecutionLogListSerializer(logs, many=True)
        return Response(serializer.data)

    @typed_schema(
        summary="获取投资组合的执行日志",
        description="获取指定投资组合的执行日志",
        parameters=[
            OpenApiParameter(
                name="portfolio_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="投资组合ID",
            )
        ],
        responses={200: StrategyExecutionLogListSerializer(many=True)},
    )
    @typed_action(detail=False, methods=["get"])
    def by_portfolio(self, request: Request) -> Response:
        """获取投资组合的执行日志"""

        query_serializer = StrategyExecutionLogByPortfolioQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        owner_profile_id, include_all = _access_context(request)
        logs = list_execution_logs_by_portfolio_for_access(
            portfolio_id=query_serializer.validated_data["portfolio_id"],
            owner_profile_id=owner_profile_id,
            include_all=include_all,
            limit=100,
        )
        serializer = StrategyExecutionLogListSerializer(logs, many=True)
        return Response(serializer.data)


__all__ = [
    "StrategyExecutionLogViewSet",
]
