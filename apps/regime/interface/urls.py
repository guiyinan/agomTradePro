"""URL configuration for Regime app."""

from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import path

from . import views

app_name = "regime"


def regime_home_redirect(request: HttpRequest) -> HttpResponseRedirect:
    """Redirect root /regime/ to dashboard"""
    del request
    return redirect("regime:dashboard")


urlpatterns = [
    # Root route - redirect to dashboard
    path("", regime_home_redirect, name="home"),
    # Page routes
    path("dashboard/", views.regime_dashboard_view, name="dashboard"),
    path("clear-cache/", views.clear_regime_cache, name="clear_cache"),
]
