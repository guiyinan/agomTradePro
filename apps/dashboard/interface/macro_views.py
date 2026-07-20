"""Dashboard macro environment and attention partial views."""

from __future__ import annotations

from django.shortcuts import render

from apps.dashboard.interface.api_auth import dashboard_api_view


def _dashboard_views():
    from apps.dashboard.interface import views as dashboard_views

    return dashboard_views


@dashboard_api_view(["GET"])
def regime_status_htmx(request):
    """Render the regime status bar partial for HTMX refreshes."""

    dashboard_views = _dashboard_views()
    navigator, pulse, action = dashboard_views._load_phase1_macro_components()
    context = dashboard_views._build_regime_status_context(navigator, pulse, action)
    return render(request, "components/regime_status_bar.html", context)


@dashboard_api_view(["GET"])
def pulse_card_htmx(request):
    """Render the Pulse card partial for HTMX refreshes."""

    dashboard_views = _dashboard_views()
    _, pulse, _ = dashboard_views._load_phase1_macro_components()
    context = dashboard_views._build_pulse_card_context(pulse)
    return render(request, "components/pulse_card.html", context)


@dashboard_api_view(["GET"])
def action_recommendation_htmx(request):
    """Render the action recommendation partial for HTMX refreshes."""

    dashboard_views = _dashboard_views()
    _, _, action = dashboard_views._load_phase1_macro_components()
    context = dashboard_views._build_action_recommendation_context(action)
    return render(request, "components/action_recommendation.html", context)


@dashboard_api_view(["GET"])
def attention_items_htmx(request):
    """Render today's attention-items partial for HTMX refreshes."""

    dashboard_views = _dashboard_views()
    data = dashboard_views._ensure_dashboard_positions(
        dashboard_views._build_dashboard_data(request.user.id),
        request.user.id,
    )
    navigator, pulse, _ = dashboard_views._load_phase1_macro_components()
    context = dashboard_views._build_attention_items_context(data, navigator, pulse)
    return render(request, "components/attention_items.html", context)
