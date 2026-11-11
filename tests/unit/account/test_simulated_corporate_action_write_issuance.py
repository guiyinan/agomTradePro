"""Orchestration tests; real credential and PostgreSQL locks need native coverage."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.account import simulated_corporate_action_write_issuance_composition as issuance
from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantConflict,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    LockedSimulatedCorporateActionWriteScope,
    SimulatedCorporateActionGrantConsent,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.infrastructure import simulated_corporate_action_write_grant_seal as seals
from core.exceptions import AuthenticationError
from tests.unit.account.test_simulated_corporate_action_write_grant import _AT, _binding, _grant


@pytest.fixture
def issuer(monkeypatch: pytest.MonkeyPatch):
    """Stub I/O ports while retaining real command, grant, MAC and request checks."""
    state = SimpleNamespace(current=(), appended=[], revocation=None, authenticated=0, closed=0)
    request = Request(APIRequestFactory().post("/consent", {}))
    request._user = User(pk=81, username="owner", is_active=True)
    request._authenticator = SessionAuthentication()
    command = SimulatedCorporateActionGrantConsent(
        grant_id="grant-41",
        grant_version="1",
        physical_account_id=41,
        expected_binding=_binding(),
        valid_until=_AT + timedelta(minutes=10),
        consent=True,
    )
    state.scope = LockedSimulatedCorporateActionWriteScope(
        physical_account_id=41,
        binding=command.expected_binding,
        valid_until=_AT + timedelta(hours=1),
    )

    @contextmanager
    def credentials(**kwargs):
        assert kwargs["mode"] == "session"
        assert kwargs["using"] == "default"
        assert kwargs["authenticated_user"].pk == 81
        state.authenticated += 1
        yield CanonicalAccountCreationRequester(actor_id="django-user:81", user_id=81)
        state.closed += 1
        kwargs["before_commit"]()

    @contextmanager
    def trading_eligibility(**kwargs):
        assert kwargs == {"user_id": 81, "using": "default"}
        yield

    class Locker:
        database_alias = "default"

        @contextmanager
        def lock_owned_scope(self, **kwargs):
            assert kwargs["owner_user_id"] == 81
            assert kwargs["physical_account_id"] == 41
            yield state.scope

    class Repository:
        def __init__(self, *, using, clock=None):
            assert using == "default"
            self.clock = clock

        def get_current_for_scope(self, *args, **kwargs):
            return state.current

        def get_current_grant(self, *, selector, as_of):
            from apps.account.domain.simulated_corporate_action_write_grant import (
                SimulatedCorporateActionWriteGrantCurrent,
            )

            if (
                not state.revocation
                and len(state.current) == 1
                and state.current[0].selector == selector
                and state.current[0].is_active_at(as_of)
            ):
                return SimulatedCorporateActionWriteGrantCurrent(grant=state.current[0])
            return None

        def get_exact_record(self, *, selector, as_of):
            from apps.account.domain.simulated_corporate_action_write_grant import (
                SimulatedCorporateActionWriteGrantRecord,
            )

            if len(state.current) == 1 and state.current[0].selector == selector:
                return SimulatedCorporateActionWriteGrantRecord(
                    grant=state.current[0], revocation=state.revocation
                )
            return None

        def append_revocation(self, revocation):
            state.revocation = revocation
            return revocation

        def append_grant(self, grant, *, expected_predecessor_content_hash):
            assert grant.recorded_at == self.clock.now()
            assert expected_predecessor_content_hash == command.expected_predecessor_content_hash
            state.appended.append(grant)
            state.current = (grant,)
            return grant

    monkeypatch.setattr(issuance, "authenticated_creation_transaction", credentials)
    monkeypatch.setattr(
        issuance, "locked_simulated_action_trading_eligibility", trading_eligibility
    )
    monkeypatch.setattr(issuance, "DjangoSimulatedCorporateActionWriteGrantRepository", Repository)
    monkeypatch.setattr(issuance, "timezone", SimpleNamespace(now=lambda: _AT))
    monkeypatch.setattr(
        seals,
        "get_secrets",
        lambda **kwargs: SimpleNamespace(
            field_encryption_key="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
        ),
    )
    return request, command, Locker(), state


def test_explicit_owner_consent_is_sealed_and_exact_retry_reuses_current_grant(issuer):
    request, command, locker, state = issuer
    grant = issuance.issue_authenticated_simulated_corporate_action_grant(
        request, command=command, scope_locker=locker, using="default"
    )
    assert seals.SimulatedCorporateActionWriteGrantSeal().verify(grant)
    assert grant.binding == command.expected_binding
    assert grant.consented_at == grant.issued_at == grant.recorded_at == _AT
    assert (
        issuance.issue_authenticated_simulated_corporate_action_grant(
            request, command=command, scope_locker=locker, using="default"
        )
        == grant
    )
    assert state.authenticated == state.closed == 2
    assert state.appended == [grant]


@pytest.mark.parametrize("authentication", [None, TokenAuthentication()])
def test_non_session_authority_is_rejected_before_storage(issuer, authentication):
    request, command, locker, state = issuer
    request._authenticator = authentication
    with pytest.raises(AuthenticationError):
        issuance.issue_authenticated_simulated_corporate_action_grant(
            request, command=command, scope_locker=locker, using="default"
        )
    assert not state.appended and state.authenticated == 0


@pytest.mark.parametrize("mutation", ["owner", "physical", "policy", "expired"])
def test_locked_scope_substitution_or_half_open_expiry_prevents_append(issuer, mutation):
    request, command, locker, state = issuer
    changes = {
        "owner": {"binding": _binding(owner_user_id=82)},
        "physical": {"physical_account_id": 99},
        "policy": {"binding": _binding(policy_content_hash="f" * 64)},
        "expired": {"valid_until": _AT},
    }
    state.scope = replace(state.scope, **changes[mutation])
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        issuance.issue_authenticated_simulated_corporate_action_grant(
            request, command=command, scope_locker=locker, using="default"
        )
    assert not state.appended


def test_plain_stored_record_cannot_be_replayed_as_authenticated_consent(issuer):
    request, command, locker, state = issuer
    state.current = (
        replace(
            _grant(grant_version=command.grant_version, valid_until=command.valid_until),
            grant_id=command.grant_id,
            content_hash="",
            identity_hash="",
        ),
    )
    with pytest.raises(SimulatedCorporateActionWriteGrantConflict):
        issuance.issue_authenticated_simulated_corporate_action_grant(
            request, command=command, scope_locker=locker, using="default"
        )
    assert not state.appended


def test_missing_explicit_consent_is_not_a_default(issuer):
    _, command, _, state = issuer
    with pytest.raises(ValueError, match="explicit"):
        replace(command, consent=False)
    assert not state.appended


def test_owner_can_withdraw_and_retry_without_current_trading_eligibility(issuer, monkeypatch):
    request, command, locker, state = issuer
    grant = issuance.issue_authenticated_simulated_corporate_action_grant(
        request, command=command, scope_locker=locker, using="default"
    )

    def deny(**kwargs):
        raise AssertionError("withdrawal must not require a positive trading permission")

    monkeypatch.setattr(issuance, "locked_simulated_action_trading_eligibility", deny)
    revocation = issuance.revoke_authenticated_simulated_corporate_action_grant(
        request,
        selector=grant.selector,
        revocation_id="withdraw-1",
        revocation_version="1",
        using="default",
    )
    assert seals.SimulatedCorporateActionWriteGrantSeal().verify_revocation(revocation)
    assert (
        issuance.revoke_authenticated_simulated_corporate_action_grant(
            request,
            selector=grant.selector,
            revocation_id="withdraw-1",
            revocation_version="1",
            using="default",
        )
        == revocation
    )
    assert state.revocation.grant_content_hash == grant.content_hash


def test_safe_method_cannot_bypass_csrf_for_grant_mutation(issuer):
    request, command, locker, state = issuer
    request._request.method = "GET"
    from core.exceptions import AuthorizationError

    with pytest.raises(AuthorizationError):
        issuance.issue_authenticated_simulated_corporate_action_grant(
            request, command=command, scope_locker=locker, using="default"
        )
    assert state.authenticated == 0 and not state.appended
