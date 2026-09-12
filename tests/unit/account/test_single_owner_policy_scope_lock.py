"""Scope lock boundary requires a private UOW and unambiguous scope identity."""

import json
from contextlib import contextmanager

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentUnavailable,
)
from apps.account.infrastructure import single_owner_authority_policy_v1_repository as subject


def _repository(monkeypatch):
    monkeypatch.setattr(
        subject.DjangoSingleOwnerAuthorityPolicyV1Repository, "_ensure_postgresql", lambda _: None
    )
    return subject.DjangoSingleOwnerAuthorityPolicyV1Repository(using="scope-test")


def test_scope_lock_requires_private_uow(monkeypatch):
    repo = _repository(monkeypatch)
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="private atomic UOW"):
        repo.lock_scope(account_namespace="account", account_id="one")


def test_active_flag_alone_does_not_authorize_lock(monkeypatch):
    repo = _repository(monkeypatch)
    repo._active = True
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="private atomic UOW"):
        repo.lock_scope(account_namespace="account", account_id="one")


def test_lock_uses_bound_connection_and_canonical_tuple(monkeypatch):
    repo = _repository(monkeypatch)
    calls = []

    class Cursor:
        def execute(self, sql, params):
            calls.append((sql, params))

    class Connection:
        @contextmanager
        def cursor(self):
            yield Cursor()

    monkeypatch.setattr(subject, "connections", {"scope-test": Connection()})
    repo._active = True
    with subject._activate_single_owner_authority_policy_v1_uow(repo._token):
        repo.lock_scope(account_namespace="a:b", account_id="c")
        repo.lock_scope(account_namespace="a", account_id="b:c")
    assert len(calls) == 2
    assert calls[0][0] == "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
    assert json.loads(calls[0][1][0]) == ["account.single-owner-policy.scope.v1", "a:b", "c"]
    assert calls[0][1] != calls[1][1]


@pytest.mark.parametrize("namespace,account_id", [(True, "a"), ("a", ""), ("a", " b")])
def test_invalid_scope_never_opens_connection(monkeypatch, namespace, account_id):
    repo = _repository(monkeypatch)
    monkeypatch.setattr(subject, "connections", {})
    repo._active = True
    with subject._activate_single_owner_authority_policy_v1_uow(repo._token):
        with pytest.raises(AccountOwnerAssignmentUnavailable, match="scope is invalid"):
            repo.lock_scope(account_namespace=namespace, account_id=account_id)
