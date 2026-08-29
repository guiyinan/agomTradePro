from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.http import JsonResponse
from django.template import engines
from django.template.response import SimpleTemplateResponse
from django.test import override_settings
from django.urls import path

import apps.terminal.infrastructure.tui_adapters as tui_adapters
from apps.terminal.application.tui_errors import TuiActionBusyError
from apps.terminal.infrastructure.tui_adapters import TuiInternalActionExecutor


def session_echo_view(request):
    return JsonResponse(
        {
            "has_session": hasattr(request, "session"),
            "flag": request.session.get("flag") if hasattr(request, "session") else None,
        }
    )


def unrendered_json_template_view(request):
    template = engines["django"].from_string('{"deleted": true}')
    return SimpleTemplateResponse(template, content_type="application/json")


urlpatterns = [
    path("test-session/", session_echo_view),
    path("test-unrendered-template/", unrendered_json_template_view),
]


@override_settings(ROOT_URLCONF=__name__)
def test_tui_internal_action_executor_forwards_session(monkeypatch):
    session = SessionStore()
    session["flag"] = "yes"

    payload = TuiInternalActionExecutor().execute(
        method="GET",
        endpoint="/test-session/",
        params={},
        body={},
        user=AnonymousUser(),
        session=session,
    )

    assert payload["status_code"] == 200
    assert payload["payload"] == {"has_session": True, "flag": "yes"}

    class SaturatedGate:
        def acquire(self, *, timeout):
            assert timeout > 0
            return False

        def release(self):
            raise AssertionError("A gate that was not acquired must not be released")

    monkeypatch.setattr(tui_adapters, "_TUI_ACTION_GATE", SaturatedGate())
    with pytest.raises(TuiActionBusyError):
        TuiInternalActionExecutor().execute(
            method="GET",
            endpoint="/test-session/",
            params={},
            body={},
            user=AnonymousUser(),
        )


@override_settings(ROOT_URLCONF=__name__)
def test_tui_internal_action_executor_renders_template_response() -> None:
    """Template-based endpoints must be rendered before content normalization."""

    payload = TuiInternalActionExecutor().execute(
        method="DELETE",
        endpoint="/test-unrendered-template/",
        params={},
        body={},
        user=AnonymousUser(),
    )

    assert payload == {
        "status_code": 200,
        "payload": {"deleted": True},
    }
