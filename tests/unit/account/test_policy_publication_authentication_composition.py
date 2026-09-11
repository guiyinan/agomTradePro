"""Request composition delegates credentials without manufacturing authentication."""

from contextlib import nullcontext

import pytest
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.account import policy_publication_authentication_composition as subject
from core.exceptions import AuthenticationError


def _request(authenticator):
    raw = APIRequestFactory().post("/policy/", {}, format="json")
    raw.session = object()
    request = Request(raw)
    request._authenticator = authenticator
    request._user = object()
    return request


@pytest.mark.parametrize(
    "candidate", [None, object(), _request(None), _request(TokenAuthentication())]
)
def test_unsupported_request_never_opens_transaction(monkeypatch, candidate):
    monkeypatch.setattr(
        subject,
        "authenticated_single_owner_policy_transaction",
        lambda **_: pytest.fail("unexpected transaction"),
    )
    with pytest.raises(AuthenticationError):
        subject.authenticated_policy_publication_transaction(
            request=candidate, using="test", settings=None, source=None
        )


def test_delegates_exact_inputs_and_repeats_backend(monkeypatch):
    authenticator = SessionAuthentication()
    request = _request(authenticator)
    calls = []

    def build(**kwargs):
        calls.append(kwargs)
        return nullcontext("trusted-requester")

    monkeypatch.setattr(subject, "authenticated_single_owner_policy_transaction", build)
    settings, source = object(), object()
    with subject.authenticated_policy_publication_transaction(
        request=request, using="test-alias", settings=settings, source=source
    ) as result:
        assert result == "trusted-requester"
    assert calls[0]["using"] == "test-alias"
    assert calls[0]["authenticated_user"] is request.user
    assert calls[0]["session"] is request._request.session
    assert calls[0]["settings"] is settings and calls[0]["source"] is source
    observed = []

    def authenticate(current):
        observed.append(current)
        return request.user, None

    monkeypatch.setattr(authenticator, "authenticate", authenticate)
    assert calls[0]["reauthenticate"]() == (request.user, None)
    assert observed == [request]
    monkeypatch.setattr(authenticator, "authenticate", lambda _: None)
    with pytest.raises(AuthenticationError):
        calls[0]["reauthenticate"]()
