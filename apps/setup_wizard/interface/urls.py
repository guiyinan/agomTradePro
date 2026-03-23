"""
URL Configuration for Setup Wizard.
"""

from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from apps.setup_wizard.interface.views import (
    SetupAuthView,
    SetupStepView,
    SetupWizardView,
    check_password_strength,
    setup_logout,
)

app_name = "setup_wizard"

urlpatterns = [
    path("", SetupWizardView.as_view(), name="wizard"),
    path("auth/", SetupAuthView.as_view(), name="auth"),
    path("step/<str:step>/", csrf_exempt(SetupStepView.as_view()), name="step"),
    path("logout/", setup_logout, name="logout"),
    path("api/password-strength/", check_password_strength, name="password_strength"),
]
