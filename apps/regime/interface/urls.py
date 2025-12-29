"""
URL configuration for Regime app.
"""
from django.urls import path
from . import views


app_name = 'regime'


urlpatterns = [
    path('dashboard/', views.regime_dashboard_view, name='dashboard'),
]
