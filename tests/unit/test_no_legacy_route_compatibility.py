from django.conf import settings
from django.test import Client


def test_deprecation_middleware_is_not_installed() -> None:
    assert "core.middleware.DeprecationHeaderMiddleware" not in settings.MIDDLEWARE


def test_removed_reported_legacy_routes_now_return_404() -> None:
    client = Client()

    removed_paths = [
        "/events/",
        "/market-data/",
        "/alpha-trigger/",
        "/alpha-trigger/create/",
        "/alpha-trigger/performance/",
        "/beta-gate/",
        "/beta-gate/test-asset/",
        "/audit/attribution/",
        "/rotation/account-config/",
        "/decision-rhythm/quota/config/",
        "/fund/analysis/",
        "/fund/compare/",
        "/equity/analysis/",
        "/equity/screener/",
        "/sector/heatmap/",
        "/api" + "/macro/data/",
        "/simulated_trading/my-accounts/",
        "/ai/manage/",
        "/sector/dashboard/",
        "/events/publish/",
        "/events/query/",
        "/events/metrics/",
        "/events/status/",
        "/events/replay/",
        "/policy/manage/",
        "/policy/events/2026-03-31/",
        "/policy/audit/queue/",
        "/policy/rss/manage/",
        "/policy/rss/manage/new/",
        "/policy/rss/manage/1/edit/",
        "/signal/list/",
        "/signal/list/validate/",
        "/backtest/list/",
        "/backtest/reports/",
        "/api/alpha/stocks/",
        "/api/policy/level/",
        "/api/policy/api/rss/sources/",
        "/api/policy/api/rss/logs/",
        "/api/policy/api/rss/keywords/",
        "/api" + "/macro/indicators/",
        "/api/portfolio/",
        "/api/signals/",
    ]

    for path in removed_paths:
        response = client.get(path, follow=False)
        assert response.status_code == 404, path
