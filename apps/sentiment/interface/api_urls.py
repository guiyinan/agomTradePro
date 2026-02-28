"""
API URL Configuration for Sentiment Module.

This file exposes only API endpoints (no page routes).
Mounted under /api/sentiment/
"""

from django.urls import path
from . import views

app_name = 'sentiment'


urlpatterns = [
    # API routes - Analysis
    path('analyze/', views.SentimentAnalyzeView.as_view(), name='analyze'),
    path('batch-analyze/', views.SentimentBatchAnalyzeView.as_view(), name='batch_analyze'),

    # API routes - Index
    path('index/', views.SentimentIndexView.as_view(), name='index'),
    path('index/range/', views.SentimentIndexRangeView.as_view(), name='index_range'),
    path('index/recent/', views.SentimentIndexRecentView.as_view(), name='index_recent'),

    # API routes - System
    path('health/', views.SentimentHealthView.as_view(), name='health'),
    path('cache/clear/', views.SentimentCacheClearView.as_view(), name='cache_clear'),
]
