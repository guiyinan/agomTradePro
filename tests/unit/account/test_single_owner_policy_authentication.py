"""Eligibility checks supplement, never replace, the real credential transaction."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from apps.account.application.owner_policy_authorization_source import (
    decode_owner_policy_authorization_source,
)
from apps.account.application.single_owner_policy_publication_settings import (
    decode_single_owner_policy_publication_settings,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.infrastructure import single_owner_policy_authentication as subject
from core.exceptions import AuthenticationError
from tests.unit.core.test_owner_policy_authorization_source_runtime import _fixture


def _setup(monkeypatch):
    package, payload = _fixture()
    source = decode_owner_policy_authorization_source(package)
    settings = decode_single_owner_policy_publication_settings(payload)
    user = SimpleNamespace(
        pk=42,
        username="designated-owner",
        is_active=True,
        is_staff=True,
        is_superuser=False,
        is_authenticated=True,
        refresh_from_db=lambda **_: None,
    )
    profile = SimpleNamespace(user_id=42, rbac_role="admin", refresh_from_db=lambda **_: None)
    calls = []

    class Manager:
        def __init__(self, value):
            self.value = value

        def using(self, alias):
            assert alias == "test-alias"
            return self

        def select_for_update(self):
            return self

        def get(self, **kwargs):
            assert list(kwargs.values()) == [42]
            return self.value

    @contextmanager
    def credentials(**kwargs):
        calls.append(kwargs)
        yield CanonicalAccountCreationRequester(actor_id="django-user:42", user_id=42)
        calls.append("credential recheck")

    monkeypatch.setattr(subject, "authenticated_creation_transaction", credentials)
    monkeypatch.setattr(subject, "User", SimpleNamespace(objects=Manager(user)))
    monkeypatch.setattr(subject, "AccountProfileModel", SimpleNamespace(objects=Manager(profile)))
    options = {
        "using": "test-alias",
        "authenticated_user": object(),
        "session": object(),
        "reauthenticate": lambda: (None, None),
        "settings": settings,
        "source": source,
    }
    return options, user, profile, calls


def test_eligible_declared_owner_keeps_session_transaction_through_exit(monkeypatch):
    options, _, _, calls = _setup(monkeypatch)
    with subject.authenticated_single_owner_policy_transaction(**options) as requester:
        assert requester.user_id == 42
        assert len(calls) == 1
        assert calls[0]["mode"] == "session"
        assert calls[0]["token"] is None
        assert calls[0]["reauthenticate"] is options["reauthenticate"]
    assert calls[-1] == "credential recheck"


@pytest.mark.parametrize(
    "field,value", [("username", "another"), ("pk", 43), ("is_staff", False), ("is_active", False)]
)
def test_ineligible_user_never_reaches_publication(monkeypatch, field, value):
    options, user, _, _ = _setup(monkeypatch)
    setattr(user, field, value)
    with pytest.raises(AuthenticationError):
        with subject.authenticated_single_owner_policy_transaction(**options):
            pytest.fail("ineligible owner reached publication")


def test_role_loss_before_exit_rejects_publication(monkeypatch):
    options, _, profile, _ = _setup(monkeypatch)
    with pytest.raises(AuthenticationError):
        with subject.authenticated_single_owner_policy_transaction(**options):
            profile.rbac_role = "user"


def test_source_settings_mismatch_never_reaches_credentials(monkeypatch):
    options, _, _, calls = _setup(monkeypatch)
    payload = options["settings"].to_payload()
    payload["authorization_source_version"] = "another-version"
    options["settings"] = decode_single_owner_policy_publication_settings(payload)
    with pytest.raises(AuthenticationError):
        with subject.authenticated_single_owner_policy_transaction(**options):
            pytest.fail("mismatched source reached publication")
    assert calls == []


def test_future_declaration_cannot_authorize_current_publication(monkeypatch):
    options, _, _, _ = _setup(monkeypatch)
    package, payload = _fixture("9999-01-01T00:00:00+00:00")
    options["source"] = decode_owner_policy_authorization_source(package)
    options["settings"] = decode_single_owner_policy_publication_settings(payload)
    with pytest.raises(AuthenticationError):
        with subject.authenticated_single_owner_policy_transaction(**options):
            pytest.fail("future declaration reached publication")


def test_credential_failure_cannot_be_replaced_by_declaration(monkeypatch):
    options, _, _, _ = _setup(monkeypatch)

    @contextmanager
    def revoked(**_):
        raise AuthenticationError("Session revoked")
        yield  # pragma: no cover - makes the failing boundary a context manager

    monkeypatch.setattr(subject, "authenticated_creation_transaction", revoked)
    with pytest.raises(AuthenticationError, match="Session revoked"):
        with subject.authenticated_single_owner_policy_transaction(**options):
            pytest.fail("declaration bypassed failed credentials")
