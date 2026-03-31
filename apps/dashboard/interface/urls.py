"""
Dashboard URL Configuration
"""

from django.urls import path
from django.views.generic import RedirectView

from apps.dashboard.interface import views

app_name = 'dashboard'

urlpatterns = [
    # Page routes
    path('', views.dashboard_entry, name='index'),
    path('ops-center/', RedirectView.as_view(url='/ops/', permanent=False), name='ops-center'),
]
