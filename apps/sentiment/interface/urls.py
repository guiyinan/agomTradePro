"""
URL Configuration for Sentiment API.

舆情情感分析模块的路由配置。
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

    # API routes - Analysis (new standard format - when mounted under /api/sentiment/)
    path('analyze/', views.SentimentAnalyzeView.as_view(), name='api_analyze'),
    path('batch-analyze/', views.SentimentBatchAnalyzeView.as_view(), name='api_batch_analyze'),

    # API routes - Index (new standard format)
    path('index/', views.SentimentIndexView.as_view(), name='api_index'),
    path('index/range/', views.SentimentIndexRangeView.as_view(), name='api_index_range'),
    path('index/recent/', views.SentimentIndexRecentView.as_view(), name='api_index_recent'),

    # API routes - System (new standard format)
    path('health/', views.SentimentHealthView.as_view(), name='api_health'),
    path('cache/clear/', views.SentimentCacheClearView.as_view(), name='api_cache_clear'),

    # API routes - legacy format (backward compatibility when mounted under /sentiment/)
    path('api/analyze/', views.SentimentAnalyzeView.as_view(), name='api_analyze_legacy'),
    path('api/batch-analyze/', views.SentimentBatchAnalyzeView.as_view(), name='api_batch_analyze_legacy'),
    path('api/index/', views.SentimentIndexView.as_view(), name='api_index_legacy'),
    path('api/index/range/', views.SentimentIndexRangeView.as_view(), name='api_index_range_legacy'),
    path('api/index/recent/', views.SentimentIndexRecentView.as_view(), name='api_index_recent_legacy'),
    path('api/health/', views.SentimentHealthView.as_view(), name='api_health_legacy'),
    path('api/cache/clear/', views.SentimentCacheClearView.as_view(), name='api_cache_clear_legacy'),
]
