"""Request-boundary rejection and backend routing, without claiming credential proof."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

import apps.account.creation_authentication_composition as composition
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.interface.authentication import (
    MultiTokenAuthentication,
    TerminalInternalAuthentication,
)
from core.exceptions import AuthenticationError


def test_missing_backend_cannot_enter_creation_transaction():
    request = Request(APIRequestFactory().post("/create/", {}, format="json"))
    with pytest.raises(AuthenticationError):
        composition.authenticated_account_creation_transaction(request=request, using="default")


def test_test_framework_force_authentication_is_not_a_real_credential():
    raw = APIRequestFactory().post("/create/", {}, format="json")
    force_authenticate(raw, user=SimpleNamespace(pk=1, is_authenticated=True))
    request = Request(raw)
    with pytest.raises(AuthenticationError):
        composition.authenticated_account_creation_transaction(request=request, using="default")


@pytest.mark.parametrize(
    ("backend", "mode"),
    [
        (SessionAuthentication, "session"),
        (MultiTokenAuthentication, "token"),
        (TerminalInternalAuthentication, "internal"),
    ],
)
def test_only_selected_backend_and_explicit_alias_reach_infrastructure(backend, mode, monkeypatch):
    user, token, session = object(), object(), object()
    raw = APIRequestFactory().post("/create/", {"actor_id": "untrusted"}, format="json")
    raw.session = session
    request = Request(raw)
    request._authenticator = backend()
    request._user, request._auth = user, token
    calls = []
    monkeypatch.setattr(backend, "authenticate", lambda self, incoming: (user, token))

    @contextmanager
    def transaction(**kwargs):
        calls.append(kwargs)
        assert kwargs["reauthenticate"]() == (user, token)
        yield CanonicalAccountCreationRequester(actor_id="django-user:2", user_id=2)

    monkeypatch.setattr(composition, "authenticated_creation_transaction", transaction)
    with composition.authenticated_account_creation_transaction(
        request=request, using="chosen"
    ) as requester:
        assert requester.user_id == 2
    assert len(calls) == 1
    assert calls[0]["mode"] == mode
    assert calls[0]["using"] == "chosen"
    assert calls[0]["authenticated_user"] is user
    assert calls[0]["session"] is session
    assert calls[0]["token"] is token
