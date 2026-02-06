"""
Views package for Macro app.

This package contains all view functions organized by functionality.
"""

from .page_views import (
    macro_data_view,
    datasource_config_view,
    data_controller_view,
    datasource_create_view,
    datasource_edit_view,
)
from .fetch_api import (
    api_fetch_data_stream,
    api_get_supported_indicators,
    api_fetch_data,
    api_get_due_indicators,
    api_sync_due_indicators,
    api_quick_sync,
)
from .table_api import (
    api_get_indicator_data,
    api_table_data,
    api_delete_record,
    api_batch_delete,
    api_create_record,
    api_update_record,
)
from .config_api import api_delete_data

__all__ = [
    # Page views
    'macro_data_view',
    'datasource_config_view',
    'data_controller_view',
    'datasource_create_view',
    'datasource_edit_view',
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
