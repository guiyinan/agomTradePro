"""Authentication and rendering contracts for Terminal page views."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from core.ui_modes import UI_MODE_COOKIE, UI_MODE_COOKIE_MAX_AGE


@pytest.fixture
def regular_user(db):
    return get_user_model().objects.create_user(
        username="terminal-page-user",
        password="testpass123",
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="terminal-page-staff",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def superuser_without_staff(db):
    return get_user_model().objects.create_user(
        username="terminal-page-superuser",
        password="testpass123",
        is_staff=False,
        is_superuser=True,
    )


@pytest.mark.parametrize(
    "path",
    ["/terminal/", "/terminal/config/", "/tui/"],
)
def test_terminal_pages_redirect_anonymous_users_to_login(client, path) -> None:
    response = client.get(path)

    assert response.status_code == 302
    assert response.url.startswith("/account/login/")


def test_regular_user_can_open_terminal_and_tui_but_not_config(
    client,
    regular_user,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.terminal.interface.views.get_terminal_page_context",
        lambda: {"page_title": "Terminal", "provider_selector_bootstrap": {}},
    )
    client.force_login(regular_user)

    terminal_response = client.get("/terminal/")
    config_response = client.get("/terminal/config/")
    tui_response = client.get("/tui/")

    assert terminal_response.status_code == 200
    assert config_response.status_code == 403
    assert tui_response.status_code == 200
    assert tui_response.cookies[UI_MODE_COOKIE].value == "tui"
    assert tui_response.cookies[UI_MODE_COOKIE]["max-age"] == UI_MODE_COOKIE_MAX_AGE
    assert tui_response.cookies[UI_MODE_COOKIE]["samesite"] == "Lax"


@pytest.mark.parametrize("user_fixture", ["staff_user", "superuser_without_staff"])
def test_staff_or_superuser_can_open_terminal_config(
    client,
    request,
    user_fixture,
) -> None:
    client.force_login(request.getfixturevalue(user_fixture))

    response = client.get("/terminal/config/")

    assert response.status_code == 302
    assert response.url == "/tui/?screen=ai-ops.terminal&action=terminal.agent_chat"
