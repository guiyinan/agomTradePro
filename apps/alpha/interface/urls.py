"""Alpha page URL configuration."""

from django.urls import path
from django.views.generic import RedirectView

from apps.alpha.interface import views

app_name = "alpha"

urlpatterns = [
    path("", RedirectView.as_view(url="/alpha/ops/inference/", permanent=False), name="root"),
    path("ops/inference/", views.alpha_ops_inference_page, name="ops-inference"),
    path("ops/qlib-data/", views.alpha_ops_qlib_data_page, name="ops-qlib-data"),
]
