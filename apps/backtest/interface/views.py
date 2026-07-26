"""
Views for Backtest Module.

包含页面视图和 API 视图。
"""

import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.throttling import BacktestRateThrottle, WriteRateThrottle

from ..application.decision_replay import (
    DecisionReplayBacktestRequest,
    DecisionReplayBacktestUseCase,
)
from ..application.interface_services import (
    backtest_exists,
    delete_backtest_payload,
    get_backtest_equity_curve_payload,
    get_backtest_result_payload,
    get_backtest_statistics_payload,
    list_backtests_payload,
    load_backtest_create_context,
    load_backtest_detail_context,
    load_backtest_list_context,
    run_backtest_payload,
)
from .serializers import (
    BacktestStatisticsSerializer,
    DecisionReplayBacktestSerializer,
    RunBacktestSerializer,
)

logger = logging.getLogger(__name__)
_MAX_BACKTEST_LIST_LIMIT = 500


def _authenticated_user_id(request: HttpRequest | Request) -> int:
    """Return a persisted authenticated user identifier or fail closed."""

    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise PermissionDenied("authenticated_user_id_required")
    return user_id


def _parse_positive_identifier(raw_value: object, *, field_name: str) -> int:
    """Parse a positive integer path/query identifier."""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, str)):
        raise ValueError(f"{field_name} must be a positive integer")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


# ==================== Page Views ====================


@login_required(login_url="/account/login/")
def backtest_list_view(request: HttpRequest) -> HttpResponse:
    """回测列表页面"""
    return render(
        request,
        "backtest/list.html",
        load_backtest_list_context(user_id=_authenticated_user_id(request), limit=20),
    )


@login_required(login_url="/account/login/")
def backtest_detail_view(request: HttpRequest, backtest_id: int) -> HttpResponse:
    """回测详情页面"""
    context = load_backtest_detail_context(
        backtest_id,
        user_id=_authenticated_user_id(request),
    )
    if context is None:
        return JsonResponse({"error": "Backtest not found"}, status=404)
    return render(request, "backtest/detail.html", context)


@login_required(login_url="/account/login/")
def backtest_create_view(request: HttpRequest) -> HttpResponse:
    """创建回测页面"""
    return render(request, "backtest/create.html", load_backtest_create_context())


# ==================== API Views (DRF) ====================


class BacktestViewSet(viewsets.ViewSet):
    """回测 API 视图集

    P0-2: 应用分层限流（限流逻辑在 throttle 类内部按请求方法过滤）

    限流策略：
    - BacktestRateThrottle: 仅对 POST (create) 生效，10/hour
    - WriteRateThrottle: 对 POST/PUT/PATCH/DELETE 生效，100/hour
    - GET (list/retrieve/statistics): 仅使用默认全局限流，不受上述限制

    配置方式（settings.py 或环境变量）：
    - REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['backtest'] 或 DRF_THROTTLE_BACKTEST
    - REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['write'] 或 DRF_THROTTLE_WRITE
    """

    # P0-2: 分层限流配置
    # 注意：限流类内部已实现方法过滤，GET 请求不会触发这些限流
    throttle_classes = [BacktestRateThrottle, WriteRateThrottle]
    permission_classes = [IsAuthenticated]

    def list(self, request: Request) -> Response:
        """列出所有回测"""
        status_filter = request.query_params.get("status")
        limit_param = request.query_params.get("limit")
        limit = None
        if limit_param not in (None, ""):
            try:
                limit = _parse_positive_identifier(limit_param, field_name="limit")
            except ValueError as exc:
                return Response(
                    {"error": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if limit > _MAX_BACKTEST_LIST_LIMIT:
                return Response(
                    {"error": f"limit must not exceed {_MAX_BACKTEST_LIST_LIMIT}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(
            list_backtests_payload(
                user_id=_authenticated_user_id(request),
                status_filter=status_filter,
                limit=limit,
            )
        )

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        """获取回测详情"""
        try:
            backtest_id = _parse_positive_identifier(pk, field_name="backtest_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        response = get_backtest_result_payload(
            backtest_id,
            user_id=_authenticated_user_id(request),
        )

        if response["error"]:
            return Response({"error": "Backtest not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "id": response["backtest_id"],
                "name": response["name"],
                "status": response["status"],
                "result": response["result"],
            }
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="equity-curve",
        permission_classes=[IsAdminUser],
    )
    def equity_curve(self, request: Request, pk: str | None = None) -> Response:
        """Return one persisted equity curve without running a backtest."""
        try:
            backtest_id = _parse_positive_identifier(pk, field_name="backtest_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        payload = get_backtest_equity_curve_payload(backtest_id)
        if payload is None:
            return Response(
                {"error": "Backtest not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(payload)

    def create(self, request: Request) -> Response:
        """创建并运行回测"""
        serializer = RunBacktestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        response = run_backtest_payload(
            dict(serializer.validated_data),
            user_id=_authenticated_user_id(request),
        )

        if response.status == "failed":
            return Response(
                {
                    "error": "Backtest failed",
                    "error_code": "backtest_execution_failed",
                    "warnings": response.warnings,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "backtest_id": response.backtest_id,
                "status": response.status,
                "result": response.result,
                "warnings": response.warnings,
            },
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        """删除回测"""
        try:
            backtest_id = _parse_positive_identifier(pk, field_name="backtest_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        response = delete_backtest_payload(
            backtest_id,
            user_id=_authenticated_user_id(request),
        )

        if not response["success"]:
            return Response({"error": "Backtest not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response({"message": "Backtest deleted successfully"})

    @action(detail=False, methods=["get"])
    def statistics(self, request: Request) -> Response:
        """获取统计信息"""
        serializer = BacktestStatisticsSerializer(
            get_backtest_statistics_payload(user_id=_authenticated_user_id(request))
        )
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def rerun(self, request: Request, pk: str | None = None) -> Response:
        """重新运行回测"""
        try:
            backtest_id = _parse_positive_identifier(pk, field_name="backtest_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if not backtest_exists(
            backtest_id,
            user_id=_authenticated_user_id(request),
        ):
            return Response({"error": "Backtest not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "error": "Backtest rerun is not implemented",
                "error_code": "backtest_rerun_not_implemented",
            },
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


# ==================== Utility Views ====================


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def backtest_statistics_api_view(request: Request) -> JsonResponse:
    """获取回测统计（独立 API）"""
    response = get_backtest_statistics_payload(user_id=_authenticated_user_id(request))

    return JsonResponse(
        {
            "total": response.total,
            "by_status": response.by_status,
            "avg_return": response.avg_return,
            "max_return": response.max_return,
            "min_return": response.min_return,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def run_backtest_api_view(request: Request) -> Response:
    """运行回测（独立 API）"""
    serializer = RunBacktestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    response = run_backtest_payload(
        dict(serializer.validated_data),
        user_id=_authenticated_user_id(request),
    )

    if response.status == "failed":
        return Response(
            {
                "error": "Backtest failed",
                "error_code": "backtest_execution_failed",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(
        {
            "backtest_id": response.backtest_id,
            "status": response.status,
            "result": response.result,
            "warnings": response.warnings,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def decision_replay_backtest_api_view(request: Request) -> Response:
    """Run a manual decision replay branch backtest."""

    serializer = DecisionReplayBacktestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    response = DecisionReplayBacktestUseCase().execute(
        DecisionReplayBacktestRequest(
            user_id=_authenticated_user_id(request),
            portfolio_id=data["portfolio_id"],
            start_date=data["start_date"],
            end_date=data["end_date"],
            branch_type=data["branch_type"],
            initial_capital=data["initial_capital"],
        )
    )
    if not response.success:
        logger.warning(
            "Decision replay backtest failed: backtest_id=%s error=%s",
            response.backtest_id,
            response.error,
        )
        return Response(
            {
                "backtest_id": response.backtest_id,
                "error": "Decision replay backtest failed",
                "error_code": "decision_replay_failed",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response({"backtest_id": response.backtest_id}, status=status.HTTP_201_CREATED)
