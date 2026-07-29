"""
API URL Configuration for Sentiment Module.

This file exposes only API endpoints (no page routes).
Mounted under /api/sentiment/
"""

from django.urls import path
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import views
from .tui_views import SentimentTuiOverviewView

app_name = "sentiment"


class SentimentApiRootView(APIView):
    """Return discoverable Sentiment API endpoints."""

    def get(self, request: Request) -> Response:
        """Return the stable Sentiment API endpoint catalog."""

        del request
        return Response(
            {
                "endpoints": {
                    "analyze": "/api/sentiment/analyze/",
                    "batch_analyze": "/api/sentiment/batch-analyze/",
                    "index": "/api/sentiment/index/",
                    "index_range": "/api/sentiment/index/range/",
                    "index_recent": "/api/sentiment/index/recent/",
                    "health": "/api/sentiment/health/",
                    "cache_clear": "/api/sentiment/cache/clear/",
                    "tui_overview": "/api/sentiment/tui/overview/",
                }
            }
        )


urlpatterns: list[URLPattern | URLResolver] = [
    path("", SentimentApiRootView.as_view(), name="root"),
    # API routes - Analysis
    path("analyze/", views.SentimentAnalyzeView.as_view(), name="analyze"),
    path("batch-analyze/", views.SentimentBatchAnalyzeView.as_view(), name="batch_analyze"),
    # API routes - Index
    path("index/", views.SentimentIndexView.as_view(), name="index"),
    path("index/range/", views.SentimentIndexRangeView.as_view(), name="index_range"),
    path("index/recent/", views.SentimentIndexRecentView.as_view(), name="index_recent"),
    # API routes - System
    path("health/", views.SentimentHealthView.as_view(), name="health"),
    path("cache/clear/", views.SentimentCacheClearView.as_view(), name="cache_clear"),
    path("tui/overview/", SentimentTuiOverviewView.as_view(), name="tui-overview"),
]
