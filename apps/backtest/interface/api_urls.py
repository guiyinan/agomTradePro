"""Backtest API URL configuration."""

from django.urls import include, path
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from . import views

app_name = "backtest_api"

router = DefaultRouter()
router.register(r"backtests", views.BacktestViewSet, basename="backtest")


class BacktestApiRootView(APIView):
    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "backtests": "/api/backtest/backtests/",
                    "statistics": "/api/backtest/statistics/",
                    "run": "/api/backtest/run/",
                }
            }
        )


urlpatterns = [
    path("", BacktestApiRootView.as_view(), name="api-root"),
    path("statistics/", views.backtest_statistics_api_view, name="statistics-api"),
    path("run/", views.run_backtest_api_view, name="run-api"),
    path("", include(router.urls)),
]
