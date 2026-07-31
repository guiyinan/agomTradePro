from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.http import JsonResponse
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


urlpatterns = [
    path("test-session/", session_echo_view),
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
        def acquire(self, *, blocking):
            assert blocking is False
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
