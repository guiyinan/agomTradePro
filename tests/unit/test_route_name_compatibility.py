from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import resolve, reverse


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
    assert reverse("fund:multidim_screen_page")
    assert reverse("prompt:home") == "/prompt/"
    assert reverse("account:home") == "/account/"


def test_policy_workbench_and_rss_page_routes_resolvable():
    assert reverse("policy:workbench") == "/policy/workbench/"
    assert reverse("policy:rss-manage") == "/policy/rss/sources/"
    assert reverse("policy:rss-source-create") == "/policy/rss/sources/new/"
    assert reverse("policy:rss-reader") == "/policy/rss/reader/"
    assert reverse("policy:rss-keywords") == "/policy/rss/keywords/"
    assert reverse("policy:rss-logs") == "/policy/rss/logs/"

    assert resolve("/policy/workbench/").view_name.endswith("workbench")
    assert resolve("/policy/rss/sources/").view_name.endswith("rss-manage")
    assert resolve("/policy/rss/manage/").view_name.endswith("rss-manage-legacy")


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


def test_macro_legacy_and_new_api_routes_resolvable():
    assert reverse("api_macro:quick_sync")
    assert reverse("api_macro:get_indicator_data")

    assert resolve("/api/macro/quick-sync/").view_name.endswith("quick_sync")
    assert resolve("/api/macro/indicator-data/").view_name.endswith("get_indicator_data")


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
    assert '{% url "api_macro:quick_sync" %}' in regime_dashboard

    assert "/macro/api/indicator-data/" not in macro_data
    assert '{% url "api_macro:get_indicator_data" %}' in macro_data

    assert "const API_BASE = '/macro/api';" not in macro_controller
    assert '{% url "api_macro:get_supported_indicators" %}' in macro_controller


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


def test_legacy_compatibility_routes_resolvable():
    assert resolve("/signal/list/").view_name.endswith("list_legacy")
    assert resolve("/signal/list/validate/").view_name.endswith("list_validate_legacy")
    assert resolve("/backtest/list/").view_name.endswith("list-legacy")
    assert resolve("/backtest/reports/").view_name.endswith("reports-legacy")
    assert resolve("/simulated_trading/my-accounts/").view_name.endswith("simulated-trading-legacy-my-accounts")
    assert resolve("/ai/manage/").view_name.endswith("ai-manage-legacy")
    assert resolve("/sector/dashboard/").view_name.endswith("sector-dashboard-legacy")
    assert resolve("/api/simulated-trading/accounts/").view_name.endswith("account-list")


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
