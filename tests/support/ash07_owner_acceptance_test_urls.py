"""Minimal real API and TUI surface for isolated ASH-07 Owner acceptance tests."""

from __future__ import annotations

from django.urls import include, path

from apps.terminal.interface.api_views import TuiWorkbenchActionRunView
from tests.support.ash07_owner_source_test_urls import csrf_bootstrap

urlpatterns = [
    path("csrf/bootstrap/", csrf_bootstrap, name="test-csrf-bootstrap"),
    path(
        "api/account/",
        include(
            ("apps.account.interface.api_urls", "account_api"),
            namespace="api_account",
        ),
    ),
    path(
        "api/simulated-trading/",
        include(
            ("apps.simulated_trading.interface.api_urls", "simulated_trading_api"),
            namespace="api_simulated_trading",
        ),
    ),
    path(
        "api/data-center/",
        include(
            ("apps.data_center.interface.api_urls", "api_data_center"),
            namespace="api_data_center",
        ),
    ),
    path(
        "api/tui/actions/<path:action_key>/run/",
        TuiWorkbenchActionRunView.as_view(),
        name="tui-action-run",
    ),
]
