"""
账户业绩与估值 API 视图

Interface 层：输入验证 + 输出格式化，无业务逻辑、无 ORM 调用。
所有 ORM 操作经由 infrastructure/performance_repositories.py 的仓储类完成。
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import date
from importlib import import_module
from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application.performance_use_cases import (
    AccountRepositoryProtocol,
    BackfillUnifiedAccountHistoryUseCase,
    BenchmarkCRUDUseCase,
    GetAccountPerformanceReportUseCase,
    GetAccountValuationSnapshotUseCase,
    ListAccountValuationTimelineUseCase,
    ObserverGrantRepositoryProtocol,
)

from .performance_serializers import (
    BenchmarkComponentResponseSerializer,
    BenchmarkPutSerializer,
    PerformanceReportQuerySerializer,
    PerformanceReportResponseSerializer,
    ValuationSnapshotQuerySerializer,
    ValuationSnapshotResponseSerializer,
    ValuationTimelineQuerySerializer,
    ValuationTimelineResponseSerializer,
)

logger = logging.getLogger(__name__)

_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _performance_repository_module():
    return import_module("apps.simulated_trading.infrastructure.performance_repositories")


def _build_account_repository():
    return _performance_repository_module().DjangoPerformanceAccountRepository()


def _build_observer_grant_repository():
    return _performance_repository_module().DjangoObserverGrantRepository()


def _build_daily_net_value_repository():
    return _performance_repository_module().DjangoPerformanceDailyNetValueRepository()


def _build_cash_flow_repository():
    return _performance_repository_module().DjangoUnifiedCashFlowRepository()


def _build_benchmark_repository():
    return _performance_repository_module().DjangoBenchmarkComponentRepository()


def _build_market_data_repository():
    return _performance_repository_module().DjangoMarketDataRepository()


def _build_trade_history_repository():
    return _performance_repository_module().DjangoTradeHistoryRepository()


def _build_snapshot_repository():
    return _performance_repository_module().DjangoValuationSnapshotRepository()


def _build_capital_flow_repository():
    return _performance_repository_module().DjangoCapitalFlowRepository()


_ACCOUNT_REPO = _build_account_repository()
_OBSERVER_GRANT_REPO = _build_observer_grant_repository()


# ---------------------------------------------------------------------------
# 权限辅助 — 含 observer 只读支持
# ---------------------------------------------------------------------------


def _get_account_or_403(
    request: Request,
    account_id: int,
    account_repo: AccountRepositoryProtocol,
    observer_grant_repo: ObserverGrantRepositoryProtocol,
):
    """
    返回账户 dict；无权限返回 "forbidden"；不存在返回 None。

    访问规则：
    - 账户所有者 (account.user_id == request.user.pk) → 完全访问
    - 管理员 (request.user.is_staff) → 完全访问
    - 已持有有效 PortfolioObserverGrant 的观察员 → GET/HEAD/OPTIONS 只读访问
    - 其他 → 拒绝
    """
    account = account_repo.get_by_id(account_id)
    if account is None:
        return None

    user = request.user

    # 所有者或管理员
    if account["user_id"] == user.pk or user.is_staff:
        return account

    # 观察员只读
    if request.method in _SAFE_METHODS:
        if observer_grant_repo.has_valid_grant(
            owner_user_id=account["user_id"],
            observer_user_id=user.pk,
        ):
            return account

    return "forbidden"


def _dataclass_to_dict(obj: Any) -> Any:
    """递归将 dataclass / list 转换为可序列化的 dict。"""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _dataclass_to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_dataclass_to_dict(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------
# 视图
# ---------------------------------------------------------------------------


class AccountPerformanceReportAPIView(APIView):
    """
    GET /api/simulated-trading/accounts/{account_id}/performance-report/
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("account_id", int, OpenApiParameter.PATH),
            OpenApiParameter("start_date", str, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("end_date", str, OpenApiParameter.QUERY, required=True),
        ],
        responses={200: PerformanceReportResponseSerializer},
        tags=["Account Performance"],
        summary="账户区间业绩报告",
    )
    def get(self, request: Request, account_id: int) -> Response:
        account = _get_account_or_403(
            request,
            account_id,
            account_repo=_ACCOUNT_REPO,
            observer_grant_repo=_OBSERVER_GRANT_REPO,
        )
        if account is None:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if account == "forbidden":
            return Response({"error": "无权访问"}, status=status.HTTP_403_FORBIDDEN)

        query_ser = PerformanceReportQuerySerializer(data=request.query_params)
        if not query_ser.is_valid():
            return Response(query_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        start_date: date = query_ser.validated_data["start_date"]
        end_date: date = query_ser.validated_data["end_date"]

        use_case = GetAccountPerformanceReportUseCase(
            account_repo=_build_account_repository(),
            daily_net_value_repo=_build_daily_net_value_repository(),
            cash_flow_repo=_build_cash_flow_repository(),
            benchmark_repo=_build_benchmark_repository(),
            market_data_repo=_build_market_data_repository(),
            trade_history_repo=_build_trade_history_repository(),
        )
        try:
            report = use_case.execute(account_id, start_date, end_date)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_dataclass_to_dict(report), status=status.HTTP_200_OK)


class AccountValuationSnapshotAPIView(APIView):
    """
    GET /api/simulated-trading/accounts/{account_id}/valuation-snapshot/
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("account_id", int, OpenApiParameter.PATH),
            OpenApiParameter("as_of_date", str, OpenApiParameter.QUERY, required=True),
        ],
        responses={200: ValuationSnapshotResponseSerializer},
        tags=["Account Performance"],
        summary="账户时点持仓估值表",
    )
    def get(self, request: Request, account_id: int) -> Response:
        account = _get_account_or_403(
            request,
            account_id,
            account_repo=_ACCOUNT_REPO,
            observer_grant_repo=_OBSERVER_GRANT_REPO,
        )
        if account is None:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if account == "forbidden":
            return Response({"error": "无权访问"}, status=status.HTTP_403_FORBIDDEN)

        query_ser = ValuationSnapshotQuerySerializer(data=request.query_params)
        if not query_ser.is_valid():
            return Response(query_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        as_of_date: date = query_ser.validated_data["as_of_date"]
        use_case = GetAccountValuationSnapshotUseCase(
            account_repo=_build_account_repository(),
            valuation_snapshot_repo=_build_snapshot_repository(),
            daily_net_value_repo=_build_daily_net_value_repository(),
        )
        try:
            snapshot = use_case.execute(account_id, as_of_date)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_dataclass_to_dict(snapshot), status=status.HTTP_200_OK)


class AccountValuationTimelineAPIView(APIView):
    """
    GET /api/simulated-trading/accounts/{account_id}/valuation-timeline/
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("account_id", int, OpenApiParameter.PATH),
            OpenApiParameter("start_date", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("end_date", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: ValuationTimelineResponseSerializer},
        tags=["Account Performance"],
        summary="账户净值时间线",
    )
    def get(self, request: Request, account_id: int) -> Response:
        account = _get_account_or_403(
            request,
            account_id,
            account_repo=_ACCOUNT_REPO,
            observer_grant_repo=_OBSERVER_GRANT_REPO,
        )
        if account is None:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if account == "forbidden":
            return Response({"error": "无权访问"}, status=status.HTTP_403_FORBIDDEN)

        query_ser = ValuationTimelineQuerySerializer(data=request.query_params)
        if not query_ser.is_valid():
            return Response(query_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        start_date = query_ser.validated_data.get("start_date")
        end_date = query_ser.validated_data.get("end_date")

        use_case = ListAccountValuationTimelineUseCase(
            account_repo=_build_account_repository(),
            daily_net_value_repo=_build_daily_net_value_repository(),
            cash_flow_repo=_build_cash_flow_repository(),
        )
        try:
            points = use_case.execute(account_id, start_date, end_date)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"points": _dataclass_to_dict(points)}, status=status.HTTP_200_OK)


class AccountBenchmarksAPIView(APIView):
    """
    GET|PUT /api/simulated-trading/accounts/{account_id}/benchmarks/
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("account_id", int, OpenApiParameter.PATH)],
        responses={200: BenchmarkComponentResponseSerializer(many=True)},
        tags=["Account Performance"],
        summary="获取账户基准成分配置",
    )
    def get(self, request: Request, account_id: int) -> Response:
        account = _get_account_or_403(
            request,
            account_id,
            account_repo=_ACCOUNT_REPO,
            observer_grant_repo=_OBSERVER_GRANT_REPO,
        )
        if account is None:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if account == "forbidden":
            return Response({"error": "无权访问"}, status=status.HTTP_403_FORBIDDEN)

        use_case = BenchmarkCRUDUseCase(
            benchmark_repo=_build_benchmark_repository()
        )
        components = use_case.get(account_id)
        return Response([dataclasses.asdict(c) for c in components], status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[OpenApiParameter("account_id", int, OpenApiParameter.PATH)],
        request=BenchmarkPutSerializer,
        responses={200: BenchmarkComponentResponseSerializer(many=True)},
        tags=["Account Performance"],
        summary="更新账户基准成分配置（全量覆盖，权重自动归一化）",
    )
    def put(self, request: Request, account_id: int) -> Response:
        account = _get_account_or_403(
            request,
            account_id,
            account_repo=_ACCOUNT_REPO,
            observer_grant_repo=_OBSERVER_GRANT_REPO,
        )
        if account is None:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if account == "forbidden":
            return Response({"error": "无权访问"}, status=status.HTTP_403_FORBIDDEN)

        body_ser = BenchmarkPutSerializer(data=request.data)
        if not body_ser.is_valid():
            return Response(body_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        use_case = BenchmarkCRUDUseCase(
            benchmark_repo=_build_benchmark_repository()
        )
        try:
            components = use_case.put(
                account_id, body_ser.validated_data["components"]
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response([dataclasses.asdict(c) for c in components], status=status.HTTP_200_OK)


class AccountBackfillAPIView(APIView):
    """
    POST /api/simulated-trading/accounts/{account_id}/backfill/

    触发账户历史数据回填：
    - 写入初始入金现金流
    - 真实盘：镜像 CapitalFlowModel 到统一现金流表
    - 验证日净值序列是否存在

    仅管理员可操作。
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("account_id", int, OpenApiParameter.PATH)],
        tags=["Account Performance"],
        summary="触发账户历史回填（admin only）",
    )
    def post(self, request: Request, account_id: int) -> Response:
        if not request.user.is_staff:
            return Response(
                {"error": "仅管理员可触发回填"}, status=status.HTTP_403_FORBIDDEN
            )

        account = _ACCOUNT_REPO.get_by_id(account_id)
        if account is None:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)

        use_case = BackfillUnifiedAccountHistoryUseCase(
            account_repo=_build_account_repository(),
            cash_flow_repo=_build_cash_flow_repository(),
            daily_net_value_repo=_build_daily_net_value_repository(),
            capital_flow_repo=_build_capital_flow_repository(),
        )
        try:
            result = use_case.execute(account_id)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)
