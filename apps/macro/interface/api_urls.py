"""Macro API URL configuration."""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from . import views

app_name = "macro_api"


class MacroApiRootView(APIView):
    """Return discoverable macro API endpoints."""

    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "supported_indicators": "/api/macro/supported-indicators/",
                    "fetch_stream": "/api/macro/fetch/stream/",
                    "fetch": "/api/macro/fetch/",
                    "delete": "/api/macro/delete/",
                    "due_indicators": "/api/macro/due-indicators/",
                    "sync_due": "/api/macro/sync-due/",
                    "indicator_data": "/api/macro/indicator-data/",
                    "quick_sync": "/api/macro/quick-sync/",
                    "table": "/api/macro/table/",
                    "datasources": "/api/macro/datasources/",
                    "datasource_detail": "/api/macro/datasources/{source_id}/",
                    "datasource_test": "/api/macro/datasources/{source_id}/test/",
                    "record_create": "/api/macro/record/create/",
                    "record_detail": "/api/macro/record/{record_id}/",
                    "record_update": "/api/macro/record/{record_id}/update/",
                    "batch_delete": "/api/macro/batch-delete/",
                }
            }
        )

urlpatterns = [
    path("", MacroApiRootView.as_view(), name="api-root"),
    path("supported-indicators/", views.api_get_supported_indicators, name="get_supported_indicators"),
    path("fetch/stream/", views.api_fetch_data_stream, name="fetch_data_stream"),
    path("fetch/", views.api_fetch_data, name="fetch_data"),
    path("delete/", views.api_delete_data, name="delete_data"),
    path("due-indicators/", views.api_get_due_indicators, name="get_due_indicators"),
    path("sync-due/", views.api_sync_due_indicators, name="sync_due_indicators"),
    path("indicator-data/", views.api_get_indicator_data, name="get_indicator_data"),
    path("quick-sync/", views.api_quick_sync, name="quick_sync"),
    path("datasources/", views.api_datasource_list_create, name="datasource_list_create"),
    path("datasources/<int:source_id>/", views.api_datasource_detail, name="datasource_detail"),
    path("datasources/<int:source_id>/test/", views.api_datasource_test_connection, name="datasource_test_connection"),
    path("table/", views.api_table_data, name="table_data"),
    path("record/<int:record_id>/", views.api_delete_record, name="delete_record"),
    path("record/create/", views.api_create_record, name="create_record"),
    path("record/<int:record_id>/update/", views.api_update_record, name="update_record"),
    path("batch-delete/", views.api_batch_delete, name="batch_delete"),
]
