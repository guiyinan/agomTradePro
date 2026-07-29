"""API URLs for config center."""

from django.urls import path

from apps.config_center.interface.api_views import (
    AlphaUniverseConfigListCreateView,
    AlphaUniverseMembersView,
    QlibRuntimeConfigView,
    QlibTrainingProfileListCreateView,
    QlibTrainingRunDetailView,
    QlibTrainingRunListView,
    QlibTrainingRunTriggerView,
    SystemGovernanceSettingsView,
)

urlpatterns = [
    path("settings/", SystemGovernanceSettingsView.as_view(), name="system-settings"),
    path("qlib/runtime/", QlibRuntimeConfigView.as_view(), name="config-center-qlib-runtime"),
    path(
        "qlib/alpha-universes/",
        AlphaUniverseConfigListCreateView.as_view(),
        name="config-center-qlib-alpha-universes",
    ),
    path(
        "qlib/alpha-universes/<str:universe_id>/members/",
        AlphaUniverseMembersView.as_view(),
        name="config-center-qlib-alpha-universe-members",
    ),
    path(
        "qlib/training-profiles/",
        QlibTrainingProfileListCreateView.as_view(),
        name="config-center-qlib-training-profiles",
    ),
    path(
        "qlib/training-runs/",
        QlibTrainingRunListView.as_view(),
        name="config-center-qlib-training-runs",
    ),
    path(
        "qlib/training-runs/trigger/",
        QlibTrainingRunTriggerView.as_view(),
        name="config-center-qlib-training-run-trigger",
    ),
    path(
        "qlib/training-runs/<str:run_id>/",
        QlibTrainingRunDetailView.as_view(),
        name="config-center-qlib-training-run-detail",
    ),
]
