"""Dashboard API URL configuration."""

from django.http import JsonResponse
from django.urls import path

from apps.dashboard.interface import alpha_history_views
from apps.dashboard.interface import alpha_metrics_views
from apps.dashboard.interface import api_v1_views
from apps.dashboard.interface import macro_views
from apps.dashboard.interface import portfolio_views
from apps.dashboard.interface import alpha_stock_views
from apps.dashboard.interface import workflow_views

app_name = "dashboard_api"


def dashboard_api_root(request):
    """Discoverable dashboard API root."""
    return JsonResponse(
        {
            "endpoints": {
                "api_root": "/api/",
                "attention_items": "/api/dashboard/attention-items/",
                "regime_status": "/api/dashboard/regime-status/",
                "pulse_card": "/api/dashboard/pulse-card/",
                "action_recommendation": "/api/dashboard/action-recommendation/",
                "position_detail": "/api/dashboard/position/{asset_code}/",
                "positions": "/api/dashboard/positions/",
                "allocation": "/api/dashboard/allocation/",
                "performance": "/api/dashboard/performance/",
                "v1_summary": "/api/dashboard/v1/summary/",
                "v1_regime_quadrant": "/api/dashboard/v1/regime-quadrant/",
                "v1_equity_curve": "/api/dashboard/v1/equity-curve/",
                "v1_signal_status": "/api/dashboard/v1/signal-status/",
                "v1_alpha_decision_chain": "/api/dashboard/v1/alpha-decision-chain/",
                "alpha_stocks": "/api/dashboard/alpha/stocks/",
                "alpha_refresh": "/api/dashboard/alpha/refresh/",
                "alpha_exit_panel": "/api/dashboard/alpha/exit-panel/",
                "alpha_history": "/api/dashboard/alpha/history/",
                "alpha_history_detail": "/api/dashboard/alpha/history/{run_id}/",
                "alpha_factor_panel": "/api/dashboard/alpha/factor-panel/",
                "alpha_provider_status": "/api/dashboard/alpha/provider-status/",
                "alpha_coverage": "/api/dashboard/alpha/coverage/",
                "alpha_ic_trends": "/api/dashboard/alpha/ic-trends/",
                "workflow_refresh_candidates": "/api/dashboard/workflow/refresh-candidates/",
                "ai_capability": "/api/ai-capability/",
                "documentation_portal": "/docs/",
                "mcp_tools_settings": "/settings/mcp-tools/",
            }
        }
    )


urlpatterns = [
    path("", dashboard_api_root, name="api_root"),
    path("attention-items/", macro_views.attention_items_htmx, name="attention_items"),
    path("regime-status/", macro_views.regime_status_htmx, name="regime_status"),
    path("pulse-card/", macro_views.pulse_card_htmx, name="pulse_card"),
    path(
        "action-recommendation/",
        macro_views.action_recommendation_htmx,
        name="action_recommendation",
    ),
    path(
        "position/<str:asset_code>/",
        portfolio_views.position_detail_htmx,
        name="position_detail",
    ),
    path("positions/", portfolio_views.positions_list_htmx, name="positions_list"),
    path("allocation/", portfolio_views.allocation_chart_htmx, name="allocation"),
    path("performance/", portfolio_views.performance_chart_htmx, name="performance"),
    path("v1/summary/", api_v1_views.dashboard_summary_v1, name="v1_summary"),
    path("v1/regime-quadrant/", api_v1_views.regime_quadrant_v1, name="v1_regime_quadrant"),
    path("v1/equity-curve/", api_v1_views.equity_curve_v1, name="v1_equity_curve"),
    path("v1/signal-status/", api_v1_views.signal_status_v1, name="v1_signal_status"),
    path(
        "v1/alpha-decision-chain/",
        api_v1_views.alpha_decision_chain_v1,
        name="v1_alpha_decision_chain",
    ),
    path("alpha/stocks/", alpha_stock_views.alpha_stocks_htmx, name="alpha_stocks"),
    path("alpha/refresh/", alpha_stock_views.alpha_refresh_htmx, name="alpha_refresh"),
    path("alpha/exit-panel/", alpha_stock_views.alpha_exit_panel_htmx, name="alpha_exit_panel"),
    path("alpha/history/", alpha_history_views.alpha_history_list_api, name="alpha_history_list"),
    path(
        "alpha/history/<int:run_id>/",
        alpha_history_views.alpha_history_detail_api,
        name="alpha_history_detail",
    ),
    path(
        "alpha/factor-panel/",
        alpha_stock_views.alpha_factor_panel_htmx,
        name="alpha_factor_panel",
    ),
    path(
        "alpha/provider-status/",
        alpha_metrics_views.alpha_provider_status_htmx,
        name="alpha_provider_status",
    ),
    path("alpha/coverage/", alpha_metrics_views.alpha_coverage_htmx, name="alpha_coverage"),
    path("alpha/ic-trends/", alpha_metrics_views.alpha_ic_trends_htmx, name="alpha_ic_trends"),
    path(
        "workflow/refresh-candidates/",
        workflow_views.workflow_refresh_candidates,
        name="workflow_refresh_candidates",
    ),
]
