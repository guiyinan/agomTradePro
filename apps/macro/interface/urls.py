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

    # API 接口 - 数据抓取 (new standard format - when mounted under /api/macro/)
    path('supported-indicators/', views.api_get_supported_indicators, name='api_get_supported_indicators'),
    path('fetch/stream/', views.api_fetch_data_stream, name='api_fetch_data_stream'),
    path('fetch/', views.api_fetch_data, name='api_fetch_data'),
    path('delete/', views.api_delete_data, name='api_delete_data'),
    path('due-indicators/', views.api_get_due_indicators, name='api_get_due_indicators'),
    path('sync-due/', views.api_sync_due_indicators, name='api_sync_due_indicators'),
    path('indicator-data/', views.api_get_indicator_data, name='api_get_indicator_data'),
    path('quick-sync/', views.api_quick_sync, name='api_quick_sync'),

    # API 接口 - 表格数据管理 (new standard format)
    path('table/', views.api_table_data, name='api_table_data'),
    path('record/<int:record_id>/', views.api_delete_record, name='api_delete_record'),
    path('record/create/', views.api_create_record, name='api_create_record'),
    path('record/<int:record_id>/update/', views.api_update_record, name='api_update_record'),
    path('batch-delete/', views.api_batch_delete, name='api_batch_delete'),

    # API 接口 - legacy format (backward compatibility when mounted under /macro/)
    path('api/supported-indicators/', views.api_get_supported_indicators, name='api_get_supported_indicators_legacy'),
    path('api/fetch/stream/', views.api_fetch_data_stream, name='api_fetch_data_stream_legacy'),
    path('api/fetch/', views.api_fetch_data, name='api_fetch_data_legacy'),
    path('api/delete/', views.api_delete_data, name='api_delete_data_legacy'),
    path('api/due-indicators/', views.api_get_due_indicators, name='api_get_due_indicators_legacy'),
    path('api/sync-due/', views.api_sync_due_indicators, name='api_sync_due_indicators_legacy'),
    path('api/indicator-data/', views.api_get_indicator_data, name='api_get_indicator_data_legacy'),
    path('api/quick-sync/', views.api_quick_sync, name='api_quick_sync_legacy'),
    path('api/table/', views.api_table_data, name='api_table_data_legacy'),
    path('api/record/<int:record_id>/', views.api_delete_record, name='api_delete_record_legacy'),
    path('api/record/create/', views.api_create_record, name='api_create_record_legacy'),
    path('api/record/<int:record_id>/update/', views.api_update_record, name='api_update_record_legacy'),
    path('api/batch-delete/', views.api_batch_delete, name='api_batch_delete_legacy'),
]
