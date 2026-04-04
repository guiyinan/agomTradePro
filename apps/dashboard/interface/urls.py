"""
Dashboard URL Configuration
"""

from django.urls import path

from apps.dashboard.interface import views

app_name = 'dashboard'

urlpatterns = [
    # Page routes
    path('', views.dashboard_entry, name='index'),
]
