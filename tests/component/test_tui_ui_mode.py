from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory

from core.context_processors import get_ui_mode


def _anonymous_request(path: str = "/", cookie: str = ""):
    request = RequestFactory().get(path, HTTP_COOKIE=cookie)
    request.user = AnonymousUser()
    return request


def test_get_ui_mode_defaults_to_classic():
    request = RequestFactory().get("/")

    assert get_ui_mode(request) == {"ui_mode": "classic", "is_tui_mode": False}


def test_get_ui_mode_accepts_tui_cookie():
    request = RequestFactory().get("/", HTTP_COOKIE="agom_ui_mode=tui")

    assert get_ui_mode(request) == {"ui_mode": "tui", "is_tui_mode": True}


def test_get_ui_mode_rejects_invalid_cookie():
    request = RequestFactory().get("/", HTTP_COOKIE="agom_ui_mode=unknown")

    assert get_ui_mode(request) == {"ui_mode": "classic", "is_tui_mode": False}


def test_base_template_does_not_load_tui_overlay():
    request = _anonymous_request("/account/login/")

    html = render_to_string("base.html", request=request)

    assert "data-ui-mode-toggle" not in html
    assert "data-ui-mode-panel" not in html
    assert "css/tui-theme.css" not in html
    assert "js/tui-mode.js" not in html
    assert "tui-workbench-shell" not in html
    assert "tui-module-rail" not in html
    assert "tui-workspace-panel" not in html


def test_base_template_ignores_legacy_tui_cookie():
    request = _anonymous_request("/account/login/", "agom_ui_mode=tui")

    html = render_to_string("base.html", request=request)

    assert 'data-ui-mode="tui"' not in html
    assert "data-ui-mode-toggle" not in html


def test_auth_template_does_not_load_tui_overlay():
    request = _anonymous_request("/account/login/", "agom_ui_mode=tui")

    html = render_to_string("base_auth.html", request=request)

    assert "css/tui-theme.css" not in html
    assert "js/tui-mode.js" not in html
    assert "ui-mode-toggle--auth" not in html
    assert "data-ui-mode-panel-toggle" not in html
    assert "tui-function-bar" not in html
    assert "tui-scan-target" not in html
