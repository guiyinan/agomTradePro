"""Canonical broker execution API routes."""

from django.urls import path

from .api_views import (
    AgentCommandCompleteView,
    AgentCommandsView,
    AgentEventsView,
    AgentHeartbeatView,
    AgentOrderLeaseView,
    AgentSnapshotView,
    AgentSubmittingView,
    BrokerExecutionAccountAccessView,
    BrokerExecutionAdvisorDraftView,
    BrokerExecutionAuditView,
    BrokerExecutionBindingView,
    BrokerExecutionConnectionSyncView,
    BrokerExecutionConnectionView,
    BrokerExecutionCredentialRevokeView,
    BrokerExecutionCredentialRotateView,
    BrokerExecutionKillSwitchView,
    BrokerExecutionOrderActionView,
    BrokerExecutionOrderDetailView,
    BrokerExecutionOrderListView,
    BrokerExecutionOverviewView,
    BrokerExecutionQmtOnboardingView,
    BrokerExecutionReconciliationResolveView,
    BrokerExecutionReconciliationView,
    BrokerExecutionSettingsView,
)

app_name = "broker_execution_api"

urlpatterns = [
    path("", BrokerExecutionOverviewView.as_view(), name="overview"),
    path("orders/", BrokerExecutionOrderListView.as_view(), name="orders"),
    path(
        "orders/from-advisor-sheet/",
        BrokerExecutionAdvisorDraftView.as_view(),
        name="advisor-order-drafts",
    ),
    path(
        "orders/<uuid:client_order_id>/",
        BrokerExecutionOrderDetailView.as_view(),
        name="order-detail",
    ),
    path(
        "orders/<uuid:client_order_id>/<str:action>/",
        BrokerExecutionOrderActionView.as_view(),
        name="order-action",
    ),
    path("kill-switch/", BrokerExecutionKillSwitchView.as_view(), name="kill-switch"),
    path("connections/", BrokerExecutionConnectionView.as_view(), name="connections"),
    path(
        "qmt-onboarding/",
        BrokerExecutionQmtOnboardingView.as_view(),
        name="qmt-onboarding",
    ),
    path(
        "connections/sync/",
        BrokerExecutionConnectionSyncView.as_view(),
        name="connection-sync",
    ),
    path("reconciliations/", BrokerExecutionReconciliationView.as_view(), name="reconciliations"),
    path(
        "reconciliations/<int:run_id>/resolve/",
        BrokerExecutionReconciliationResolveView.as_view(),
        name="resolve-reconciliation",
    ),
    path("audit/", BrokerExecutionAuditView.as_view(), name="audit"),
    path("bindings/", BrokerExecutionBindingView.as_view(), name="bindings"),
    path(
        "account-access/",
        BrokerExecutionAccountAccessView.as_view(),
        name="account-access",
    ),
    path(
        "credentials/rotate/",
        BrokerExecutionCredentialRotateView.as_view(),
        name="credential-rotate",
    ),
    path(
        "credentials/<uuid:credential_id>/revoke/",
        BrokerExecutionCredentialRevokeView.as_view(),
        name="credential-revoke",
    ),
    path("settings/<int:account_id>/", BrokerExecutionSettingsView.as_view(), name="settings"),
    path("agent/v1/heartbeat/", AgentHeartbeatView.as_view(), name="agent-heartbeat"),
    path("agent/v1/orders/lease/", AgentOrderLeaseView.as_view(), name="agent-order-lease"),
    path("agent/v1/orders/submitting/", AgentSubmittingView.as_view(), name="agent-submitting"),
    path("agent/v1/events/", AgentEventsView.as_view(), name="agent-events"),
    path("agent/v1/snapshots/", AgentSnapshotView.as_view(), name="agent-snapshots"),
    path("agent/v1/commands/lease/", AgentCommandsView.as_view(), name="agent-commands"),
    path(
        "agent/v1/commands/complete/",
        AgentCommandCompleteView.as_view(),
        name="agent-command-complete",
    ),
]
