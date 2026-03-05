"""Fund API URL configuration."""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from .views import (
    AnalyzeFundStyleView,
    CalculateFundPerformanceView,
    FundHoldingView,
    FundInfoView,
    FundMultiDimScreenAPIView,
    FundNavView,
    RankFundsView,
    ScreenFundsView,
)

app_name = "fund_api"


class FundApiRootView(APIView):
    """Return discoverable fund API endpoints."""

    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "screen": "/api/fund/screen/",
                    "rank": "/api/fund/rank/",
                    "style": "/api/fund/style/{fund_code}/",
                    "performance": "/api/fund/performance/calculate/",
                    "info": "/api/fund/info/{fund_code}/",
                    "nav": "/api/fund/nav/{fund_code}/",
                    "holding": "/api/fund/holding/{fund_code}/",
                    "multidim_screen": "/api/fund/multidim-screen/",
                }
            }
        )


urlpatterns = [
    path("", FundApiRootView.as_view(), name="api-root"),
    path("screen/", ScreenFundsView.as_view(), name="screen"),
    path("rank/", RankFundsView.as_view(), name="rank"),
    path("style/<str:fund_code>/", AnalyzeFundStyleView.as_view(), name="style"),
    path("performance/calculate/", CalculateFundPerformanceView.as_view(), name="calculate_performance"),
    path("info/<str:fund_code>/", FundInfoView.as_view(), name="info"),
    path("nav/<str:fund_code>/", FundNavView.as_view(), name="nav"),
    path("holding/<str:fund_code>/", FundHoldingView.as_view(), name="holding"),
    path("multidim-screen/", FundMultiDimScreenAPIView.as_view(), name="multidim_screen"),
]

