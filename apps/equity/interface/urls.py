"""Equity page URL configuration."""

from django.urls import include, path

from .views import detail_page, pool_page, screen_page

app_name = 'equity'

urlpatterns = [
    # Page routes
    path('screen/', screen_page, name='screen'),
    path('detail/<str:stock_code>/', detail_page, name='detail'),
    path('pool/', pool_page, name='pool'),

    # Legacy API compatibility under /equity/api/*
    path('api/', include('apps.equity.interface.api_urls')),
]
