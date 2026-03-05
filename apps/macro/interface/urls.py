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
    path('supported-indicators/', views.api_get_supported_indicators, name='get_supported_indicators'),
    path('fetch/stream/', views.api_fetch_data_stream, name='fetch_data_stream'),
    path('fetch/', views.api_fetch_data, name='fetch_data'),
    path('delete/', views.api_delete_data, name='delete_data'),
    path('due-indicators/', views.api_get_due_indicators, name='get_due_indicators'),
    path('sync-due/', views.api_sync_due_indicators, name='sync_due_indicators'),
    path('indicator-data/', views.api_get_indicator_data, name='get_indicator_data'),
    path('quick-sync/', views.api_quick_sync, name='quick_sync'),

    # API 接口 - 表格数据管理 (new standard format)
    path('table/', views.api_table_data, name='table_data'),
    path('record/<int:record_id>/', views.api_delete_record, name='delete_record'),
    path('record/create/', views.api_create_record, name='create_record'),
    path('record/<int:record_id>/update/', views.api_update_record, name='update_record'),
    path('batch-delete/', views.api_batch_delete, name='batch_delete'),

    # API 接口 - legacy format (backward compatibility when mounted under /macro/)
    # Keep these aliases to avoid breaking existing templates/scripts still calling /macro/api/*.
    path('api/supported-indicators/', views.api_get_supported_indicators, name='get_supported_indicators_legacy'),
    path('api/fetch/stream/', views.api_fetch_data_stream, name='fetch_data_stream_legacy'),
    path('api/fetch/', views.api_fetch_data, name='fetch_data_legacy'),
    path('api/delete/', views.api_delete_data, name='delete_data_legacy'),
    path('api/due-indicators/', views.api_get_due_indicators, name='get_due_indicators_legacy'),
    path('api/sync-due/', views.api_sync_due_indicators, name='sync_due_indicators_legacy'),
    path('api/indicator-data/', views.api_get_indicator_data, name='get_indicator_data_legacy'),
    path('api/quick-sync/', views.api_quick_sync, name='quick_sync_legacy'),
    path('api/table/', views.api_table_data, name='table_data_legacy'),
    path('api/record/<int:record_id>/', views.api_delete_record, name='delete_record_legacy'),
    path('api/record/create/', views.api_create_record, name='create_record_legacy'),
    path('api/record/<int:record_id>/update/', views.api_update_record, name='update_record_legacy'),
    path('api/batch-delete/', views.api_batch_delete, name='batch_delete_legacy'),
]
