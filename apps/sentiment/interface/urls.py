"""
URL Configuration for Sentiment Module.

This file contains only page routes (HTML views).
API routes are in api_urls.py and mounted under /api/sentiment/

Note: Legacy API routes (api/*) are kept for backward compatibility.
New code should use /api/sentiment/ endpoints.
"""

from django.shortcuts import redirect
from django.urls import path

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

    # Note: Legacy API routes have been removed to avoid duplication.
    # All API routes are now handled by api_urls.py mounted at /api/sentiment/
    # If you need backward compatibility with /sentiment/api/* URLs,
    # please update your client to use /api/sentiment/* instead.
]
