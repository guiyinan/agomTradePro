"""Account API URL configuration."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.account.interface import classification_api_views, sizing_views, views
from apps.account.interface.observer_api_views import ObserverGrantViewSet
from apps.account.interface.performance_compat_views import (
    PortfolioBenchmarksCompatView,
    PortfolioPerformanceReportCompatView,
    PortfolioValuationSnapshotCompatView,
    PortfolioValuationTimelineCompatView,
)
from apps.account.interface.portfolio_api_views import PortfolioViewSet, PositionViewSet
from apps.account.interface.profile_api_views import (
    AccountHealthView,
    AccountProfileView,
    AssetMetadataViewSet,
    TradingCostConfigViewSet,
    UserSearchView,
)
from apps.account.interface.transaction_api_views import (
    CapitalFlowViewSet,
    TransactionViewSet,
)
from apps.simulated_trading.interface.performance_views import (
    AccountBackfillAPIView,
    AccountBenchmarksAPIView,
    AccountPerformanceReportAPIView,
    AccountValuationSnapshotAPIView,
    AccountValuationTimelineAPIView,
)
from apps.simulated_trading.interface.views import (
    AccountBatchDeleteAPIView,
    AccountDetailAPIView,
    AccountListAPIView,
    DailyInspectionReportListAPIView,
    DailyInspectionRunAPIView,
    EquityCurveAPIView,
    PerformanceAPIView,
    PositionListAPIView,
    TradeListAPIView,
)

app_name = "account_api"

router = DefaultRouter()
router.register(r"portfolios", PortfolioViewSet, basename="portfolio_api")
router.register(r"positions", PositionViewSet, basename="position_api")
router.register(r"transactions", TransactionViewSet, basename="transaction_api")
router.register(r"capital-flows", CapitalFlowViewSet, basename="capital_flow_api")
router.register(r"assets", AssetMetadataViewSet, basename="asset_api")
router.register(r"observer-grants", ObserverGrantViewSet, basename="observer_grant_api")
router.register(r"trading-cost-configs", TradingCostConfigViewSet, basename="trading_cost_config_api")

classification_router = DefaultRouter()
classification_router.register(r"categories", classification_api_views.AssetCategoryViewSet, basename="category_api")
classification_router.register(r"currencies", classification_api_views.CurrencyViewSet, basename="currency_api")
classification_router.register(r"exchange-rates", classification_api_views.ExchangeRateViewSet, basename="exchange_rate_api")

urlpatterns = [
    path("profile/", AccountProfileView.as_view(), name="profile"),
    path("health/", AccountHealthView.as_view(), name="health"),
    path("users/search/", UserSearchView.as_view(), name="user-search"),
    # 统一账户 canonical API
    path("accounts/", AccountListAPIView.as_view(), name="account-list"),
    path("accounts/batch-delete/", AccountBatchDeleteAPIView.as_view(), name="account-batch-delete"),
    path("accounts/<int:account_id>/", AccountDetailAPIView.as_view(), name="account-detail"),
    path("accounts/<int:account_id>/positions/", PositionListAPIView.as_view(), name="account-position-list"),
    path("accounts/<int:account_id>/trades/", TradeListAPIView.as_view(), name="account-trade-list"),
    path("accounts/<int:account_id>/performance/", PerformanceAPIView.as_view(), name="account-performance"),
    path("accounts/<int:account_id>/performance-report/", AccountPerformanceReportAPIView.as_view(), name="account-performance-report"),
    path("accounts/<int:account_id>/valuation-snapshot/", AccountValuationSnapshotAPIView.as_view(), name="account-valuation-snapshot"),
    path("accounts/<int:account_id>/valuation-timeline/", AccountValuationTimelineAPIView.as_view(), name="account-valuation-timeline"),
    path("accounts/<int:account_id>/benchmarks/", AccountBenchmarksAPIView.as_view(), name="account-benchmarks"),
    path("accounts/<int:account_id>/backfill/", AccountBackfillAPIView.as_view(), name="account-backfill"),
    path("accounts/<int:account_id>/equity-curve/", EquityCurveAPIView.as_view(), name="account-equity-curve"),
    path("accounts/<int:account_id>/inspections/run/", DailyInspectionRunAPIView.as_view(), name="account-inspection-run"),
    path("accounts/<int:account_id>/inspections/", DailyInspectionReportListAPIView.as_view(), name="account-inspection-list"),
    path("", include(router.urls)),
    path("volatility/", views.portfolio_volatility_api_view, name="volatility"),
    path("sizing-context/", sizing_views.SizingContextView.as_view(), name="sizing-context"),
    path("", include(classification_router.urls)),
    path("portfolios/<int:portfolio_id>/allocation/", classification_api_views.PortfolioAllocationView.as_view(), name="portfolio_allocation"),
    # 统一账户业绩兼容入口
    path("portfolios/<int:portfolio_id>/performance-report/", PortfolioPerformanceReportCompatView.as_view(), name="portfolio-performance-report"),
    path("portfolios/<int:portfolio_id>/valuation-snapshot/", PortfolioValuationSnapshotCompatView.as_view(), name="portfolio-valuation-snapshot"),
    path("portfolios/<int:portfolio_id>/valuation-timeline/", PortfolioValuationTimelineCompatView.as_view(), name="portfolio-valuation-timeline"),
    path("portfolios/<int:portfolio_id>/benchmarks/", PortfolioBenchmarksCompatView.as_view(), name="portfolio-benchmarks"),
]
