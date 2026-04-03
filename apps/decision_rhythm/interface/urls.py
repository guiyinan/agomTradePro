"""Decision rhythm page URL configuration."""

from django.urls import include, path

from .page_views import decision_rhythm_config_view, decision_rhythm_quota_view

app_name = "decision_rhythm"

urlpatterns = [
    path("", include("apps.decision_rhythm.interface.api_urls")),
    path("decision-rhythm/quota/", decision_rhythm_quota_view, name="quota"),
    path("decision-rhythm/config/", decision_rhythm_config_view, name="config"),
]
