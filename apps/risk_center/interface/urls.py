"""Page routes for risk center."""

from django.urls import path

from apps.risk_center.interface.views import risk_center_console_view

app_name = "risk_center"

urlpatterns = [
    path("", risk_center_console_view, name="console"),
]
