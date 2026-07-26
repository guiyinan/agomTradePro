"""Dashboard macro environment and attention partial views."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.dashboard.application.use_cases import DashboardData
from apps.dashboard.interface.api_auth import dashboard_api_view
from apps.pulse.domain.entities import PulseSnapshot
from apps.regime.domain.action_mapper import RegimeActionRecommendation
from apps.regime.domain.entities import RegimeNavigatorOutput


class _DashboardViewsProtocol(Protocol):
    """Typed legacy patch surface exposed by the main Dashboard views module."""

    def _load_phase1_macro_components(
        self,
    ) -> tuple[
        RegimeNavigatorOutput | None,
        PulseSnapshot | None,
        RegimeActionRecommendation | None,
    ]: ...

    def _build_regime_status_context(
        self,
        navigator: RegimeNavigatorOutput | None,
        pulse: PulseSnapshot | None,
        action: RegimeActionRecommendation | None,
    ) -> dict[str, Any]: ...

    def _build_pulse_card_context(
        self,
        pulse: PulseSnapshot | None,
    ) -> dict[str, Any]: ...

    def _build_action_recommendation_context(
        self,
        action: RegimeActionRecommendation | None,
    ) -> dict[str, Any]: ...

    def _build_dashboard_data(self, user_id: int) -> DashboardData: ...

    def _ensure_dashboard_positions(
        self,
        data: DashboardData,
        user_id: int,
    ) -> DashboardData: ...

    def _build_attention_items_context(
        self,
        data: DashboardData,
        navigator: RegimeNavigatorOutput | None,
        pulse: PulseSnapshot | None,
    ) -> dict[str, Any]: ...


def _dashboard_views() -> _DashboardViewsProtocol:
    """Return the typed legacy module used by existing monkeypatch consumers."""

    from apps.dashboard.interface import views as dashboard_views

    return cast(_DashboardViewsProtocol, dashboard_views)


def _persisted_user_id(request: HttpRequest) -> int:
    """Return the authenticated persisted user id required by portfolio queries."""

    raw_user_id = getattr(request.user, "id", None)
    if isinstance(raw_user_id, bool) or not isinstance(raw_user_id, int) or raw_user_id <= 0:
        raise PermissionDenied("A persisted user is required for dashboard attention items.")
    return raw_user_id


def _dashboard_get_view(
    view: Callable[[HttpRequest], HttpResponse],
) -> Callable[[HttpRequest], HttpResponse]:
    """Keep the typed view signature across the dynamic DRF decorator boundary."""

    return cast(Callable[[HttpRequest], HttpResponse], dashboard_api_view(["GET"])(view))


@_dashboard_get_view
def regime_status_htmx(request: HttpRequest) -> HttpResponse:
    """Render the regime status bar partial for HTMX refreshes."""

    dashboard_views = _dashboard_views()
    navigator, pulse, action = dashboard_views._load_phase1_macro_components()
    context = dashboard_views._build_regime_status_context(navigator, pulse, action)
    return render(request, "components/regime_status_bar.html", context)


@_dashboard_get_view
def pulse_card_htmx(request: HttpRequest) -> HttpResponse:
    """Render the Pulse card partial for HTMX refreshes."""

    dashboard_views = _dashboard_views()
    _, pulse, _ = dashboard_views._load_phase1_macro_components()
    context = dashboard_views._build_pulse_card_context(pulse)
    return render(request, "components/pulse_card.html", context)


@_dashboard_get_view
def action_recommendation_htmx(request: HttpRequest) -> HttpResponse:
    """Render the action recommendation partial for HTMX refreshes."""

    dashboard_views = _dashboard_views()
    _, _, action = dashboard_views._load_phase1_macro_components()
    context = dashboard_views._build_action_recommendation_context(action)
    return render(request, "components/action_recommendation.html", context)


@_dashboard_get_view
def attention_items_htmx(request: HttpRequest) -> HttpResponse:
    """Render today's attention-items partial for HTMX refreshes."""

    dashboard_views = _dashboard_views()
    user_id = _persisted_user_id(request)
    data = dashboard_views._ensure_dashboard_positions(
        dashboard_views._build_dashboard_data(user_id),
        user_id,
    )
    navigator, pulse, _ = dashboard_views._load_phase1_macro_components()
    context = dashboard_views._build_attention_items_context(data, navigator, pulse)
    return render(request, "components/attention_items.html", context)
