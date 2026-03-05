from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import resolve, reverse
from pathlib import Path


def test_dashboard_legacy_api_route_names_resolvable():
    names = [
        "dashboard:api_positions_list",
        "dashboard:api_allocation",
        "dashboard:api_performance",
        "dashboard:api_v1_summary",
        "dashboard:api_v1_regime_quadrant",
        "dashboard:api_v1_equity_curve",
        "dashboard:api_v1_signal_status",
        "dashboard:api_alpha_stocks",
        "dashboard:api_alpha_provider_status",
        "dashboard:api_alpha_coverage",
        "dashboard:api_alpha_ic_trends",
        "dashboard:api_workflow_refresh_candidates",
    ]
    for name in names:
        assert reverse(name)

    assert reverse("dashboard:api_position_detail", args=["000001.SZ"])


def test_equity_fund_page_route_names_resolvable():
    assert reverse("equity:screen")
    assert reverse("equity:pool")
    assert reverse("equity:detail", args=["000001.SZ"])
    assert reverse("fund:dashboard")
    assert reverse("fund:multidim_screen_page")


def test_policy_workbench_and_rss_page_routes_resolvable():
    assert reverse("policy:workbench") == "/policy/workbench/"
    assert reverse("policy:rss-manage") == "/policy/rss/manage/"
    assert reverse("policy:rss-source-create") == "/policy/rss/manage/new/"
    assert reverse("policy:rss-reader") == "/policy/rss/reader/"
    assert reverse("policy:rss-keywords") == "/policy/rss/keywords/"
    assert reverse("policy:rss-logs") == "/policy/rss/logs/"

    assert resolve("/policy/workbench/").view_name.endswith("workbench")
    assert resolve("/policy/rss/manage/").view_name.endswith("rss-manage")


def test_macro_legacy_and_new_api_routes_resolvable():
    assert reverse("api_macro:quick_sync")
    assert reverse("api_macro:get_indicator_data")

    assert resolve("/macro/api/quick-sync/").view_name.endswith("quick_sync_legacy")
    assert resolve("/macro/api/indicator-data/").view_name.endswith("get_indicator_data_legacy")


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
