"""
Equity API URL configuration.

This module is mounted under:
- /api/equity/ (primary API prefix)
- /equity/api/ (legacy compatibility prefix)
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import EquityMultiDimScreenAPIView, EquityViewSet

app_name = "equity_api"

router = DefaultRouter()
router.register(r"", EquityViewSet, basename="equity")

urlpatterns = [
    path("", include(router.urls)),
    path("multidim-screen/", EquityMultiDimScreenAPIView.as_view(), name="multidim_screen"),
]

