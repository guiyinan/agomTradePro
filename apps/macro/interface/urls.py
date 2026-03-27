"""URL configuration for Macro app."""
from django.shortcuts import redirect
from django.urls import path

from . import views

app_name = 'macro'


def macro_home_redirect(request):
    """Redirect root /macro/ to data page"""
    return redirect('macro:data')


urlpatterns = [
    # Root route - redirect to data page
    path('', macro_home_redirect, name='home'),

    path('data/', views.macro_data_view, name='data'),
    path('datasources/', views.datasource_config_view, name='datasources'),
    path('datasources/new/', views.datasource_create_view, name='datasource-create'),
    path('datasources/<int:source_id>/edit/', views.datasource_edit_view, name='datasource-edit'),

    # 统一数据管理器
    path('controller/', views.data_controller_view, name='data_controller'),
]
