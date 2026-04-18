"""Dashboard API URL configuration."""

from django.http import JsonResponse
from django.urls import path

from apps.dashboard.interface import views

app_name = "dashboard_api"


def dashboard_api_root(request):
    """Discoverable dashboard API root."""
    return JsonResponse(
        {
            "endpoints": {
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
                "alpha_history": "/api/dashboard/alpha/history/",
                "alpha_history_detail": "/api/dashboard/alpha/history/{run_id}/",
                "alpha_factor_panel": "/api/dashboard/alpha/factor-panel/",
                "alpha_provider_status": "/api/dashboard/alpha/provider-status/",
                "alpha_coverage": "/api/dashboard/alpha/coverage/",
                "alpha_ic_trends": "/api/dashboard/alpha/ic-trends/",
                "workflow_refresh_candidates": "/api/dashboard/workflow/refresh-candidates/",
            }
        }
    )


urlpatterns = [
    path("", dashboard_api_root, name="api_root"),
    path("attention-items/", views.attention_items_htmx, name="attention_items"),
    path("regime-status/", views.regime_status_htmx, name="regime_status"),
    path("pulse-card/", views.pulse_card_htmx, name="pulse_card"),
    path(
        "action-recommendation/",
        views.action_recommendation_htmx,
        name="action_recommendation",
    ),
    path("position/<str:asset_code>/", views.position_detail_htmx, name="position_detail"),
    path("positions/", views.positions_list_htmx, name="positions_list"),
    path("allocation/", views.allocation_chart_htmx, name="allocation"),
    path("performance/", views.performance_chart_htmx, name="performance"),
    path("v1/summary/", views.dashboard_summary_v1, name="v1_summary"),
    path("v1/regime-quadrant/", views.regime_quadrant_v1, name="v1_regime_quadrant"),
    path("v1/equity-curve/", views.equity_curve_v1, name="v1_equity_curve"),
    path("v1/signal-status/", views.signal_status_v1, name="v1_signal_status"),
    path(
        "v1/alpha-decision-chain/",
        views.alpha_decision_chain_v1,
        name="v1_alpha_decision_chain",
    ),
    path("alpha/stocks/", views.alpha_stocks_htmx, name="alpha_stocks"),
    path("alpha/refresh/", views.alpha_refresh_htmx, name="alpha_refresh"),
    path("alpha/history/", views.alpha_history_list_api, name="alpha_history_list"),
    path("alpha/history/<int:run_id>/", views.alpha_history_detail_api, name="alpha_history_detail"),
    path("alpha/factor-panel/", views.alpha_factor_panel_htmx, name="alpha_factor_panel"),
    path("alpha/provider-status/", views.alpha_provider_status_htmx, name="alpha_provider_status"),
    path("alpha/coverage/", views.alpha_coverage_htmx, name="alpha_coverage"),
    path("alpha/ic-trends/", views.alpha_ic_trends_htmx, name="alpha_ic_trends"),
    path("workflow/refresh-candidates/", views.workflow_refresh_candidates, name="workflow_refresh_candidates"),
]
