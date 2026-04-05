"""
Views package for Macro app.

This package contains all view functions organized by functionality.
"""

from .config_api import (
    api_datasource_detail,
    api_datasource_list_create,
    api_datasource_test_connection,
    api_delete_data,
)
from .fetch_api import (
    api_fetch_data,
    api_fetch_data_stream,
    api_get_due_indicators,
    api_get_supported_indicators,
    api_quick_sync,
    api_sync_due_indicators,
)
from .page_views import (
    data_controller_view,
    datasource_config_view,
    datasource_create_view,
    datasource_edit_view,
    macro_data_view,
)
from .table_api import (
    api_batch_delete,
    api_create_record,
    api_delete_record,
    api_get_indicator_data,
    api_table_data,
    api_update_record,
)

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
    'api_datasource_list_create',
    'api_datasource_detail',
    'api_datasource_test_connection',
]
