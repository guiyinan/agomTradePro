"""Page URLs for config center."""

from django.urls import path

from apps.config_center.interface.views import qlib_config_center_view


urlpatterns = [
    path("qlib/", qlib_config_center_view, name="qlib-center"),
]

