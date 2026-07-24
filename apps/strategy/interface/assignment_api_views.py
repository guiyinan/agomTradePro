"""Owner-scoped portfolio-strategy assignment endpoints."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

from django.apps import apps as django_apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend  # type: ignore[import-untyped]
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.strategy.application.interface_services import (
    bind_strategy_assignment,
    get_assignment_queryset_for_access,
    list_assignments_by_portfolio_for_access,
    set_assignment_active,
    unbind_strategy_assignments,
)
from apps.strategy.application.simulated_trading_gateway import (
    get_simulated_trading_facade,
)
from apps.strategy.interface.page_views import _json_error
from apps.strategy.interface.serializers import (
    PortfolioStrategyAssignmentDetailSerializer,
    PortfolioStrategyAssignmentSerializer,
)
from core.exceptions import InvalidInputError

logger = logging.getLogger(__name__)

StrategyModel = django_apps.get_model("strategy", "StrategyModel")

_MAX_ASSIGNMENT_BODY_BYTES = 10_000
ViewMethod = TypeVar("ViewMethod", bound=Callable[..., Any])
typed_action = cast(
    Callable[..., Callable[[ViewMethod], ViewMethod]],
    action,
)
typed_extend_schema = cast(
    Callable[..., Callable[[ViewMethod], ViewMethod]],
    extend_schema,
)


def _profile_id(user: object) -> int | None:
    """Return a valid account-profile identifier when available."""

    value = getattr(getattr(user, "account_profile", None), "id", None)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _positive_int(value: object, *, field_name: str) -> int:
    """Validate a positive integer request value."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidInputError(f"{field_name} 必须是正整数")
    return value


def _parse_json_object(request: HttpRequest) -> dict[str, Any]:
    """Decode a small JSON object for assignment mutation endpoints."""

    if len(request.body) > _MAX_ASSIGNMENT_BODY_BYTES:
        raise InvalidInputError("请求体过大")
    try:
        payload = json.loads(request.body.decode("utf-8") if request.body else "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidInputError("无效 JSON") from exc
    if not isinstance(payload, dict):
        raise InvalidInputError("JSON 请求体必须是对象")
    return cast(dict[str, Any], payload)


def _assignment_error(message: str, status_code: int) -> JsonResponse:
    """Return the project-standard JSON error with a precise response type."""

    response: JsonResponse = _json_error(message, status_code)
    return response


def _validate_assignment_targets(
    *,
    request: Request,
    strategy: object,
    portfolio: object,
) -> None:
    """Require both sides of an assignment to belong to the caller."""

    owner_profile_id = _profile_id(request.user)
    strategy_owner_id = getattr(strategy, "created_by_id", None)
    portfolio_id = getattr(portfolio, "id", None)
    user_id = getattr(request.user, "id", None)
    if owner_profile_id is None or strategy_owner_id != owner_profile_id:
        raise PermissionDenied("策略不存在或无权限访问")
    if (
        isinstance(portfolio_id, bool)
        or not isinstance(portfolio_id, int)
        or isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or not get_simulated_trading_facade().user_owns_account(portfolio_id, user_id)
    ):
        raise PermissionDenied("账户不存在或无权限访问")


class PortfolioStrategyAssignmentViewSet(viewsets.ModelViewSet[Any]):
    """Owner-scoped portfolio and strategy assignments."""

    serializer_class = PortfolioStrategyAssignmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["portfolio", "strategy", "is_active"]
    search_fields = ["portfolio__account_name", "strategy__name"]
    ordering_fields = ["assigned_at", "created_at"]
    ordering = ["-assigned_at"]

    def get_queryset(self) -> Any:
        """Return only assignments owned through both linked resources."""

        return get_assignment_queryset_for_access(
            owner_profile_id=_profile_id(self.request.user),
            include_all=bool(self.request.user.is_staff or self.request.user.is_superuser),
        )

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        """Select the detail serializer for retrieve responses."""

        if self.action == "retrieve":
            return cast(
                type[serializers.BaseSerializer[Any]],
                PortfolioStrategyAssignmentDetailSerializer,
            )
        return cast(
            type[serializers.BaseSerializer[Any]],
            PortfolioStrategyAssignmentSerializer,
        )

    def perform_create(self, serializer: serializers.BaseSerializer[Any]) -> None:
        """Create only when the strategy and portfolio share the caller owner."""

        strategy = serializer.validated_data.get("strategy")
        portfolio = serializer.validated_data.get("portfolio")
        _validate_assignment_targets(
            request=self.request,
            strategy=strategy,
            portfolio=portfolio,
        )
        serializer.save(assigned_by=cast(Any, self.request.user).account_profile)

    def perform_update(self, serializer: serializers.BaseSerializer[Any]) -> None:
        """Prevent reassignment to a strategy or portfolio owned by another user."""

        strategy = serializer.validated_data.get(
            "strategy",
            getattr(serializer.instance, "strategy", None),
        )
        portfolio = serializer.validated_data.get(
            "portfolio",
            getattr(serializer.instance, "portfolio", None),
        )
        _validate_assignment_targets(
            request=self.request,
            strategy=strategy,
            portfolio=portfolio,
        )
        serializer.save()

    @typed_extend_schema(
        summary="获取投资组合的策略列表",
        description="获取指定投资组合的所有策略分配",
        parameters=[
            OpenApiParameter(
                name="portfolio_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="投资组合ID",
            )
        ],
        responses={200: PortfolioStrategyAssignmentSerializer(many=True)},
    )
    @typed_action(detail=False, methods=["get"])
    def by_portfolio(self, request: Request) -> Response:
        """Return assignments for one visible portfolio."""

        raw_portfolio_id = request.query_params.get("portfolio_id")
        if raw_portfolio_id is None or raw_portfolio_id == "":
            return Response(
                {"detail": "必须提供 portfolio_id 参数"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            portfolio_id = int(raw_portfolio_id)
            if portfolio_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"detail": "必须提供正整数 portfolio_id 参数"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignments = list_assignments_by_portfolio_for_access(
            portfolio_id=portfolio_id,
            owner_profile_id=_profile_id(request.user),
            include_all=bool(request.user.is_staff or request.user.is_superuser),
        )
        serializer = self.get_serializer(assignments, many=True)
        return Response(serializer.data)

    @typed_extend_schema(
        summary="激活策略分配",
        description="激活指定的投资组合策略分配",
        responses={200: PortfolioStrategyAssignmentSerializer},
    )
    @typed_action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        """Activate one visible assignment."""

        assignment = self.get_object()
        assignment = set_assignment_active(assignment.id, True) or assignment
        return Response(self.get_serializer(assignment).data)

    @typed_extend_schema(
        summary="停用策略分配",
        description="停用指定的投资组合策略分配",
        responses={200: PortfolioStrategyAssignmentSerializer},
    )
    @typed_action(detail=True, methods=["post"])
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        """Deactivate one visible assignment."""

        assignment = self.get_object()
        assignment = set_assignment_active(assignment.id, False) or assignment
        return Response(self.get_serializer(assignment).data)


@login_required
def bind_strategy(request: HttpRequest) -> JsonResponse:
    """Bind an owned strategy to an owned simulated account."""

    if request.method != "POST":
        return _assignment_error("只支持 POST 请求", status.HTTP_405_METHOD_NOT_ALLOWED)

    try:
        data = _parse_json_object(request)
        unknown_fields = set(data) - {"portfolio_id", "strategy_id"}
        if unknown_fields:
            raise InvalidInputError(f"不支持的参数: {', '.join(sorted(unknown_fields))}")
        if data.get("portfolio_id") is None or data.get("strategy_id") is None:
            raise InvalidInputError("缺少必要参数")
        portfolio_id = _positive_int(data.get("portfolio_id"), field_name="portfolio_id")
        strategy_id = _positive_int(data.get("strategy_id"), field_name="strategy_id")
        profile = getattr(request.user, "account_profile", None)
        profile_id = _profile_id(request.user)
        user_id = getattr(request.user, "id", None)
        if profile_id is None or isinstance(user_id, bool) or not isinstance(user_id, int):
            raise PermissionDenied("当前用户缺少账户资料")

        strategy = get_object_or_404(
            StrategyModel,
            id=strategy_id,
            created_by_id=profile_id,
        )
        if not get_simulated_trading_facade().user_owns_account(portfolio_id, user_id):
            return _assignment_error("账户不存在或无权限访问", status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            bind_strategy_assignment(
                portfolio_id=portfolio_id,
                strategy=strategy,
                assigned_by=profile,
            )
    except InvalidInputError as exc:
        return _assignment_error(exc.message, exc.status_code)
    except PermissionDenied:
        raise
    except Exception:
        logger.exception("Unexpected error while binding strategy")
        return _assignment_error(
            "策略绑定失败，请稍后重试",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return JsonResponse({"success": True, "message": "策略绑定成功"})


@login_required
def unbind_strategy(request: HttpRequest) -> JsonResponse:
    """Unbind all strategies from an owned simulated account."""

    if request.method != "POST":
        return _assignment_error("只支持 POST 请求", status.HTTP_405_METHOD_NOT_ALLOWED)

    try:
        data = _parse_json_object(request)
        unknown_fields = set(data) - {"portfolio_id"}
        if unknown_fields:
            raise InvalidInputError(f"不支持的参数: {', '.join(sorted(unknown_fields))}")
        portfolio_id = _positive_int(data.get("portfolio_id"), field_name="portfolio_id")
        user_id = getattr(request.user, "id", None)
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            raise PermissionDenied("当前用户无效")
        if not get_simulated_trading_facade().user_owns_account(portfolio_id, user_id):
            return _assignment_error("账户不存在或无权限访问", status.HTTP_404_NOT_FOUND)
        unbind_strategy_assignments(portfolio_id)
    except InvalidInputError as exc:
        return _assignment_error(exc.message, exc.status_code)
    except PermissionDenied:
        raise
    except Exception:
        logger.exception("Unexpected error while unbinding strategy")
        return _assignment_error(
            "策略解绑失败，请稍后重试",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return JsonResponse({"success": True, "message": "策略已解绑"})


__all__ = [
    "PortfolioStrategyAssignmentViewSet",
    "bind_strategy",
    "unbind_strategy",
]
