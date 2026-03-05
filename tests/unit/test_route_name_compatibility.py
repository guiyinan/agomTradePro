from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse


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


def test_dashboard_page_does_not_raise_reverse_error(db):
    user = get_user_model().objects.create_user(username="route_test_user", password="x")
    client = Client()
    client.force_login(user)

    response = client.get("/dashboard/")
    assert response.status_code in (200, 302)

