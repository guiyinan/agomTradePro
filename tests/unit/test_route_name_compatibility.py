from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, resolve, reverse
import pytest
from rest_framework.views import APIView


def test_dashboard_legacy_api_route_names_resolvable():
    names = [
        "api_dashboard:positions_list",
        "api_dashboard:allocation",
        "api_dashboard:performance",
        "api_dashboard:v1_summary",
        "api_dashboard:v1_regime_quadrant",
        "api_dashboard:v1_equity_curve",
        "api_dashboard:v1_signal_status",
        "api_dashboard:alpha_stocks",
        "api_dashboard:alpha_provider_status",
        "api_dashboard:alpha_coverage",
        "api_dashboard:alpha_ic_trends",
        "api_dashboard:workflow_refresh_candidates",
    ]
    for name in names:
        assert reverse(name)

    assert reverse("api_dashboard:position_detail", args=["000001.SZ"])


def test_equity_fund_page_route_names_resolvable():
    assert reverse("equity:home") == "/equity/"
    assert reverse("equity:screen")
    assert reverse("equity:pool")
    assert reverse("equity:detail", args=["000001.SZ"])
    assert reverse("fund:home") == "/fund/"
    assert reverse("fund:dashboard")
    assert reverse("prompt:home") == "/prompt/"
    assert reverse("account:home") == "/account/"

    with pytest.raises(NoReverseMatch):
        reverse("fund:multidim_screen_page")


def test_policy_workbench_and_rss_page_routes_resolvable():
    assert reverse("policy:workbench") == "/policy/workbench/"
    assert reverse("policy:rss-manage") == "/policy/rss/sources/"
    assert reverse("policy:rss-source-create") == "/policy/rss/sources/new/"
    assert reverse("policy:rss-reader") == "/policy/rss/reader/"
    assert reverse("policy:rss-keywords") == "/policy/rss/keywords/"
    assert reverse("policy:rss-logs") == "/policy/rss/logs/"

    assert resolve("/policy/workbench/").view_name.endswith("workbench")
    assert resolve("/policy/rss/sources/").view_name.endswith("rss-manage")


def test_non_api_policy_status_and_audit_routes_are_removed():
    client = Client()

    for path in [
        "/policy/status/",
        "/policy/audit/review/1/",
        "/policy/audit/bulk_review/",
        "/policy/audit/auto_assign/",
    ]:
        response = client.get(path, follow=False)
        assert response.status_code == 404, path


def test_policy_and_account_root_redirects(db):
    user = get_user_model().objects.create_user(username="route_root_user", password="x")
    client = Client()
    client.force_login(user)

    policy_response = client.get("/policy/", follow=False)
    account_response = client.get("/api/account/", follow=False)

    assert policy_response.status_code in (301, 302)
    assert policy_response["Location"].endswith("/policy/workbench/")

    # /api/account/ now serves API root directly (200), no longer redirects
    assert account_response.status_code in (200, 301, 302)


def test_module_page_root_redirects():
    client = Client()

    cases = {
        "/account/": "/account/login/",
        "/equity/": "/equity/screen/",
        "/fund/": "/fund/dashboard/",
        "/prompt/": "/prompt/manage/",
    }

    for path, expected in cases.items():
        response = client.get(path, follow=False)
        assert response.status_code in (301, 302)
        assert response["Location"].endswith(expected)


def test_regime_dashboard_does_not_return_500(db):
    user = get_user_model().objects.create_user(username="regime_route_user", password="x")
    client = Client()
    client.force_login(user)

    response = client.get("/regime/dashboard/")
    assert response.status_code < 500


def test_data_center_macro_api_routes_resolvable():
    assert reverse("api_data_center:dc-macro-series") == "/api/data-center/macro/series/"
    assert reverse("api_data_center:dc-sync-macro") == "/api/data-center/sync/macro/"

    assert resolve("/api/data-center/macro/series/").view_name.endswith("dc-macro-series")
    assert resolve("/api/data-center/sync/macro/").view_name.endswith("dc-sync-macro")


def test_dashboard_page_does_not_raise_reverse_error(db):
    user = get_user_model().objects.create_user(username="route_test_user", password="x")
    client = Client()
    client.force_login(user)

    response = client.get("/dashboard/")
    assert response.status_code in (200, 302)


def test_macro_templates_do_not_hardcode_legacy_api_paths():
    template_dir = Path("core/templates")

    regime_dashboard = (template_dir / "regime/dashboard.html").read_text(encoding="utf-8")
    macro_data = (template_dir / "macro/data.html").read_text(encoding="utf-8")
    macro_controller = (template_dir / "macro/data_controller.html").read_text(encoding="utf-8")

    assert "/macro/api/quick-sync/" not in regime_dashboard
    assert '{% url "api_data_center:dc-sync-macro" %}' in regime_dashboard

    assert "/macro/api/indicator-data/" not in macro_data
    assert '{% url "api_data_center:dc-macro-series" %}' in macro_data
    assert '{% url "api_data_center:dc-sync-macro" %}' in macro_data
    assert 'id="refreshAllIndicatorsBtn"' in macro_data
    assert "function normalizeChronologicalSeries(data)" in macro_data
    assert "function normalizeMacroPayload(code, result)" in macro_data
    assert "const response = await fetch(`${macroSeriesUrl}?indicator_code=${encodeURIComponent(code)}&limit=500`);" in macro_data
    assert "currentIndicatorPayload = normalizeMacroPayload(code, result);" in macro_data

    assert "const API_BASE = '/macro/api';" not in macro_controller
    assert "const API_BASE = '/api/data-center';" in macro_controller


def test_regime_redesign_templates_reflect_closure():
    template_dir = Path("core/templates")

    dashboard_template = (template_dir / "dashboard/index.html").read_text(encoding="utf-8")
    base_template = (template_dir / "base.html").read_text(encoding="utf-8")
    regime_template = (template_dir / "regime/dashboard.html").read_text(encoding="utf-8")

    assert '<div class="nav-section-title">决策平面</div>' not in dashboard_template
    assert "{% url 'beta_gate:config' %}" not in dashboard_template
    assert "{% url 'alpha_trigger:list' %}" not in dashboard_template
    assert "{% url 'decision_rhythm:quota' %}" not in dashboard_template
    assert "决策引擎" not in base_template
    assert "navigatorHistoryChart" in regime_template
    assert '{% url "regime_api:regime-navigator-history" %}' in regime_template
    assert "onboardingOverlay" not in regime_template
    assert "regime_onboarding_done" not in regime_template


def test_removed_legacy_page_routes_return_404():
    client = Client()

    for path in [
        "/signal/list/",
        "/signal/list/validate/",
        "/backtest/list/",
        "/backtest/reports/",
        "/simulated_trading/my-accounts/",
        "/ai/manage/",
        "/sector/dashboard/",
        "/policy/rss/manage/",
    ]:
        response = client.get(path, follow=False)
        assert response.status_code == 404


def test_canonical_api_routes_still_resolve():
    assert resolve("/api/simulated-trading/accounts/").view_name.endswith("account-list")


def test_asset_pool_summary_page_redirects_to_asset_screen():
    client = Client()

    response = client.get("/asset-analysis/pool-summary/", follow=False)

    assert response.status_code == 302
    assert response["Location"] == "/asset-analysis/screen/"


def test_legacy_sector_page_aliases_redirect_to_rotation_assets():
    client = Client()

    for path in [
        "/sector/",
        "/sector/analysis/",
        "/sector/rotation/",
        "/sector/strength/",
        "/sector/flow/",
    ]:
        response = client.get(path, follow=False)
        assert response.status_code == 302, path
        assert response["Location"] == "/rotation/assets/"


def test_non_api_routes_do_not_resolve_to_drf_api_views():
    violations: list[str] = []

    def walk(patterns, prefix: str = "") -> None:
        for pattern in patterns:
            if isinstance(pattern, URLPattern):
                route = "/" + (prefix + str(pattern.pattern)).replace("//", "/")
                if route.startswith("/api/"):
                    continue
                callback = pattern.callback
                view_class = getattr(callback, "view_class", None)
                if view_class and issubclass(view_class, APIView):
                    violations.append(f"{route} -> {view_class.__module__}.{view_class.__name__}")
            elif isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))

    walk(get_resolver().url_patterns)
    assert violations == []


def test_reported_route_aliases_are_removed():
    client = Client()

    for path in [
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
        "/fund/compare/?regime=Recovery",
        "/equity/analysis/",
        "/equity/screener/",
        "/sector/heatmap/?top_n=5",
        "/api" + "/macro/data/?indicator_code=CPI",
    ]:
        response = client.get(path, follow=False)
        assert response.status_code == 404


def test_high_risk_business_pages_require_login():
    client = Client()

    for path in [
        "/ai/",
        "/ai/logs/",
        "/equity/screen/",
        "/equity/pool/",
        "/equity/valuation-repair/",
        "/equity/valuation-repair/config/",
        "/fund/dashboard/",
    ]:
        response = client.get(path, follow=False)
        assert response.status_code == 302
        assert "/account/login/" in response["Location"]
        assert "next=" in response["Location"]


def test_pulse_api_root_is_discoverable(db):
    user = get_user_model().objects.create_user(username="pulse_route_user", password="x")
    client = Client()
    client.force_login(user)

    response = client.get("/api/pulse/")

    assert response.status_code == 200
    assert response.json()["endpoints"]["current"] == "/api/pulse/current/"


def test_admin_problem_pages_do_not_return_500(db):
    admin = get_user_model().objects.create_superuser(
        username="route_admin",
        email="route_admin@example.com",
        password="x",
    )
    client = Client()
    client.force_login(admin)

    urls = [
        "/admin/regime/regimethresholdconfig/add/",
        "/admin/simulated_trading/simulatedaccountmodel/",
        "/admin/simulated_trading/simulatedaccountmodel/add/",
        "/admin/simulated_trading/positionmodel/add/",
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code < 500
