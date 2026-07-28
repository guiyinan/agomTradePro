"""Valuation-repair and valuation-data actions for the equity API viewset.

Owns `EquityValuationActionsMixin` plus module-level implementations for the
actions whose use-case classes stay patchable through the legacy
`apps.equity.interface.views` namespace (the facade injects them as
`use_case_cls`). Do not import the compatibility facade here.
"""

from collections.abc import Callable
from typing import Any, ParamSpec, Protocol, TypeVar, cast

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.equity.application.use_cases_valuation_repair import (
    ListValuationRepairsRequest,
    ListValuationRepairsUseCase,
)
from apps.equity.application.use_cases_valuation_sync import (
    SyncEquityValuationRequest,
    ValidateEquityValuationQualityRequest,
)

from .serializers import (
    ListValuationRepairsRequestSerializer,
    ListValuationRepairsResponseSerializer,
    ScanValuationRepairsRequestSerializer,
    ScanValuationRepairsResponseSerializer,
    SyncFinancialDataRequestSerializer,
    SyncFinancialDataResponseSerializer,
    SyncValuationDataRequestSerializer,
    SyncValuationDataResponseSerializer,
    ValidateValuationDataRequestSerializer,
    ValuationFreshnessResponseSerializer,
    ValuationQualitySnapshotResponseSerializer,
    ValuationRepairHistoryResponseSerializer,
    ValuationRepairStatusResponseSerializer,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


class _PreservingDecorator(Protocol):
    """Describe a third-party decorator that preserves a callable signature."""

    def __call__(self, func: Callable[_P, _R], /) -> Callable[_P, _R]: ...


def _typed_decorator(decorator: object) -> _PreservingDecorator:
    """Narrow an untyped framework decorator without changing runtime behavior."""

    return cast(_PreservingDecorator, decorator)


# OpenAPI declarations for the facade valuation actions. The facade applies
# these prebuilt decorators so its thin methods stay bounded without losing
# the established API schema contract.
valuation_repair_status_schema = extend_schema(
    summary="获取估值修复状态",
    description="获取单只股票的估值修复状态（实时计算）",
    responses={200: ValuationRepairStatusResponseSerializer},
)
valuation_repair_history_schema = extend_schema(
    summary="获取估值修复历史",
    description="获取估值百分位历史序列（实时计算）",
    responses={200: ValuationRepairHistoryResponseSerializer},
)
scan_valuation_repairs_schema = extend_schema(
    summary="批量扫描估值修复",
    description="批量扫描股票池并保存快照",
    request=ScanValuationRepairsRequestSerializer,
    responses={200: ScanValuationRepairsResponseSerializer},
)
sync_valuation_data_schema = extend_schema(
    summary="同步估值数据",
    description="从主备 provider 同步估值数据到本地估值表",
    request=SyncValuationDataRequestSerializer,
    responses={200: SyncValuationDataResponseSerializer},
)
validate_valuation_data_schema = extend_schema(
    summary="校验估值数据质量",
    description="对本地估值表生成质量快照并计算 gate 状态",
    request=ValidateValuationDataRequestSerializer,
    responses={200: ValuationQualitySnapshotResponseSerializer},
)
valuation_data_freshness_schema = extend_schema(
    summary="获取估值数据新鲜度",
    description="返回本地估值表最新交易日和 freshness 状态",
    responses={200: ValuationFreshnessResponseSerializer},
)
valuation_data_quality_latest_schema = extend_schema(
    summary="获取最近估值数据质量快照",
    description="返回最近一次估值数据质量快照",
    responses={200: ValuationQualitySnapshotResponseSerializer},
)


def _percentile_chart_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scale canonical ratio fields into user-facing percentage chart rows."""

    return [
        {
            "trade_date": str(row.get("trade_date") or ""),
            "pe_percentile_percent": (
                round(float(row["pe_percentile"]) * 100, 6)
                if row.get("pe_percentile") is not None
                else None
            ),
            "pb_percentile_percent": round(float(row.get("pb_percentile") or 0) * 100, 6),
            "composite_percentile_percent": round(
                float(row.get("composite_percentile") or 0) * 100,
                6,
            ),
        }
        for row in rows
    ]


class EquityValuationActionsMixin:
    """Snapshot listing and financial-data sync actions."""

    repair_repo: Any

    @_typed_decorator(
        extend_schema(
            summary="同步财务数据",
            description="同步指定股票的财务数据（ROE、营收、利润等）",
            request=SyncFinancialDataRequestSerializer,
            responses={200: SyncFinancialDataResponseSerializer},
        )
    )
    @_typed_decorator(action(detail=False, methods=["post"], url_path="financial-data/sync"))
    def sync_financial_data(self, request: Request) -> Response:
        """同步财务数据"""
        from apps.equity.application.tasks_valuation_sync import sync_financial_data_task

        stock_codes = request.data.get("stock_codes")
        periods = request.data.get("periods", 8)
        source = request.data.get("source", "akshare")

        # 异步执行同步任务
        result = sync_financial_data_task(
            source=source,
            periods=periods,
            stock_codes=stock_codes,
        )

        return Response(result, status=status.HTTP_200_OK)

    @_typed_decorator(
        extend_schema(
            summary="列出估值修复快照",
            description="列出估值修复快照（不触发实时重算）",
            request=ListValuationRepairsRequestSerializer,
            responses={200: ListValuationRepairsResponseSerializer},
        )
    )
    @_typed_decorator(action(detail=False, methods=["get"], url_path="valuation-repair-list"))
    def list_valuation_repairs(self, request: Request) -> Response:
        """
        GET /api/equity/valuation-repair-list/

        列出估值修复快照

        直接读取快照表，不触发实时重算。

        Query Parameters:
        - universe: all_active 或 current_pool（默认 all_active）
        - phase: 阶段过滤（可选）
        - limit: 返回数量限制（默认 50）

        Response:
        {
            "success": true,
            "results": [
                {
                    "stock_code": "600030.SH",
                    "stock_name": "中信证券",
                    "phase": "repairing",
                    "signal": "hold",
                    "composite_percentile": 0.28,
                    "repair_progress": 0.45,
                    "repair_speed_per_30d": 0.08,
                    "repair_duration_trading_days": 30,
                    "estimated_days_to_target": 82,
                    "is_stalled": false,
                    "as_of_date": "2026-03-10"
                },
                ...
            ]
        }
        """
        # 1. 验证并获取参数
        try:
            limit = int(request.query_params.get("limit", 50))
            if limit < 1 or limit > 200:
                return Response(
                    {"success": False, "error": "limit must be between 1 and 200"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (ValueError, TypeError):
            return Response(
                {"success": False, "error": "limit must be a valid integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. 构造请求对象
        use_case_request = ListValuationRepairsRequest(
            universe=request.query_params.get("universe", "all_active"),
            phase=request.query_params.get("phase"),
            limit=limit,
        )

        # 2. 执行用例
        use_case_type: type[Any] = ListValuationRepairsUseCase
        use_case = use_case_type(valuation_repair_repository=self.repair_repo)
        use_case_response = use_case.execute(use_case_request)

        # 3. 返回响应
        if use_case_response.success:
            return Response(
                {"success": True, "results": use_case_response.data}, status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"success": False, "error": use_case_response.error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ==================== 估值修复跟踪 API 实现 ====================
# These implementations receive their use-case class through the facade so the
# legacy `apps.equity.interface.views` monkeypatch surface keeps working.


def get_valuation_repair_status_impl(
    viewset: Any,
    request: Request,
    stock_code: str,
    *,
    use_case_cls: type[Any],
) -> Response:
    """实现 GET /api/equity/valuation-repair/{stock_code}/（实时计算估值修复状态）。"""
    from apps.equity.application.use_cases_valuation_repair import (
        GetValuationRepairStatusRequest,
    )

    # 1. 获取并验证 lookback_days 参数
    try:
        lookback_days = int(request.query_params.get("lookback_days", 756))
        if lookback_days < 30 or lookback_days > 2520:
            return Response(
                {"success": False, "error": "lookback_days must be between 30 and 2520"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    except (ValueError, TypeError):
        return Response(
            {"success": False, "error": "lookback_days must be a valid integer"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 2. 构造请求对象
    use_case_request = GetValuationRepairStatusRequest(
        stock_code=stock_code, lookback_days=lookback_days
    )

    # 3. 执行用例
    use_case = use_case_cls(
        stock_repository=viewset.stock_repo,
        valuation_repair_repository=viewset.repair_repo,
        valuation_quality_repository=viewset.quality_repo,
    )
    use_case_response = use_case.execute(use_case_request)

    # 4. 返回响应
    if use_case_response.success:
        return Response(use_case_response.data, status=status.HTTP_200_OK)
    else:
        return Response(
            {"success": False, "error": use_case_response.error},
            status=status.HTTP_400_BAD_REQUEST,
        )


def get_valuation_repair_history_impl(
    viewset: Any,
    request: Request,
    stock_code: str,
    *,
    use_case_cls: type[Any],
) -> Response:
    """实现 GET /api/equity/valuation-repair/{stock_code}/history/（百分位历史序列）。"""
    from apps.equity.application.use_cases_valuation_repair import (
        GetValuationPercentileHistoryRequest,
    )

    # 1. 获取并验证 lookback_days 参数
    try:
        lookback_days = int(request.query_params.get("lookback_days", 252))
        if lookback_days < 30 or lookback_days > 2520:
            return Response(
                {"success": False, "error": "lookback_days must be between 30 and 2520"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    except (ValueError, TypeError):
        return Response(
            {"success": False, "error": "lookback_days must be a valid integer"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 2. 构造请求对象
    use_case_request = GetValuationPercentileHistoryRequest(
        stock_code=stock_code, lookback_days=lookback_days
    )

    # 3. 执行用例
    use_case = use_case_cls(stock_repository=viewset.stock_repo)
    use_case_response = use_case.execute(use_case_request)

    # 4. 返回响应
    if use_case_response.success:
        latest_snapshot = viewset.quality_repo.get_latest_snapshot()
        points = [row for row in use_case_response.data if isinstance(row, dict)]
        return Response(
            {
                "stock_code": stock_code,
                "points": points,
                "chart_points": _percentile_chart_points(points),
                "data_quality_flag": (
                    "ok" if (latest_snapshot and latest_snapshot.is_gate_passed) else None
                ),
                "data_source_provider": "local_db",
                "data_as_of_date": (
                    latest_snapshot.as_of_date.isoformat() if latest_snapshot else None
                ),
            },
            status=status.HTTP_200_OK,
        )
    else:
        return Response(
            {"success": False, "error": use_case_response.error},
            status=status.HTTP_400_BAD_REQUEST,
        )


def scan_valuation_repairs_impl(
    viewset: Any,
    request: Request,
    *,
    use_case_cls: type[Any],
) -> Response:
    """实现 POST /api/equity/valuation-repair/scan/（批量扫描并保存快照）。"""
    from apps.equity.application.use_cases_valuation_repair import (
        ScanValuationRepairsRequest,
    )

    # 1. 验证请求
    serializer = ScanValuationRepairsRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # 2. 构造请求对象
    use_case_request = ScanValuationRepairsRequest(
        universe=data.get("universe", "all_active"),
        lookback_days=data.get("lookback_days", 756),
        limit=None,
    )

    # 3. 执行用例
    use_case = use_case_cls(
        stock_repository=viewset.stock_repo,
        valuation_repair_repository=viewset.repair_repo,
        stock_pool_adapter=viewset.pool_adapter,
        valuation_quality_repository=viewset.quality_repo,
    )
    use_case_response = use_case.execute(use_case_request)

    # 4. 返回响应
    if use_case_response.success:
        response_data = {
            "success": True,
            "universe": use_case_response.universe,
            "as_of_date": use_case_response.as_of_date.isoformat(),
            "scanned_count": use_case_response.scanned_count,
            "saved_count": use_case_response.saved_count,
            "phase_counts": use_case_response.phase_counts,
        }
        return Response(response_data, status=status.HTTP_200_OK)
    else:
        return Response(
            {"success": False, "error": use_case_response.error},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def sync_valuation_data_impl(
    viewset: Any,
    request: Request,
    *,
    use_case_cls: type[Any],
) -> Response:
    """实现 POST /api/equity/valuation-data/sync/（同步估值数据到本地估值表）。"""
    serializer = SyncValuationDataRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    use_case = use_case_cls(stock_repository=viewset.stock_repo)
    response = use_case.execute(
        SyncEquityValuationRequest(
            stock_codes=data.get("stock_codes"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            days_back=data.get("days_back", 1),
            primary_source=data.get("primary_source", "akshare"),
            fallback_source=data.get("fallback_source", "tushare"),
        )
    )
    if response.success:
        return Response(response.data, status=status.HTTP_200_OK)
    return Response({"success": False, "error": response.error}, status=status.HTTP_400_BAD_REQUEST)


def validate_valuation_data_impl(
    viewset: Any,
    request: Request,
    *,
    use_case_cls: type[Any],
) -> Response:
    """实现 POST /api/equity/valuation-data/validate/（质量快照与 gate 状态）。"""
    serializer = ValidateValuationDataRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    use_case = use_case_cls(
        stock_repository=viewset.stock_repo,
        quality_repository=viewset.quality_repo,
    )
    response = use_case.execute(
        ValidateEquityValuationQualityRequest(
            as_of_date=data.get("as_of_date"),
            primary_source=data.get("primary_source", "akshare"),
        )
    )
    if response.success:
        return Response(response.data, status=status.HTTP_200_OK)
    return Response({"success": False, "error": response.error}, status=status.HTTP_400_BAD_REQUEST)


def valuation_data_freshness_impl(
    viewset: Any,
    request: Request,
    *,
    use_case_cls: type[Any],
) -> Response:
    """实现 GET /api/equity/valuation-data/freshness/（估值数据新鲜度）。"""
    use_case = use_case_cls(
        stock_repository=viewset.stock_repo,
        quality_repository=viewset.quality_repo,
    )
    response = use_case.execute()
    if response.success:
        return Response(response.data, status=status.HTTP_200_OK)
    return Response({"success": False, "error": response.error}, status=status.HTTP_400_BAD_REQUEST)


def valuation_data_quality_latest_impl(
    viewset: Any,
    request: Request,
    *,
    use_case_cls: type[Any],
) -> Response:
    """实现 GET /api/equity/valuation-data/quality-latest/（最近质量快照）。"""
    use_case = use_case_cls(
        quality_repository=viewset.quality_repo,
    )
    response = use_case.execute()
    if response.success:
        return Response(response.data, status=status.HTTP_200_OK)
    return Response({"success": False, "error": response.error}, status=status.HTTP_400_BAD_REQUEST)


__all__ = [
    "EquityValuationActionsMixin",
    "get_valuation_repair_history_impl",
    "get_valuation_repair_status_impl",
    "scan_valuation_repairs_impl",
    "scan_valuation_repairs_schema",
    "sync_valuation_data_impl",
    "sync_valuation_data_schema",
    "validate_valuation_data_impl",
    "validate_valuation_data_schema",
    "valuation_data_freshness_impl",
    "valuation_data_freshness_schema",
    "valuation_data_quality_latest_impl",
    "valuation_data_quality_latest_schema",
    "valuation_repair_history_schema",
    "valuation_repair_status_schema",
]
