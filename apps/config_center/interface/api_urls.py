"""API URLs for config center."""

from django.urls import path

from apps.config_center.interface.api_views import (
    QlibRuntimeConfigView,
    QlibTrainingProfileListCreateView,
    QlibTrainingRunDetailView,
    QlibTrainingRunListView,
    QlibTrainingRunTriggerView,
)


urlpatterns = [
    path("qlib/runtime/", QlibRuntimeConfigView.as_view(), name="config-center-qlib-runtime"),
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
        "qlib/training-runs/<str:run_id>/",
        QlibTrainingRunDetailView.as_view(),
        name="config-center-qlib-training-run-detail",
    ),
    path(
        "qlib/training-runs/trigger/",
        QlibTrainingRunTriggerView.as_view(),
        name="config-center-qlib-training-run-trigger",
    ),
]

