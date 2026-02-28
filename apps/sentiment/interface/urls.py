"""
URL Configuration for Sentiment Module.

This file contains only page routes (HTML views).
API routes are in api_urls.py and mounted under /api/sentiment/
"""

from django.urls import path
from django.shortcuts import redirect
from . import views

app_name = 'sentiment'


def sentiment_home_redirect(request):
    """Redirect root /sentiment/ to dashboard"""
    return redirect('sentiment:dashboard')


urlpatterns = [
    # Root route - redirect to dashboard
    path('', sentiment_home_redirect, name='home'),

    # HTML page routes
    path('dashboard/', views.SentimentDashboardView.as_view(), name='dashboard'),
    path('analyze/', views.SentimentAnalyzePageView.as_view(), name='analyze'),

    # Legacy API routes (backward compatibility when mounted under /sentiment/)
    # These are kept for backward compatibility but new code should use /api/sentiment/
    path('api/analyze/', views.SentimentAnalyzeView.as_view(), name='analyze_legacy'),
    path('api/batch-analyze/', views.SentimentBatchAnalyzeView.as_view(), name='batch_analyze_legacy'),
    path('api/index/', views.SentimentIndexView.as_view(), name='index_legacy'),
    path('api/index/range/', views.SentimentIndexRangeView.as_view(), name='index_range_legacy'),
    path('api/index/recent/', views.SentimentIndexRecentView.as_view(), name='index_recent_legacy'),
    path('api/health/', views.SentimentHealthView.as_view(), name='health_legacy'),
    path('api/cache/clear/', views.SentimentCacheClearView.as_view(), name='cache_clear_legacy'),
]
