"""
Dashboard URL Configuration
"""

from django.urls import path
from apps.dashboard.interface import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_view, name='index'),
]
