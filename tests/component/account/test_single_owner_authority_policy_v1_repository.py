"""Opt-in PostgreSQL contract tests for the single-owner policy ledger."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Protocol, cast

import pytest
from django.core.exceptions import ValidationError
from django.db import connections, transaction

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    ACTIVE_STATUS,
    REVOKED_STATUS,
    SingleOwnerAuthorityPolicyV1,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from apps.account.single_owner_authority_policy_composition import (
    build_current_single_owner_policy_resolver,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (  # noqa: F401 - imported fixture is registered in this test module
    evid06_alias,
)


class _DjangoDbBlocker(Protocol):
    """Narrow protocol for the opt-in fixture's database unblocker."""

    def unblock(self) -> AbstractContextManager[None]:
        """Temporarily permit isolated-schema DDL."""


@pytest.fixture(name="policy_alias")
def policy_alias(
    request: pytest.FixtureRequest, django_db_blocker: _DjangoDbBlocker
) -> Iterator[str]:
    """Add and remove the policy ledger table inside the dedicated EVID-06 DB."""

    base_alias = cast(str, request.getfixturevalue("evid06_alias"))
    connection = connections[base_alias]
    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.create_model(SingleOwnerAuthorityPolicyV1Model)
    try:
        yield base_alias
    finally:
        with django_db_blocker.unblock():
            with connection.schema_editor() as editor:
                editor.delete_model(SingleOwnerAuthorityPolicyV1Model)


def _policy(
    *,
    observed_at: datetime,
    valid_from: datetime,
    valid_until: datetime,
    policy_id: str = "policy-001",
    policy_version: str = "v1",
    tenant_id: str = "tenant-001",
    owner_id: str = "owner-001",
    account_namespace: str = "broker",
    account_id: str = "account-001",
    owner_user_id: int = 1,
    authorization_content_hash: str = "a" * 64,
    status: str = ACTIVE_STATUS,
) -> SingleOwnerAuthorityPolicyV1:
    """Build one valid policy whose source clocks are supplied by the test."""

    return SingleOwnerAuthorityPolicyV1(
        policy_id=policy_id,
        policy_version=policy_version,
        tenant_id=tenant_id,
        owner_id=owner_id,
        account_namespace=account_namespace,
        account_id=account_id,
        owner_user_id=owner_user_id,
        authorization_content_hash=authorization_content_hash,
        observed_at=observed_at,
        valid_from=valid_from,
        valid_until=valid_until,
        status=status,
    )


@pytest.mark.parametrize("lock_mode", ["explicit", "append"])
def test_scope_lock_blocks_other_connection_and_releases_after_transaction(
    policy_alias: str, django_db_blocker: _DjangoDbBlocker, lock_mode: str
) -> None:
    """Real PostgreSQL scope lock excludes a second session and releases on exit."""
    with django_db_blocker.unblock():
        repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
        probe = connections[policy_alias].copy(alias="policy-scope-lock-probe")
        key = json.dumps(
            ["account.single-owner-policy.scope.v1", "account", "lock-test"],
            separators=(",", ":"),
        )
        try:
            with repository.atomic():
                if lock_mode == "explicit":
                    repository.lock_scope(account_namespace="account", account_id="lock-test")
                else:
                    now = repository.now()
                    repository.append(
                        policy=_policy(
                            account_namespace="account",
                            account_id="lock-test",
                            observed_at=now,
                            valid_from=now,
                            valid_until=now + timedelta(minutes=5),
                        ),
                        expected_previous_content_hash=None,
                    )
                with probe.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [key]
                    )
                    assert cursor.fetchone() == (False,)
            with probe.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [key])
                assert cursor.fetchone() == (True,)
        finally:
            probe.close()


def _root(repository: DjangoSingleOwnerAuthorityPolicyV1Repository) -> SingleOwnerAuthorityPolicyV1:
    """Build a root observed safely before the live repository clock."""

    now = repository.now()
    return _policy(
        observed_at=now - timedelta(hours=1),
        valid_from=now - timedelta(hours=2),
        valid_until=now + timedelta(days=1),
    )


def _append(
    repository: DjangoSingleOwnerAuthorityPolicyV1Repository,
    policy: SingleOwnerAuthorityPolicyV1,
    previous: str | None = None,
) -> SingleOwnerAuthorityPolicyV1:
    """Append one policy under the repository's private UOW."""

    with repository.atomic():
        return repository.append(
            policy=policy,
            expected_previous_content_hash=previous,
        )


def test_root_read_exact_and_historical_cutoff(policy_alias: str) -> None:
    """A root is readable by exact hash and is absent before its observation."""

    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    root = _root(repository)
    stored = _append(repository, root)

    assert stored == root
    assert (
        repository.get_head(
            policy_id=root.policy_id, as_of=root.observed_at - timedelta(microseconds=1)
        )
        is None
    )
    cutoff = repository.now()
    assert repository.get_head(policy_id=root.policy_id, as_of=cutoff) == root
    assert (
        repository.get_exact_current(
            policy_id=root.policy_id,
            policy_version=root.policy_version,
            expected_content_hash=root.content_hash,
            as_of=cutoff,
        )
        == root
    )
    assert (
        repository.get_exact_current(
            policy_id=root.policy_id,
            policy_version="missing",
            expected_content_hash=root.content_hash,
            as_of=cutoff,
        )
        is None
    )


def test_scope_reader_retains_owner_collisions_and_revocation_has_no_fallback(
    policy_alias: str,
) -> None:
    """Stored test policies remain distinct candidates, never implicit authority."""
    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    first = _root(repository)
    _append(repository, first)
    second = _policy(
        policy_id="second-owner-policy",
        owner_id="second-owner",
        owner_user_id=2,
        observed_at=first.observed_at,
        valid_from=first.valid_from,
        valid_until=first.valid_until,
    )
    _append(repository, second)
    cutoff = repository.now()
    candidates = repository.get_current_for_scope(
        account_namespace=first.account_namespace,
        account_id=first.account_id,
        as_of=cutoff,
    )
    assert {policy.content_hash for policy in candidates} == {
        first.content_hash,
        second.content_hash,
    }
    assert {policy.owner_user_id for policy in candidates} == {1, 2}
    revoked = _policy(
        policy_version="v2",
        status=REVOKED_STATUS,
        observed_at=first.observed_at + timedelta(minutes=1),
        valid_from=first.valid_from,
        valid_until=first.valid_until,
    )
    _append(repository, revoked, first.content_hash)
    assert repository.get_current_for_scope(
        account_namespace=first.account_namespace,
        account_id=first.account_id,
        as_of=repository.now(),
    ) == (second,)
    assert (
        repository.get_current_for_scope(
            account_namespace=first.account_namespace,
            account_id="missing",
            as_of=repository.now(),
        )
        == ()
    )


def test_policy_resolver_requires_one_scope_head_before_matching_owner(policy_alias: str) -> None:
    """Real policy lookup must reject collisions for both owners, without issuing authority."""
    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    resolver = build_current_single_owner_policy_resolver(using=policy_alias)
    first = _root(repository)

    def resolve(owner_user_id: int):
        return resolver.resolve(
            account_namespace=first.account_namespace,
            account_id=first.account_id,
            owner_user_id=owner_user_id,
            as_of=repository.now(),
        )

    assert resolve(first.owner_user_id) is None
    _append(repository, first)
    selected = resolve(first.owner_user_id)
    assert selected is not None
    assert selected.expected_content_hash == first.content_hash
    assert selected.tenant_id == first.tenant_id
    assert selected.owner_id == first.owner_id
    with pytest.raises(AccountOwnerAssignmentCorruption):
        resolve(2)

    second = _policy(
        policy_id="colliding-owner-policy",
        owner_id="other-owner",
        owner_user_id=2,
        observed_at=first.observed_at,
        valid_from=first.valid_from,
        valid_until=first.valid_until,
    )
    _append(repository, second)
    for user_id in (first.owner_user_id, second.owner_user_id):
        with pytest.raises(AccountOwnerAssignmentConflict):
            resolve(user_id)
    revoked = _policy(
        policy_id=second.policy_id,
        policy_version="v2",
        owner_id=second.owner_id,
        owner_user_id=second.owner_user_id,
        status=REVOKED_STATUS,
        observed_at=first.observed_at + timedelta(minutes=1),
        valid_from=first.valid_from,
        valid_until=first.valid_until,
    )
    _append(repository, revoked, second.content_hash)
    restored = resolve(first.owner_user_id)
    assert restored == selected
    assert SingleOwnerAuthorityPolicyV1Model.objects.using(policy_alias).count() == 3


def test_root_replay_identity_conflict_and_append_guard(policy_alias: str) -> None:
    """Exact replays are idempotent while identity changes and outside writes fail."""

    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    root = _root(repository)
    assert _append(repository, root) == root
    assert _append(repository, root) == root
    assert SingleOwnerAuthorityPolicyV1Model._default_manager.using(policy_alias).count() == 1

    changed = _policy(
        observed_at=root.observed_at,
        valid_from=root.valid_from,
        valid_until=root.valid_until,
        authorization_content_hash="b" * 64,
    )
    with pytest.raises(AccountOwnerAssignmentConflict, match="identity"):
        _append(repository, changed)
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="private atomic UOW"):
        repository.append(policy=root, expected_previous_content_hash=None)


def test_successor_cas_scope_and_revoked_head_no_fallback(policy_alias: str) -> None:
    """Successors require the exact current hash and a revoked head is terminal for reads."""

    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    root = _root(repository)
    _append(repository, root)
    successor = _policy(
        observed_at=root.observed_at + timedelta(minutes=5),
        valid_from=root.valid_from,
        valid_until=root.valid_until,
        policy_version="v2",
        authorization_content_hash="b" * 64,
    )
    assert _append(repository, successor, root.content_hash) == successor
    revoked = _policy(
        observed_at=successor.observed_at + timedelta(minutes=5),
        valid_from=root.valid_from,
        valid_until=root.valid_until,
        policy_version="v3",
        authorization_content_hash="c" * 64,
        status=REVOKED_STATUS,
    )
    assert _append(repository, revoked, successor.content_hash) == revoked

    assert repository.get_head(policy_id=root.policy_id, as_of=repository.now()) == revoked
    assert (
        repository.get_exact_current(
            policy_id=root.policy_id,
            policy_version=successor.policy_version,
            expected_content_hash=successor.content_hash,
            as_of=repository.now(),
        )
        is None
    )
    assert _append(repository, successor, root.content_hash) == successor


def test_successor_rejects_missing_cross_scope_and_stale_predecessor(policy_alias: str) -> None:
    """CAS rejects an absent, cross-policy, scope-changing, or non-head predecessor."""

    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    root = _root(repository)
    _append(repository, root)
    successor = _policy(
        observed_at=root.observed_at + timedelta(minutes=5),
        valid_from=root.valid_from,
        valid_until=root.valid_until,
        policy_version="v2",
        authorization_content_hash="b" * 64,
    )
    with pytest.raises(AccountOwnerAssignmentConflict, match="not persisted"):
        _append(repository, successor, "d" * 64)

    cross_policy = _policy(
        observed_at=successor.observed_at,
        valid_from=root.valid_from,
        valid_until=root.valid_until,
        policy_id="policy-002",
        policy_version="v2",
        authorization_content_hash="c" * 64,
    )
    with pytest.raises(AccountOwnerAssignmentConflict, match="policy_id"):
        _append(repository, cross_policy, root.content_hash)

    changed_scope = _policy(
        observed_at=successor.observed_at,
        valid_from=root.valid_from,
        valid_until=root.valid_until,
        policy_version="v2",
        account_id="account-002",
        authorization_content_hash="d" * 64,
    )
    with pytest.raises(AccountOwnerAssignmentConflict, match="immutable scope"):
        _append(repository, changed_scope, root.content_hash)

    assert _append(repository, successor, root.content_hash) == successor
    later = _policy(
        observed_at=successor.observed_at + timedelta(minutes=5),
        valid_from=root.valid_from,
        valid_until=root.valid_until,
        policy_version="v3",
        authorization_content_hash="e" * 64,
    )
    with pytest.raises(AccountOwnerAssignmentConflict, match="no longer the chain head"):
        _append(repository, later, root.content_hash)


def test_outer_alias_transaction_and_private_reentry(policy_alias: str) -> None:
    """An outer caller transaction is allowed, while the same UOW cannot re-enter."""

    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    root = _root(repository)
    with transaction.atomic(using=policy_alias):
        with repository.atomic():
            assert (
                repository.append(
                    policy=root,
                    expected_previous_content_hash=None,
                )
                == root
            )
    assert repository.get_head(policy_id=root.policy_id, as_of=repository.now()) == root

    with pytest.raises(AccountOwnerAssignmentConflict, match="cannot be re-entered"):
        with repository.atomic():
            with repository.atomic():
                pass

    other_repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    with repository.atomic():
        with other_repository.atomic():
            with pytest.raises(AccountOwnerAssignmentConflict, match="cannot be re-entered"):
                with repository.atomic():
                    pass


def test_append_rollback_and_model_mutation_guards(policy_alias: str) -> None:
    """A failed private UOW leaves no row and direct ORM mutation remains closed."""

    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    root = _root(repository)
    with pytest.raises(RuntimeError, match="rollback"):
        with repository.atomic():
            repository.append(policy=root, expected_previous_content_hash=None)
            raise RuntimeError("rollback")
    assert SingleOwnerAuthorityPolicyV1Model._default_manager.using(policy_alias).count() == 0

    row = SingleOwnerAuthorityPolicyV1Model(policy_id=root.policy_id)
    with pytest.raises(ValidationError, match="exact insert claim"):
        row.save(force_insert=True, using=policy_alias)
    with pytest.raises(ValidationError, match="requires exact appends"):
        SingleOwnerAuthorityPolicyV1Model._default_manager.using(policy_alias).bulk_create([row])
    with pytest.raises(ValidationError, match="updated"):
        SingleOwnerAuthorityPolicyV1Model._default_manager.using(policy_alias).update(
            status="active"
        )
    with pytest.raises(ValidationError, match="append-only"):
        row.delete(using=policy_alias)


def test_tampered_denormalized_field_and_record_seal_are_corruption(policy_alias: str) -> None:
    """A DB-level tamper cannot be projected back into a trusted Domain policy."""

    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    root = _root(repository)
    _append(repository, root)
    table = connections[policy_alias].ops.quote_name(
        SingleOwnerAuthorityPolicyV1Model._meta.db_table
    )
    with connections[policy_alias].cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET authorization_content_hash = %s WHERE content_hash = %s",
            ["b" * 64, root.content_hash],
        )
    with pytest.raises(AccountOwnerAssignmentCorruption, match="scalar"):
        repository.get_head(policy_id=root.policy_id, as_of=repository.now())

    with connections[policy_alias].cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET authorization_content_hash = %s WHERE content_hash = %s",
            [root.authorization_content_hash, root.content_hash],
        )
        cursor.execute(
            f"UPDATE {table} SET record_seal = %s WHERE content_hash = %s",
            ["0" * 64, root.content_hash],
        )
    with pytest.raises(AccountOwnerAssignmentCorruption, match="record_seal"):
        repository.get_head(policy_id=root.policy_id, as_of=repository.now())


def test_tampered_persisted_at_is_rejected_by_record_seal(policy_alias: str) -> None:
    """The ledger seal covers persistence time as well as policy source facts."""

    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    root = _root(repository)
    _append(repository, root)
    table = connections[policy_alias].ops.quote_name(
        SingleOwnerAuthorityPolicyV1Model._meta.db_table
    )
    with connections[policy_alias].cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET persisted_at = %s WHERE content_hash = %s",
            [root.observed_at + timedelta(seconds=1), root.content_hash],
        )
    with pytest.raises(AccountOwnerAssignmentCorruption, match="record_seal"):
        repository.get_head(policy_id=root.policy_id, as_of=repository.now())


def test_policy_alias_is_postgresql_and_default_alias_is_rejected(policy_alias: str) -> None:
    """The durable ledger cannot silently fall back to the local SQLite alias."""

    assert connections[policy_alias].vendor == "postgresql"
    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using="default")
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="PostgreSQL"):
        repository.now()


def test_policy_record_seal_binds_complete_payload_and_predecessor(policy_alias: str) -> None:
    """The persisted envelope exposes the complete JSON policy and predecessor CAS."""

    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    root = _root(repository)
    _append(repository, root)
    successor = _policy(
        observed_at=root.observed_at + timedelta(minutes=5),
        valid_from=root.valid_from,
        valid_until=root.valid_until,
        policy_version="v2",
        authorization_content_hash="b" * 64,
    )
    _append(repository, successor, root.content_hash)
    row = SingleOwnerAuthorityPolicyV1Model._default_manager.using(policy_alias).get(
        content_hash=successor.content_hash
    )
    assert row.expected_previous_content_hash == root.content_hash
    assert set(cast(dict[str, object], row.canonical_payload)) == {
        "policy_id",
        "policy_version",
        "tenant_id",
        "owner_id",
        "account_namespace",
        "account_id",
        "owner_user_id",
        "authorization_content_hash",
        "observed_at",
        "valid_from",
        "valid_until",
        "status",
        "identity_hash",
        "content_hash",
        "schema",
        "artifact_type",
        "mode",
    }
    assert type(json.loads(json.dumps(row.canonical_payload))) is dict


__all__ = ["policy_alias"]
