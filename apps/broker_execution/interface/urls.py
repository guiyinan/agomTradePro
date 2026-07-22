"""Classic Web routes for broker execution."""

from django.urls import path

from .views import (
    audit_view,
    connection_view,
    order_detail_view,
    orders_view,
    overview_view,
    reconciliation_view,
    settings_view,
)

app_name = "broker_execution"

urlpatterns = [
    path("", overview_view, name="overview"),
    path("orders/", orders_view, name="orders"),
    path("orders/<uuid:client_order_id>/", order_detail_view, name="order-detail"),
    path("reconciliation/", reconciliation_view, name="reconciliation"),
    path("connection/", connection_view, name="connection"),
    path("settings/", settings_view, name="settings"),
    path("audit/", audit_view, name="audit"),
]
