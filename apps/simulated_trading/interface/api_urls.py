"""Simulated trading API URL configuration."""

from django.http import JsonResponse
from django.urls import path

from .fee_correction_policy_views import FeeCorrectionPolicyAPIView
from .fee_correction_views import (
    FeeCorrectionAPIView,
    FeeCorrectionConfirmationAPIView,
    FeeCorrectionEvidenceUploadAPIView,
    FeeCorrectionHeadAPIView,
    FeeCorrectionPreviewAPIView,
    FeeCorrectionRecoveryAPIView,
    FeeCorrectionRecoveryHeadAPIView,
)
from .order_history_views import (
    SimulatedOrderDecisionHistoryAPIView,
    SimulatedOrderFillHistoryAPIView,
    SimulatedOrderHistoryAPIView,
)
from .performance_views import (
    AccountBackfillAPIView,
    AccountBenchmarksAPIView,
    AccountPerformanceReportAPIView,
    AccountValuationSnapshotAPIView,
    AccountValuationTimelineAPIView,
)
from .sdk_contract_views import AccountResetAPIView, PositionCloseAPIView
from .tui_views import InspectionNotificationConfigAPIView
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
                    "/api/simulated-trading/accounts/{account_id}/orders/",
                    "/api/simulated-trading/accounts/{account_id}/orders/{order_id}/fills/",
                    "/api/simulated-trading/accounts/{account_id}/orders/{order_id}/decisions/",
                    "/api/simulated-trading/accounts/{account_id}/fee-correction-policy/",
                    "/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/fee-correction-evidence/",
                    "/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/fee-correction-preview/",
                    "/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/fee-corrections/",
                    "/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/fee-corrections/confirm/",
                    "/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/fee-corrections/head/",
                    "/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/fee-corrections/recovery/",
                    "/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/fee-corrections/recovery/{source_locator}/head/",
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
    path(
        "accounts/batch-delete/", AccountBatchDeleteAPIView.as_view(), name="account-batch-delete"
    ),
    path("accounts/<int:account_id>/", AccountDetailAPIView.as_view(), name="account-detail"),
    path(
        "accounts/<int:account_id>/orders/",
        SimulatedOrderHistoryAPIView.as_view(),
        name="order-history",
    ),
    path(
        "accounts/<int:account_id>/orders/<int:order_id>/fills/",
        SimulatedOrderFillHistoryAPIView.as_view(),
        name="order-fill-history",
    ),
    path(
        "accounts/<int:account_id>/orders/<int:order_id>/decisions/",
        SimulatedOrderDecisionHistoryAPIView.as_view(),
        name="order-decision-history",
    ),
    path(
        "accounts/<int:account_id>/positions/", PositionListAPIView.as_view(), name="position-list"
    ),
    path(
        "accounts/<int:account_id>/positions/close/",
        PositionCloseAPIView.as_view(),
        name="position-close",
    ),
    path("accounts/<int:account_id>/trades/", TradeListAPIView.as_view(), name="trade-list"),
    path(
        "accounts/<int:account_id>/fee-correction-policy/",
        FeeCorrectionPolicyAPIView.as_view(),
        name="fee-correction-policy",
    ),
    path(
        "accounts/<int:account_id>/trades/<int:trade_id>/fee-correction-evidence/",
        FeeCorrectionEvidenceUploadAPIView.as_view(),
        name="fee-correction-evidence",
    ),
    path(
        "accounts/<int:account_id>/trades/<int:trade_id>/fee-corrections/",
        FeeCorrectionAPIView.as_view(),
        name="fee-correction",
    ),
    path(
        "accounts/<int:account_id>/trades/<int:trade_id>/fee-correction-preview/",
        FeeCorrectionPreviewAPIView.as_view(),
        name="fee-correction-preview",
    ),
    path(
        "accounts/<int:account_id>/trades/<int:trade_id>/fee-corrections/confirm/",
        FeeCorrectionConfirmationAPIView.as_view(),
        name="fee-correction-confirmation",
    ),
    path(
        "accounts/<int:account_id>/trades/<int:trade_id>/fee-corrections/head/",
        FeeCorrectionHeadAPIView.as_view(),
        name="fee-correction-head",
    ),
    path(
        "accounts/<int:account_id>/trades/<int:trade_id>/fee-corrections/recovery/",
        FeeCorrectionRecoveryAPIView.as_view(),
        name="fee-correction-recovery",
    ),
    path(
        "accounts/<int:account_id>/trades/<int:trade_id>/fee-corrections/recovery/<uuid:source_locator>/head/",
        FeeCorrectionRecoveryHeadAPIView.as_view(),
        name="fee-correction-recovery-head",
    ),
    path(
        "accounts/<int:account_id>/performance/", PerformanceAPIView.as_view(), name="performance"
    ),
    path("accounts/<int:account_id>/trade/", ManualTradeAPIView.as_view(), name="manual-trade"),
    path("accounts/<int:account_id>/reset/", AccountResetAPIView.as_view(), name="account-reset"),
    path(
        "accounts/<int:account_id>/equity-curve/", EquityCurveAPIView.as_view(), name="equity-curve"
    ),
    path(
        "accounts/<int:account_id>/inspections/run/",
        DailyInspectionRunAPIView.as_view(),
        name="daily-inspection-run",
    ),
    path(
        "accounts/<int:account_id>/inspections/",
        DailyInspectionReportListAPIView.as_view(),
        name="daily-inspection-list",
    ),
    path(
        "accounts/<int:account_id>/inspection-notification/",
        InspectionNotificationConfigAPIView.as_view(),
        name="inspection-notification-config",
    ),
    path("fee-configs/", FeeConfigListAPIView.as_view(), name="fee-config-list"),
    path("auto-trading/run/", AutoTradingAPIView.as_view(), name="auto-trading-run"),
    # 统一账户业绩与估值 API
    path(
        "accounts/<int:account_id>/performance-report/",
        AccountPerformanceReportAPIView.as_view(),
        name="performance-report",
    ),
    path(
        "accounts/<int:account_id>/valuation-snapshot/",
        AccountValuationSnapshotAPIView.as_view(),
        name="valuation-snapshot",
    ),
    path(
        "accounts/<int:account_id>/valuation-timeline/",
        AccountValuationTimelineAPIView.as_view(),
        name="valuation-timeline",
    ),
    path(
        "accounts/<int:account_id>/benchmarks/",
        AccountBenchmarksAPIView.as_view(),
        name="benchmarks",
    ),
    path("accounts/<int:account_id>/backfill/", AccountBackfillAPIView.as_view(), name="backfill"),
]
