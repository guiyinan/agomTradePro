"""URL configuration for Filter app."""
from django.shortcuts import redirect
from django.urls import path

from . import views

app_name = 'filter'


def filter_home_redirect(request):
    """Redirect root /filter/ to dashboard"""
    return redirect('filter:dashboard')


urlpatterns = [
    # Root route - redirect to dashboard
    path('', filter_home_redirect, name='home'),

    # Page routes
    path('dashboard/', views.filter_dashboard_view, name='dashboard'),
]
