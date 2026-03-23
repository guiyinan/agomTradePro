"""
Views module for Macro app.

This module bridges the views package for URL configuration compatibility.
All actual view implementations are organized in the views/ subdirectory.
"""

from .views import (
    api_batch_delete,
    api_create_record,
    # Config API
    api_delete_data,
    api_delete_record,
    api_fetch_data,
    # Fetch API
    api_fetch_data_stream,
    api_get_due_indicators,
    # Table API
    api_get_indicator_data,
    api_get_supported_indicators,
    api_quick_sync,
    api_sync_due_indicators,
    api_table_data,
    api_update_record,
    data_controller_view,
    datasource_config_view,
    datasource_create_view,
    datasource_edit_view,
    # Page views
    macro_data_view,
)

__all__ = [
    # Page views
    'macro_data_view',
    'datasource_config_view',
    'datasource_create_view',
    'datasource_edit_view',
    'data_controller_view',
    # Fetch API
    'api_fetch_data_stream',
    'api_get_supported_indicators',
    'api_fetch_data',
    'api_get_due_indicators',
    'api_sync_due_indicators',
    'api_quick_sync',
    # Table API
    'api_get_indicator_data',
    'api_table_data',
    'api_delete_record',
    'api_batch_delete',
    'api_create_record',
    'api_update_record',
    # Config API
    'api_delete_data',
]
