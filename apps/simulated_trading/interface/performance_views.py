"""
账户业绩与估值 API 视图

Interface 层：输入验证 + 输出格式化，无业务逻辑。
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application.performance_use_cases import (
    BackfillUnifiedAccountHistoryUseCase,
    BenchmarkCRUDUseCase,
    GetAccountPerformanceReportUseCase,
    GetAccountValuationSnapshotUseCase,
    ListAccountValuationTimelineUseCase,
)
from apps.simulated_trading.infrastructure.models import (
    AccountBenchmarkComponentModel,
    AccountPositionValuationSnapshotModel,
    DailyNetValueModel,
    SimulatedAccountModel,
    UnifiedAccountCashFlowModel,
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


# ---------------------------------------------------------------------------
# 基础设施适配器（内联实现 Protocol，避免额外文件）
# ---------------------------------------------------------------------------


class _AccountRepo:
    """AccountRepositoryProtocol 实现（内联）。"""

    def get_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        try:
            obj = SimulatedAccountModel.objects.get(pk=account_id)
        except SimulatedAccountModel.DoesNotExist:
            return None
        return {
            "account_id": obj.pk,
            "account_name": obj.account_name,
            "account_type": obj.account_type,
            "initial_capital": float(obj.initial_capital),
            "current_cash": float(obj.current_cash),
            "total_value": float(obj.total_value),
            "start_date": obj.start_date,
            "user_id": obj.user_id,
        }


class _BenchmarkRepo:
    """BenchmarkComponentRepositoryProtocol 实现（内联）。"""

    def list_active(self, account_id: int) -> List[Dict[str, Any]]:
        qs = AccountBenchmarkComponentModel.objects.filter(
            account_id=account_id, is_active=True
        ).order_by("sort_order")
        return [
            {
                "benchmark_code": obj.benchmark_code,
                "weight": obj.weight,
                "display_name": obj.display_name,
                "sort_order": obj.sort_order,
                "is_active": obj.is_active,
            }
            for obj in qs
        ]

    def upsert_components(self, account_id: int, components: List[Dict[str, Any]]) -> None:
        AccountBenchmarkComponentModel.objects.filter(account_id=account_id).delete()
        AccountBenchmarkComponentModel.objects.bulk_create([
            AccountBenchmarkComponentModel(
                account_id=account_id,
                benchmark_code=c["benchmark_code"],
                weight=float(c["weight"]),
                display_name=c.get("display_name", ""),
                sort_order=int(c.get("sort_order", i)),
                is_active=True,
            )
            for i, c in enumerate(components)
        ])


class _CashFlowRepo:
    """UnifiedCashFlowRepositoryProtocol 实现（内联）。"""

    def list_for_account(
        self,
        account_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        qs = UnifiedAccountCashFlowModel.objects.filter(account_id=account_id)
        if start_date:
            qs = qs.filter(flow_date__gte=start_date)
        if end_date:
            qs = qs.filter(flow_date__lte=end_date)
        qs = qs.order_by("flow_date")
        return [
            {
                "flow_id": obj.pk,
                "account_id": obj.account_id,
                "flow_type": obj.flow_type,
                "amount": float(obj.amount),
                "flow_date": obj.flow_date,
                "source_app": obj.source_app,
                "source_id": obj.source_id,
                "notes": obj.notes,
            }
            for obj in qs
        ]

    def create_initial_capital(self, account_id: int, amount: float, flow_date: date) -> None:
        UnifiedAccountCashFlowModel.objects.get_or_create(
            account_id=account_id,
            flow_type="initial_capital",
            defaults={
                "amount": amount,
                "flow_date": flow_date,
                "source_app": "simulated_trading",
                "source_id": "",
                "notes": "初始入金（自动回填）",
            },
        )

    def mirror_from_capital_flow(self, account_id: int, capital_flow_dict: Dict[str, Any]) -> None:
        source_id = str(capital_flow_dict.get("id", ""))
        flow_type_map = {
            "deposit": "deposit",
            "withdraw": "withdrawal",
            "dividend": "dividend",
            "interest": "interest",
            "adjustment": "adjustment",
        }
        flow_type = flow_type_map.get(capital_flow_dict.get("flow_type", ""), "adjustment")
        UnifiedAccountCashFlowModel.objects.update_or_create(
            account_id=account_id,
            source_app="account",
            source_id=source_id,
            defaults={
                "flow_type": flow_type,
                "amount": float(capital_flow_dict.get("amount", 0)),
                "flow_date": capital_flow_dict.get("flow_date"),
                "notes": capital_flow_dict.get("notes", ""),
            },
        )


class _DailyNetValueRepo:
    """DailyNetValueRepositoryProtocol 实现（内联）。"""

    def list_range(
        self,
        account_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        qs = DailyNetValueModel.objects.filter(account_id=account_id)
        if start_date:
            qs = qs.filter(record_date__gte=start_date)
        if end_date:
            qs = qs.filter(record_date__lte=end_date)
        qs = qs.order_by("record_date")
        return [
            {
                "record_date": obj.record_date,
                "cash": float(obj.cash),
                "market_value": float(obj.market_value),
                "total_value": float(obj.net_value) * float(
                    SimulatedAccountModel.objects.filter(pk=account_id)
                    .values_list("initial_capital", flat=True)
                    .first() or 1
                ),
                "net_value": float(obj.net_value),
                "daily_return": float(obj.daily_return),
                "cumulative_return": float(obj.cumulative_return),
                "drawdown": float(obj.drawdown),
            }
            for obj in qs
        ]


class _ValuationSnapshotRepo:
    """ValuationSnapshotRepositoryProtocol 实现（内联）。"""

    def get_for_date(self, account_id: int, record_date: date) -> List[Dict[str, Any]]:
        qs = AccountPositionValuationSnapshotModel.objects.filter(
            account_id=account_id, record_date=record_date
        ).order_by("-market_value")
        return [
            {
                "asset_code": obj.asset_code,
                "asset_name": obj.asset_name,
                "asset_type": obj.asset_type,
                "quantity": float(obj.quantity),
                "avg_cost": float(obj.avg_cost),
                "close_price": float(obj.close_price),
                "market_value": float(obj.market_value),
                "weight": obj.weight,
                "unrealized_pnl": float(obj.unrealized_pnl),
                "unrealized_pnl_pct": obj.unrealized_pnl_pct,
            }
            for obj in qs
        ]

    def upsert_snapshot(
        self,
        account_id: int,
        record_date: date,
        rows: List[Dict[str, Any]],
    ) -> None:
        AccountPositionValuationSnapshotModel.objects.filter(
            account_id=account_id, record_date=record_date
        ).delete()
        AccountPositionValuationSnapshotModel.objects.bulk_create([
            AccountPositionValuationSnapshotModel(
                account_id=account_id,
                record_date=record_date,
                asset_code=r["asset_code"],
                asset_name=r.get("asset_name", ""),
                asset_type=r.get("asset_type", "equity"),
                quantity=r["quantity"],
                avg_cost=r.get("avg_cost", 0),
                close_price=r.get("close_price", 0),
                market_value=r["market_value"],
                weight=r.get("weight", 0),
                unrealized_pnl=r.get("unrealized_pnl", 0),
                unrealized_pnl_pct=r.get("unrealized_pnl_pct", 0),
            )
            for r in rows
        ])


class _TradeHistoryRepo:
    """TradeHistoryRepositoryProtocol 实现（内联）。"""

    def list_closed_trades(
        self,
        account_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
        qs = SimulatedTradeModel.objects.filter(
            account_id=account_id,
            action="sell",
            status="executed",
            realized_pnl__isnull=False,
        )
        if start_date:
            qs = qs.filter(execution_date__gte=start_date)
        if end_date:
            qs = qs.filter(execution_date__lte=end_date)
        return [{"realized_pnl": float(obj.realized_pnl)} for obj in qs]


class _NullMarketDataRepo:
    """MarketDataRepositoryProtocol 空实现（占位，后续注入真实数据源）。"""

    def get_close_price(self, asset_code: str, trade_date: date):
        return None

    def get_index_daily_returns(self, index_code: str, start_date: date, end_date: date):
        return []

    def get_index_cumulative_return(self, index_code: str, start_date: date, end_date: date):
        return None


# ---------------------------------------------------------------------------
# 账户权限辅助
# ---------------------------------------------------------------------------


def _get_account_or_403(request: Request, account_id: int):
    """返回账户 ORM 对象；非所有者或管理员则返回 None（触发 403）。"""
    try:
        account = SimulatedAccountModel.objects.get(pk=account_id)
    except SimulatedAccountModel.DoesNotExist:
        return None
    user = request.user
    if account.user_id != user.pk and not user.is_staff:
        return "forbidden"
    return account


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
        account = _get_account_or_403(request, account_id)
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
            account_repo=_AccountRepo(),
            daily_net_value_repo=_DailyNetValueRepo(),
            cash_flow_repo=_CashFlowRepo(),
            benchmark_repo=_BenchmarkRepo(),
            market_data_repo=_NullMarketDataRepo(),
            trade_history_repo=_TradeHistoryRepo(),
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
        account = _get_account_or_403(request, account_id)
        if account is None:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if account == "forbidden":
            return Response({"error": "无权访问"}, status=status.HTTP_403_FORBIDDEN)

        query_ser = ValuationSnapshotQuerySerializer(data=request.query_params)
        if not query_ser.is_valid():
            return Response(query_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        as_of_date: date = query_ser.validated_data["as_of_date"]
        use_case = GetAccountValuationSnapshotUseCase(
            account_repo=_AccountRepo(),
            valuation_snapshot_repo=_ValuationSnapshotRepo(),
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
        account = _get_account_or_403(request, account_id)
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
            account_repo=_AccountRepo(),
            daily_net_value_repo=_DailyNetValueRepo(),
            cash_flow_repo=_CashFlowRepo(),
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
        account = _get_account_or_403(request, account_id)
        if account is None:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if account == "forbidden":
            return Response({"error": "无权访问"}, status=status.HTTP_403_FORBIDDEN)

        use_case = BenchmarkCRUDUseCase(benchmark_repo=_BenchmarkRepo())
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
        account = _get_account_or_403(request, account_id)
        if account is None:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if account == "forbidden":
            return Response({"error": "无权访问"}, status=status.HTTP_403_FORBIDDEN)

        body_ser = BenchmarkPutSerializer(data=request.data)
        if not body_ser.is_valid():
            return Response(body_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        use_case = BenchmarkCRUDUseCase(benchmark_repo=_BenchmarkRepo())
        try:
            components = use_case.put(account_id, body_ser.validated_data["components"])
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response([dataclasses.asdict(c) for c in components], status=status.HTTP_200_OK)


class AccountBackfillAPIView(APIView):
    """
    POST /api/simulated-trading/accounts/{account_id}/backfill/

    触发账户历史数据回填（初始入金现金流写入等）。
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
            return Response({"error": "仅管理员可触发回填"}, status=status.HTTP_403_FORBIDDEN)

        try:
            SimulatedAccountModel.objects.get(pk=account_id)
        except SimulatedAccountModel.DoesNotExist:
            return Response({"error": "账户不存在"}, status=status.HTTP_404_NOT_FOUND)

        use_case = BackfillUnifiedAccountHistoryUseCase(
            account_repo=_AccountRepo(),
            cash_flow_repo=_CashFlowRepo(),
            daily_net_value_repo=_DailyNetValueRepo(),
        )
        try:
            result = use_case.execute(account_id)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)
