"""Authenticated empty-state contracts for high-value user-facing pages."""

import pytest
from django.test import Client

CORE_USER_PAGES = [
    "/account/profile/",
    "/account/settings/",
    "/account/mcp/",
    "/account/collaboration/",
    "/account/observer/",
    "/account/admin/users/",
    "/account/admin/tokens/",
    "/account/admin/settings/",
    "/alpha/ops/inference/",
    "/alpha/ops/qlib-data/",
    "/alpha-triggers/",
    "/alpha-triggers/create/",
    "/alpha-triggers/invalidation-builder/",
    "/alpha-triggers/performance/",
    "/audit/page/",
    "/audit/reports/",
    "/audit/indicator-performance/",
    "/audit/threshold-validation/",
    "/audit/review/",
    "/audit/manual-trades/",
    "/audit/operation-logs/",
    "/audit/my-logs/",
    "/audit/decision-traces/",
    "/audit/my-decision-traces/",
    "/backtest/",
    "/backtest/create/",
    "/beta-gate/config/",
    "/beta-gate/config/new/",
    "/beta-gate/test/",
    "/beta-gate/version/",
    "/decision-rhythm/quota/",
    "/decision-rhythm/config/",
    "/macro/data/",
    "/macro/controller/",
    "/policy/workbench/",
    "/policy/events/",
    "/policy/events/new/",
    "/policy/rss/sources/",
    "/policy/rss/sources/new/",
    "/policy/rss/reader/",
    "/policy/rss/keywords/",
    "/policy/rss/keywords/new/",
    "/policy/rss/logs/",
    "/regime/dashboard/",
    "/signal/manage/",
    "/signal/create/",
    "/simulated-trading/dashboard/",
    "/simulated-trading/my-accounts/",
    "/strategy/",
    "/strategy/create/",
    "/fund/dashboard/",
    "/sentiment/dashboard/",
    "/sentiment/analyze/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("path", CORE_USER_PAGES)
def test_admin_can_render_core_user_page_empty_states(
    admin_client: Client,
    path: str,
) -> None:
    """Every critical page must render usable HTML for an authorized empty account."""

    response = admin_client.get(path, follow=True)

    assert response.status_code == 200, path
    assert response.headers["Content-Type"].startswith("text/html"), path
    body = response.content.lower()
    assert b"<h1>server error" not in body, path
    assert b"technical 500 response" not in body, path
    assert len(body) > 200, path
