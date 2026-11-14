"""Browser acceptance failures must not reveal session or continuation values."""

from types import SimpleNamespace

import pytest
from django.conf import settings
from django.http import HttpRequest
from django.middleware.csrf import get_token

from tests.component.simulated_trading import (
    test_corporate_action_owner_workflow_tui_browser as browser_journey,
)
from tests.component.simulated_trading.test_corporate_action_owner_workflow_tui_browser import (
    _continuation_token,
    _ordinary_owner_browser,
    _response_payload,
)

_OPAQUE = "synthetic-secret-must-not-be-rendered-in-failure"


def test_real_masked_csrf_token_matches_the_original_cookie_without_literal_equality(monkeypatch):
    request = HttpRequest()
    masked = get_token(request)
    secret = request.META["CSRF_COOKIE"]
    assert masked != secret
    cookies = {
        settings.SESSION_COOKIE_NAME: SimpleNamespace(value=_OPAQUE),
        settings.CSRF_COOKIE_NAME: SimpleNamespace(value=secret),
    }
    world = SimpleNamespace(
        owner=SimpleNamespace(client=SimpleNamespace(cookies=cookies), csrf_token=masked)
    )

    class BrowserReached(RuntimeError):
        pass

    def reached():
        raise BrowserReached("validated cookie binding reached the browser")

    monkeypatch.setattr(browser_journey, "sync_playwright", reached)
    with pytest.raises(BrowserReached):
        with _ordinary_owner_browser(world, live_server=SimpleNamespace(url="http://127.0.0.1")):
            pytest.fail("browser sentinel was bypassed")


@pytest.mark.parametrize("defect", ("target", "extra_input"))
def test_malformed_continuation_diagnostics_never_include_the_sealed_value(defect):
    inputs = {"account_id": 17, "workflow_token": _OPAQUE}
    if defect == "extra_input":
        inputs["extra"] = "unexpected"
    payload = {
        "continuation": {
            "action_key": "wrong" if defect == "target" else "expected",
            "input": inputs,
        }
    }
    with pytest.raises(AssertionError) as failure:
        _continuation_token(payload, expected_action="expected", token_field="workflow_token")
    assert _OPAQUE not in str(failure.value)


def test_non_object_response_diagnostics_never_include_its_body():
    response = SimpleNamespace(
        status=200,
        headers={"content-type": "application/json"},
        json=lambda: _OPAQUE,
    )
    with pytest.raises(AssertionError) as failure:
        _response_payload(response)
    assert _OPAQUE not in str(failure.value)


def test_mismatched_browser_csrf_diagnostics_never_include_cookie_values():
    cookies = {
        settings.SESSION_COOKIE_NAME: SimpleNamespace(value=_OPAQUE),
        settings.CSRF_COOKIE_NAME: SimpleNamespace(value=_OPAQUE),
    }
    world = SimpleNamespace(
        owner=SimpleNamespace(client=SimpleNamespace(cookies=cookies), csrf_token="different")
    )
    with pytest.raises(AssertionError) as failure:
        with _ordinary_owner_browser(world, live_server=SimpleNamespace(url="http://127.0.0.1")):
            pytest.fail("mismatched browser cookies reached Playwright")
    assert _OPAQUE not in str(failure.value)
