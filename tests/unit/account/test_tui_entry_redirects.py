import pytest
from django.contrib.auth.models import User


@pytest.mark.django_db
def test_root_redirects_to_tui_and_sets_cookie(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response["Location"] == "/tui/"
    assert response.cookies["agom_ui_mode"].value == "tui"


@pytest.mark.django_db
def test_login_defaults_to_tui_and_sets_cookie(client):
    User.objects.create_user(username="operator", password="test-pass-123")

    response = client.post(
        "/account/login/",
        {"username": "operator", "password": "test-pass-123"},
    )

    assert response.status_code == 302
    assert response["Location"] == "/tui/"
    assert response.cookies["agom_ui_mode"].value == "tui"


@pytest.mark.django_db
def test_login_next_dashboard_keeps_classic_entry_and_sets_cookie(client):
    User.objects.create_user(username="classic_user", password="test-pass-123")

    response = client.post(
        "/account/login/?next=/dashboard/",
        {"username": "classic_user", "password": "test-pass-123"},
    )

    assert response.status_code == 302
    assert response["Location"] == "/dashboard/"
    assert response.cookies["agom_ui_mode"].value == "classic"
