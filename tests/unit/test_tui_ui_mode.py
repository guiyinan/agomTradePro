from pathlib import Path

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


def test_base_template_outputs_classic_ui_mode():
    request = _anonymous_request("/account/login/")

    html = render_to_string("base.html", request=request)

    assert 'data-ui-mode="classic"' in html
    assert "data-ui-mode-toggle" in html
    assert "data-ui-mode-panel" in html
    assert 'data-ui-mode-choice="tui"' in html
    assert "data-ui-mode-exit" in html
    assert "data-tui-scan-toggle" in html
    assert "data-tui-manual-scan" in html
    assert "css/tui-theme.css" in html
    assert "js/tui-mode.js" in html
    assert "tui-scan-target" in html


def test_base_template_outputs_tui_ui_mode_from_cookie():
    request = _anonymous_request("/account/login/", "agom_ui_mode=tui")

    html = render_to_string("base.html", request=request)

    assert 'data-ui-mode="tui"' in html
    assert 'aria-pressed="true"' in html


def test_auth_template_outputs_tui_controls():
    request = _anonymous_request("/account/login/", "agom_ui_mode=tui")

    html = render_to_string("base_auth.html", request=request)

    assert 'data-ui-mode="tui"' in html
    assert "ui-mode-toggle--auth" in html
    assert "data-ui-mode-panel-toggle" in html
    assert "data-ui-mode-reset" in html
    assert "data-ui-mode-exit" in html
    assert "tui-function-bar" in html
    assert "tui-scan-target" in html


def test_tui_mode_script_exposes_control_interface_hooks():
    script = Path("static/js/tui-mode.js").read_text(encoding="utf-8")

    assert "agom:tui-scan-enabled" in script
    assert "data-ui-mode-panel-toggle" in script
    assert "data-ui-mode-exit" in script
    assert "data-tui-manual-scan" in script
    assert "exitTuiMode" in script
    assert "setScanEnabled" in script
