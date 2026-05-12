"""
Data Center — API URL Patterns

Mounts all /api/data-center/* endpoints.

Phase 1:  /providers/, /providers/<id>/, /providers/<id>/test/, /providers/status/, /settings/
Phase 2:  /assets/resolve/, /macro/series/, /prices/history/, /prices/quotes/
"""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_center.interface.api_views import (
    asset_resolve,
    capital_flows,
    financials,
    fund_nav_series,
    indicator_detail,
    indicator_list_create,
    indicator_unit_rule_detail,
    indicator_unit_rule_list_create,
    macro_series,
    news,
    price_history,
    price_latest_quote,
    provider_detail,
    provider_list_create,
    provider_settings,
    provider_status,
    provider_test_connection,
    publisher_detail,
    publisher_list_create,
    repair_decision_reliability,
    sector_constituents,
    sync_capital_flows,
    sync_financials,
    sync_fund_nav,
    sync_macro,
    sync_news,
    sync_prices,
    sync_quotes,
    sync_sector_constituents,
    sync_valuations,
    valuations,
)


class DataCenterApiRootView(APIView):
    """Return discoverable data-center API endpoints."""

    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "providers": "/api/data-center/providers/",
                    "provider_status": "/api/data-center/providers/status/",
                    "provider_settings": "/api/data-center/settings/",
                    "publishers": "/api/data-center/publishers/",
                    "indicators": "/api/data-center/indicators/",
                    "asset_resolve": "/api/data-center/assets/resolve/",
                    "macro_series": "/api/data-center/macro/series/",
                    "price_history": "/api/data-center/prices/history/",
                    "price_quotes": "/api/data-center/prices/quotes/",
                    "fund_nav": "/api/data-center/funds/nav/",
                    "financials": "/api/data-center/financials/",
                    "valuations": "/api/data-center/valuations/",
                    "sector_constituents": "/api/data-center/sectors/constituents/",
                    "news": "/api/data-center/news/",
                    "capital_flows": "/api/data-center/capital-flows/",
                    "decision_reliability_repair": "/api/data-center/decision-reliability/repair/",
                }
            }
        )


urlpatterns = [
    path("", DataCenterApiRootView.as_view(), name="dc-api-root"),
    # Provider CRUD
    path("providers/", provider_list_create, name="dc-provider-list"),
    path("providers/<int:provider_id>/", provider_detail, name="dc-provider-detail"),
    path(
        "providers/<int:provider_id>/test/",
        provider_test_connection,
        name="dc-provider-test",
    ),
    # Runtime health
    path("providers/status/", provider_status, name="dc-provider-status"),
    # Global settings
    path("settings/", provider_settings, name="dc-settings"),
    # Publisher governance
    path("publishers/", publisher_list_create, name="dc-publisher-list"),
    path("publishers/<str:publisher_code>/", publisher_detail, name="dc-publisher-detail"),
    # Indicator governance
    path("indicators/", indicator_list_create, name="dc-indicator-list"),
    path("indicators/<str:indicator_code>/", indicator_detail, name="dc-indicator-detail"),
    path(
        "indicators/<str:indicator_code>/unit-rules/",
        indicator_unit_rule_list_create,
        name="dc-indicator-unit-rule-list",
    ),
    path(
        "indicators/<str:indicator_code>/unit-rules/<int:rule_id>/",
        indicator_unit_rule_detail,
        name="dc-indicator-unit-rule-detail",
    ),
    # --- Phase 2: data query endpoints ---
    path("assets/resolve/", asset_resolve, name="dc-asset-resolve"),
    path("macro/series/", macro_series, name="dc-macro-series"),
    path("prices/history/", price_history, name="dc-price-history"),
    path("prices/quotes/", price_latest_quote, name="dc-price-latest-quote"),
    path("funds/nav/", fund_nav_series, name="dc-fund-nav"),
    path("financials/", financials, name="dc-financials"),
    path("valuations/", valuations, name="dc-valuations"),
    path("sectors/constituents/", sector_constituents, name="dc-sector-constituents"),
    path("news/", news, name="dc-news"),
    path("capital-flows/", capital_flows, name="dc-capital-flows"),
    path(
        "decision-reliability/repair/",
        repair_decision_reliability,
        name="dc-decision-reliability-repair",
    ),
    # --- Phase 4: sync endpoints ---
    path("sync/macro/", sync_macro, name="dc-sync-macro"),
    path("sync/prices/", sync_prices, name="dc-sync-prices"),
    path("sync/quotes/", sync_quotes, name="dc-sync-quotes"),
    path("sync/funds/nav/", sync_fund_nav, name="dc-sync-fund-nav"),
    path("sync/financials/", sync_financials, name="dc-sync-financials"),
    path("sync/valuations/", sync_valuations, name="dc-sync-valuations"),
    path(
        "sync/sectors/constituents/",
        sync_sector_constituents,
        name="dc-sync-sector-constituents",
    ),
    path("sync/news/", sync_news, name="dc-sync-news"),
    path("sync/capital-flows/", sync_capital_flows, name="dc-sync-capital-flows"),
]
