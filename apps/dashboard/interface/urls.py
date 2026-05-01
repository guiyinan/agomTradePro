"""
Dashboard URL Configuration
"""

from django.urls import path

from apps.dashboard.interface import alpha_history_views
from apps.dashboard.interface import views

app_name = 'dashboard'

urlpatterns = [
    # Page routes
    path('', views.dashboard_entry, name='index'),
    path('alpha/history/', alpha_history_views.alpha_history_page, name='alpha_history'),
]
