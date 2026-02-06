"""
URL configuration for Macro app.
"""
from django.urls import path
from django.shortcuts import redirect
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

    # API 接口 - 数据抓取
    path('api/supported-indicators/', views.api_get_supported_indicators, name='api_get_supported_indicators'),
    path('api/fetch/stream/', views.api_fetch_data_stream, name='api_fetch_data_stream'),
    path('api/fetch/', views.api_fetch_data, name='api_fetch_data'),
    path('api/delete/', views.api_delete_data, name='api_delete_data'),
    path('api/due-indicators/', views.api_get_due_indicators, name='api_get_due_indicators'),
    path('api/sync-due/', views.api_sync_due_indicators, name='api_sync_due_indicators'),
    path('api/indicator-data/', views.api_get_indicator_data, name='api_get_indicator_data'),
    path('api/quick-sync/', views.api_quick_sync, name='api_quick_sync'),  # 新增：快速同步

    # API 接口 - 表格数据管理
    path('api/table/', views.api_table_data, name='api_table_data'),
    path('api/record/<int:record_id>/', views.api_delete_record, name='api_delete_record'),
    path('api/record/create/', views.api_create_record, name='api_create_record'),
    path('api/record/<int:record_id>/update/', views.api_update_record, name='api_update_record'),
    path('api/batch-delete/', views.api_batch_delete, name='api_batch_delete'),
]
