"""Simulated trading API URL configuration."""

from django.http import JsonResponse
from django.urls import path

from .performance_views import (
    AccountBackfillAPIView,
    AccountBenchmarksAPIView,
    AccountPerformanceReportAPIView,
    AccountValuationSnapshotAPIView,
    AccountValuationTimelineAPIView,
)
from .views import (
    AccountBatchDeleteAPIView,
    AccountDetailAPIView,
    AccountListAPIView,
    AutoTradingAPIView,
    DailyInspectionReportListAPIView,
    DailyInspectionRunAPIView,
    EquityCurveAPIView,
    FeeConfigListAPIView,
    ManualTradeAPIView,
    PerformanceAPIView,
    PositionListAPIView,
    TradeListAPIView,
)

app_name = "simulated_trading_api"


urlpatterns = [
    path(
        "",
        lambda request: JsonResponse(
            {
                "module": "simulated-trading",
                "endpoints": [
                    "/api/simulated-trading/accounts/",
                    "/api/simulated-trading/accounts/batch-delete/",
                    "/api/simulated-trading/accounts/{account_id}/",
                    "/api/simulated-trading/accounts/{account_id}/positions/",
                    "/api/simulated-trading/accounts/{account_id}/trades/",
                    "/api/simulated-trading/accounts/{account_id}/performance/",
                    "/api/simulated-trading/accounts/{account_id}/performance-report/",
                    "/api/simulated-trading/accounts/{account_id}/valuation-snapshot/",
                    "/api/simulated-trading/accounts/{account_id}/valuation-timeline/",
                    "/api/simulated-trading/accounts/{account_id}/benchmarks/",
                ],
            }
        ),
        name="api-root",
    ),
    path("accounts/", AccountListAPIView.as_view(), name="account-list"),
    path("accounts/batch-delete/", AccountBatchDeleteAPIView.as_view(), name="account-batch-delete"),
    path("accounts/<int:account_id>/", AccountDetailAPIView.as_view(), name="account-detail"),
    path("accounts/<int:account_id>/positions/", PositionListAPIView.as_view(), name="position-list"),
    path("accounts/<int:account_id>/trades/", TradeListAPIView.as_view(), name="trade-list"),
    path("accounts/<int:account_id>/performance/", PerformanceAPIView.as_view(), name="performance"),
    path("accounts/<int:account_id>/trade/", ManualTradeAPIView.as_view(), name="manual-trade"),
    path("accounts/<int:account_id>/equity-curve/", EquityCurveAPIView.as_view(), name="equity-curve"),
    path("accounts/<int:account_id>/inspections/run/", DailyInspectionRunAPIView.as_view(), name="daily-inspection-run"),
    path("accounts/<int:account_id>/inspections/", DailyInspectionReportListAPIView.as_view(), name="daily-inspection-list"),
    path("fee-configs/", FeeConfigListAPIView.as_view(), name="fee-config-list"),
    path("auto-trading/run/", AutoTradingAPIView.as_view(), name="auto-trading-run"),
    # 统一账户业绩与估值 API
    path("accounts/<int:account_id>/performance-report/", AccountPerformanceReportAPIView.as_view(), name="performance-report"),
    path("accounts/<int:account_id>/valuation-snapshot/", AccountValuationSnapshotAPIView.as_view(), name="valuation-snapshot"),
    path("accounts/<int:account_id>/valuation-timeline/", AccountValuationTimelineAPIView.as_view(), name="valuation-timeline"),
    path("accounts/<int:account_id>/benchmarks/", AccountBenchmarksAPIView.as_view(), name="benchmarks"),
    path("accounts/<int:account_id>/backfill/", AccountBackfillAPIView.as_view(), name="backfill"),
]
