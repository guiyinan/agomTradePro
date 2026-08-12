from django.urls import path

from .api_views import ExperimentListCreateView, PromotionEvaluationView, TrialListCreateView
from .evidence_api_views import (
    EvidenceEnvelopeDetailView,
    EvidenceOperatorSpecDetailView,
    EvidenceTrackRecordDetailView,
)

app_name = "research"

urlpatterns = [
    path("experiments/", ExperimentListCreateView.as_view(), name="experiment-list"),
    path("trials/", TrialListCreateView.as_view(), name="trial-list"),
    path("trials/<str:trial_id>/promotion/", PromotionEvaluationView.as_view(), name="promotion"),
    path(
        "evidence/operator-specs/<str:operator_id>/versions/<str:operator_version>/",
        EvidenceOperatorSpecDetailView.as_view(),
        name="evidence-operator-spec-detail",
    ),
    path(
        "evidence/track-records/<str:snapshot_id>/versions/<str:snapshot_version>/",
        EvidenceTrackRecordDetailView.as_view(),
        name="evidence-track-record-detail",
    ),
    path(
        "evidence/envelopes/<str:output_owner>/<str:output_artifact_type>/"
        "<str:output_artifact_id>/versions/<str:output_artifact_version>/",
        EvidenceEnvelopeDetailView.as_view(),
        name="evidence-envelope-detail",
    ),
]
