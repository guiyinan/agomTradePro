"""Backtest API URL configuration."""

from django.urls import include, path
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from . import views

app_name = "backtest_api"

router = DefaultRouter()
router.register(r"backtests", views.BacktestViewSet, basename="backtest")


class BacktestApiRootView(APIView):
    """Return the discoverable backtest API directory."""

    def get(self, request: Request) -> Response:
        """Return stable backtest endpoints."""

        del request
        return Response(
            {
                "endpoints": {
                    "backtests": "/api/backtest/backtests/",
                    "statistics": "/api/backtest/statistics/",
                    "run": "/api/backtest/run/",
                    "decision_replay": "/api/backtest/decision-replay/",
                    "tui_decision_replay": "/api/backtest/tui/decision-replay/",
                }
            }
        )


urlpatterns = [
    path("", BacktestApiRootView.as_view(), name="api-root"),
    path("statistics/", views.backtest_statistics_api_view, name="statistics-api"),
    path("run/", views.run_backtest_api_view, name="run-api"),
    path("decision-replay/", views.decision_replay_backtest_api_view, name="decision-replay-api"),
    path(
        "tui/decision-replay/",
        views.decision_replay_comparison_api_view,
        name="tui-decision-replay-api",
    ),
    path("", include(router.urls)),
]
