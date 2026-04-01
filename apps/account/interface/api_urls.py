"""Account API URL configuration."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.account.interface import api_views, classification_api_views, sizing_views, views

app_name = "account_api"

router = DefaultRouter()
router.register(r"portfolios", api_views.PortfolioViewSet, basename="portfolio_api")
router.register(r"positions", api_views.PositionViewSet, basename="position_api")
router.register(r"transactions", api_views.TransactionViewSet, basename="transaction_api")
router.register(r"capital-flows", api_views.CapitalFlowViewSet, basename="capital_flow_api")
router.register(r"assets", api_views.AssetMetadataViewSet, basename="asset_api")
router.register(r"observer-grants", api_views.ObserverGrantViewSet, basename="observer_grant_api")
router.register(r"trading-cost-configs", api_views.TradingCostConfigViewSet, basename="trading_cost_config_api")

classification_router = DefaultRouter()
classification_router.register(r"categories", classification_api_views.AssetCategoryViewSet, basename="category_api")
classification_router.register(r"currencies", classification_api_views.CurrencyViewSet, basename="currency_api")
classification_router.register(r"exchange-rates", classification_api_views.ExchangeRateViewSet, basename="exchange_rate_api")

from apps.account.interface.performance_compat_views import (
    PortfolioBenchmarksCompatView,
    PortfolioPerformanceReportCompatView,
    PortfolioValuationSnapshotCompatView,
    PortfolioValuationTimelineCompatView,
)

urlpatterns = [
    path("profile/", api_views.AccountProfileView.as_view(), name="profile"),
    path("health/", api_views.AccountHealthView.as_view(), name="health"),
    path("users/search/", api_views.UserSearchView.as_view(), name="user-search"),
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
