"""个股分析模块 Interface 层视图（兼容导出面）

视图实现已拆分到同目录关注点模块；本模块保留稳定的导入面与 legacy
monkeypatch 面（`DjangoStockRepository` 工厂与估值修复/估值数据用例类）。
"""

from typing import Any

from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.equity.application.repository_provider import (
    get_equity_regime_repository,
    get_equity_stock_pool_repository,
    get_equity_stock_repository,
    get_equity_valuation_data_quality_repository,
    get_equity_valuation_repair_repository,
)
from apps.equity.application.use_cases_valuation_repair import (
    GetValuationPercentileHistoryUseCase,
    GetValuationRepairStatusUseCase,
    ScanValuationRepairsUseCase,
)
from apps.equity.application.use_cases_valuation_sync import (
    GetEquityValuationFreshnessUseCase,
    GetLatestEquityValuationQualityUseCase,
    SyncEquityValuationUseCase,
    ValidateEquityValuationQualityUseCase,
)
from apps.equity.interface import valuation_actions as _valuation_actions
from apps.equity.interface.analysis_actions import EquityAnalysisActionsMixin
from apps.equity.interface.multidim_screen_views import EquityMultiDimScreenAPIView
from apps.equity.interface.page_views import (
    detail_page,
    pool_page,
    screen_page,
    valuation_repair_config_page,
    valuation_repair_page,
)
from apps.equity.interface.pool_actions import EquityPoolActionsMixin
from apps.equity.interface.sdk_contract_actions import EquitySDKContractActionsMixin
from apps.equity.interface.valuation_actions import EquityValuationActionsMixin
from apps.equity.interface.valuation_config_views import ValuationRepairConfigViewSet


def DjangoStockRepository() -> Any:
    """Compatibility factory kept for legacy API tests."""

    return get_equity_stock_repository()


def DjangoValuationRepairRepository() -> Any:
    """Compatibility factory kept for legacy API tests."""

    return get_equity_valuation_repair_repository()


class EquityViewSet(
    EquitySDKContractActionsMixin,
    EquityAnalysisActionsMixin,
    EquityPoolActionsMixin,
    EquityValuationActionsMixin,
    viewsets.ViewSet,
):
    """个股分析 API

    Action implementations live in focused owner modules. The valuation-repair
    and valuation-data actions below resolve their use-case classes from this
    module namespace so legacy `apps.equity.interface.views` monkeypatch paths
    keep working.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.stock_repo = DjangoStockRepository()
        self.repair_repo = DjangoValuationRepairRepository()
        self.quality_repo = get_equity_valuation_data_quality_repository()
        self.regime_repo = get_equity_regime_repository()
        self.pool_adapter = get_equity_stock_pool_repository()

    @_valuation_actions.valuation_repair_status_schema
    @_valuation_actions.typed_action(
        detail=False,
        methods=["get"],
        url_path="valuation-repair/(?P<stock_code>(?!scan|list)[^/]+)",
    )
    def get_valuation_repair_status(self, request: Request, stock_code: str) -> Response:
        """GET /api/equity/valuation-repair/{stock_code}/（实时计算，不依赖快照表）"""
        return _valuation_actions.get_valuation_repair_status_impl(
            self, request, stock_code, use_case_cls=GetValuationRepairStatusUseCase
        )

    @_valuation_actions.valuation_repair_history_schema
    @_valuation_actions.typed_action(
        detail=False,
        methods=["get"],
        url_path="valuation-repair/(?P<stock_code>(?!scan|list)[^/]+)/history",
    )
    def get_valuation_repair_history(self, request: Request, stock_code: str) -> Response:
        """GET /api/equity/valuation-repair/{stock_code}/history/（百分位历史序列）"""
        return _valuation_actions.get_valuation_repair_history_impl(
            self, request, stock_code, use_case_cls=GetValuationPercentileHistoryUseCase
        )

    @_valuation_actions.scan_valuation_repairs_schema
    @_valuation_actions.typed_action(
        detail=False, methods=["post"], url_path="valuation-repair/scan"
    )
    def scan_valuation_repairs(self, request: Request) -> Response:
        """POST /api/equity/valuation-repair/scan/（批量计算并保存快照）"""
        return _valuation_actions.scan_valuation_repairs_impl(
            self, request, use_case_cls=ScanValuationRepairsUseCase
        )

    @_valuation_actions.sync_valuation_data_schema
    @_valuation_actions.typed_action(detail=False, methods=["post"], url_path="valuation-data/sync")
    def sync_valuation_data(self, request: Request) -> Response:
        """POST /api/equity/valuation-data/sync/"""
        return _valuation_actions.sync_valuation_data_impl(
            self, request, use_case_cls=SyncEquityValuationUseCase
        )

    @_valuation_actions.validate_valuation_data_schema
    @_valuation_actions.typed_action(
        detail=False, methods=["post"], url_path="valuation-data/validate"
    )
    def validate_valuation_data(self, request: Request) -> Response:
        """POST /api/equity/valuation-data/validate/"""
        return _valuation_actions.validate_valuation_data_impl(
            self, request, use_case_cls=ValidateEquityValuationQualityUseCase
        )

    @_valuation_actions.valuation_data_freshness_schema
    @_valuation_actions.typed_action(
        detail=False, methods=["get"], url_path="valuation-data/freshness"
    )
    def valuation_data_freshness(self, request: Request) -> Response:
        """GET /api/equity/valuation-data/freshness/"""
        return _valuation_actions.valuation_data_freshness_impl(
            self, request, use_case_cls=GetEquityValuationFreshnessUseCase
        )

    @_valuation_actions.valuation_data_quality_latest_schema
    @_valuation_actions.typed_action(
        detail=False, methods=["get"], url_path="valuation-data/quality-latest"
    )
    def valuation_data_quality_latest(self, request: Request) -> Response:
        """GET /api/equity/valuation-data/quality-latest/"""
        return _valuation_actions.valuation_data_quality_latest_impl(
            self, request, use_case_cls=GetLatestEquityValuationQualityUseCase
        )


__all__ = [
    "DjangoStockRepository",
    "DjangoValuationRepairRepository",
    "EquityMultiDimScreenAPIView",
    "EquityViewSet",
    "GetEquityValuationFreshnessUseCase",
    "GetLatestEquityValuationQualityUseCase",
    "GetValuationPercentileHistoryUseCase",
    "GetValuationRepairStatusUseCase",
    "ScanValuationRepairsUseCase",
    "SyncEquityValuationUseCase",
    "ValidateEquityValuationQualityUseCase",
    "ValuationRepairConfigViewSet",
    "detail_page",
    "pool_page",
    "screen_page",
    "valuation_repair_config_page",
    "valuation_repair_page",
]
