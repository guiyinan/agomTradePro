"""Scope lookup retains collisions and never revives superseded policy heads."""

from datetime import timedelta

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentUnavailable,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from tests.unit.account.test_single_owner_authority_policy_v1 import NOW, _policy


def _reader(monkeypatch, records):
    # Only the database restore boundary is replaced; head selection is real.
    monkeypatch.setattr(
        DjangoSingleOwnerAuthorityPolicyV1Repository, "_ensure_postgresql", lambda _: None
    )
    monkeypatch.setattr(
        DjangoSingleOwnerAuthorityPolicyV1Repository, "_restore_world", lambda _: records
    )
    return DjangoSingleOwnerAuthorityPolicyV1Repository(using="scope-reader-test")


def _record(policy, previous=None):
    return (
        SingleOwnerAuthorityPolicyV1Model(
            expected_previous_content_hash=previous,
            persisted_at=policy.observed_at,
        ),
        policy,
    )


def test_returns_all_current_scope_heads_including_other_owner(monkeypatch):
    first = _policy()
    second = _policy(policy_id="second-policy", owner_user_id=18, owner_id="other-owner")
    unrelated = _policy(policy_id="unrelated", account_id="other-account")
    reader = _reader(monkeypatch, (_record(first), _record(second), _record(unrelated)))
    result = reader.get_current_for_scope(
        account_namespace="account", account_id="account-a", as_of=NOW
    )
    assert {policy.content_hash for policy in result} == {first.content_hash, second.content_hash}
    assert {policy.owner_user_id for policy in result} == {17, 18}


@pytest.mark.parametrize("status", ["active", "revoked"])
def test_only_head_is_considered_and_expired_or_revoked_head_has_no_fallback(monkeypatch, status):
    root = _policy()
    successor = _policy(
        policy_version="2",
        status=status,
        observed_at=NOW + timedelta(seconds=1),
        valid_until=NOW + timedelta(seconds=3),
    )
    reader = _reader(monkeypatch, (_record(root), _record(successor, root.content_hash)))
    cutoff = NOW + timedelta(seconds=2 if status == "revoked" else 4)
    assert (
        reader.get_current_for_scope(
            account_namespace="account", account_id="account-a", as_of=cutoff
        )
        == ()
    )


def test_future_successor_does_not_change_historical_head(monkeypatch):
    root = _policy()
    successor = _policy(policy_version="2", observed_at=NOW + timedelta(seconds=10))
    reader = _reader(monkeypatch, (_record(root), _record(successor, root.content_hash)))
    assert reader.get_current_for_scope(
        account_namespace="account", account_id="account-a", as_of=NOW
    ) == (root,)


def test_late_persisted_backdated_successor_does_not_rewrite_historical_head(monkeypatch):
    root = _policy()
    successor = _policy(
        policy_version="2",
        observed_at=NOW + timedelta(seconds=1),
        valid_until=NOW + timedelta(seconds=30),
    )
    root_row, _ = _record(root)
    successor_row, _ = _record(successor, root.content_hash)
    successor_row.persisted_at = NOW + timedelta(seconds=10)
    reader = _reader(monkeypatch, ((root_row, root), (successor_row, successor)))

    assert reader.get_head(policy_id=root.policy_id, as_of=NOW + timedelta(seconds=5)) == root
    assert reader.get_head(policy_id=root.policy_id, as_of=NOW + timedelta(seconds=10)) == successor


@pytest.mark.parametrize(
    "namespace,account_id,cutoff",
    [
        (True, "account-a", NOW),
        ("account", " account-a", NOW),
        ("account", "account-a", NOW.replace(tzinfo=None)),
    ],
)
def test_invalid_scope_or_clock_is_rejected_before_restore(
    monkeypatch, namespace, account_id, cutoff
):
    reader = _reader(monkeypatch, ())

    def unexpected_restore(_):
        pytest.fail("invalid input reached persistence")

    monkeypatch.setattr(
        DjangoSingleOwnerAuthorityPolicyV1Repository, "_restore_world", unexpected_restore
    )
    with pytest.raises(AccountOwnerAssignmentUnavailable):
        reader.get_current_for_scope(
            account_namespace=namespace, account_id=account_id, as_of=cutoff
        )


def test_missing_scope_has_no_default_policy(monkeypatch):
    reader = _reader(monkeypatch, (_record(_policy()),))
    assert (
        reader.get_current_for_scope(account_namespace="account", account_id="missing", as_of=NOW)
        == ()
    )
