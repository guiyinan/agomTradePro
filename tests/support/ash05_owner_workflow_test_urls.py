"""Actual owner APIs and product TUI routes for the isolated ASH05 journey."""

from django.urls import path

from apps.terminal.interface.api_views import (
    TuiOperatorGovernanceQueueView,
    TuiOperatorHomeSectionView,
    TuiOperatorHomeView,
    TuiWorkbenchActionRunView,
    TuiWorkbenchApiRootView,
    TuiWorkbenchBootstrapView,
    TuiWorkbenchCatalogView,
    TuiWorkbenchModuleSnapshotView,
    TuiWorkbenchRegistryView,
    TuiWorkbenchScreenView,
)
from apps.terminal.interface.views import tui_workbench_view
from tests.support.ash07_owner_source_test_urls import urlpatterns as owner_source_routes

# Use actual product views without loading unrelated apps outside this test's
# explicitly restricted migrated application set.
urlpatterns = [
    *owner_source_routes,
    path("tui/", tui_workbench_view, name="tui-workbench"),
    path("api/tui/", TuiWorkbenchApiRootView.as_view(), name="api-tui-root"),
    path("api/tui/catalog/", TuiWorkbenchCatalogView.as_view(), name="api-tui-catalog"),
    path("api/tui/bootstrap/", TuiWorkbenchBootstrapView.as_view(), name="api-tui-bootstrap"),
    path("api/tui/operator/home/", TuiOperatorHomeView.as_view(), name="api-tui-operator-home"),
    path(
        "api/tui/operator/home/<str:section_key>/",
        TuiOperatorHomeSectionView.as_view(),
        name="api-tui-operator-home-section",
    ),
    path(
        "api/tui/operator/governance-queue/",
        TuiOperatorGovernanceQueueView.as_view(),
        name="api-tui-operator-governance-queue",
    ),
    path(
        "api/tui/screens/<str:screen_key>/", TuiWorkbenchScreenView.as_view(), name="api-tui-screen"
    ),
    path(
        "api/tui/actions/<str:action_key>/run/",
        TuiWorkbenchActionRunView.as_view(),
        name="api-tui-action-run",
    ),
    path("api/tui/registry/", TuiWorkbenchRegistryView.as_view(), name="api-tui-registry"),
    path(
        "api/tui/modules/<str:module_key>/snapshot/",
        TuiWorkbenchModuleSnapshotView.as_view(),
        name="api-tui-module-snapshot",
    ),
]
