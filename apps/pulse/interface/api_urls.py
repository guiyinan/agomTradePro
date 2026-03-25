"""Pulse API URL configuration."""

from django.urls import path

from .api_views import PulseCalculateView, PulseCurrentView, PulseHistoryView

app_name = "pulse_api"

urlpatterns = [
    path("current/", PulseCurrentView.as_view(), name="pulse-current"),
    path("history/", PulseHistoryView.as_view(), name="pulse-history"),
    path("calculate/", PulseCalculateView.as_view(), name="pulse-calculate"),
]
