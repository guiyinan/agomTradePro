"""URL Configuration for Backtest Module."""

from django.urls import path, include
from django.views.generic import RedirectView
from . import views

app_name = 'backtest'

urlpatterns = [
    # Page URLs
    path('', views.backtest_list_view, name='list'),
    path('list/', RedirectView.as_view(url='/backtest/', permanent=False), name='list-legacy'),
    path('create/', views.backtest_create_view, name='create'),
    path('<int:backtest_id>/', views.backtest_detail_view, name='detail'),
    path('reports/', RedirectView.as_view(url='/audit/reports/', permanent=False), name='reports-legacy'),

    # Legacy API compatibility under /backtest/api/*
    path('api/', include(('apps.backtest.interface.api_urls', 'backtest_api'), namespace='legacy_backtest_api')),
]
