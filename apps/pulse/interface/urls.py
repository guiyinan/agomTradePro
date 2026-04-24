"""Pulse page URL configuration."""

from django.urls import path

from .views import PulseIndexView

app_name = "pulse"

urlpatterns = [
    path("", PulseIndexView.as_view(), name="index"),
]
