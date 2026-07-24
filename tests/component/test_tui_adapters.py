from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.http import JsonResponse
from django.test import override_settings
from django.urls import path

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
def test_tui_internal_action_executor_forwards_session():
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
