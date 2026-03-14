"""Filter API URL configuration."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import FilterHealthView, FilterViewSet

app_name = "filter_api"

router = DefaultRouter()
router.register(r"", FilterViewSet, basename="filter")

urlpatterns = [
    path("", include(router.urls)),
    path("health/", FilterHealthView.as_view(), name="health"),
]
