"""API URL configuration for Setup Wizard."""

from django.urls import path

from apps.setup_wizard.interface.views import check_password_strength

app_name = "setup_wizard_api"

urlpatterns = [
    path("password-strength/", check_password_strength, name="password_strength"),
]
