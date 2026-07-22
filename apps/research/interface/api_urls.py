from django.urls import path

from .api_views import ExperimentListCreateView, PromotionEvaluationView, TrialListCreateView

app_name = "research"

urlpatterns = [
    path("experiments/", ExperimentListCreateView.as_view(), name="experiment-list"),
    path("trials/", TrialListCreateView.as_view(), name="trial-list"),
    path("trials/<str:trial_id>/promotion/", PromotionEvaluationView.as_view(), name="promotion"),
]

