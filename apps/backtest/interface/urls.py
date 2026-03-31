"""URL Configuration for Backtest Module."""

from django.urls import path

from . import views

app_name = 'backtest'

urlpatterns = [
    # Page URLs
    path('', views.backtest_list_view, name='list'),
    path('create/', views.backtest_create_view, name='create'),
    path('<int:backtest_id>/', views.backtest_detail_view, name='detail'),
]
