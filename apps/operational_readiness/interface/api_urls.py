"""Operational-readiness administrator API routes."""

from django.urls import path

from apps.operational_readiness.interface.api_views import ReleaseIdentityView

app_name = "operational_readiness"

urlpatterns = [
    path(
        "release-identity/",
        ReleaseIdentityView.as_view(),
        name="release-identity",
    ),
]
