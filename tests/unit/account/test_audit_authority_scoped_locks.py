"""Unit contracts for the V5/V3 audit-authority scoped transaction locks."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager

import pytest
from django.db import DatabaseError

from apps.account.application.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5Unavailable,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Unavailable,
)
from apps.account.infrastructure import (
    account_owner_assignment_evidence_v5_repository as evidence_v5_repository,
)
from apps.account.infrastructure import (
    owner_tenant_authority_v3_repository as authority_v3_repository,
)
from shared.infrastructure.postgres_advisory_lock import (
    ScopedAdvisoryLockKey,
    ScopedAdvisoryLockUnavailableError,
    derive_scoped_advisory_lock_id,
)


class _Cursor:
    """Record SQL issued by a repository lock helper."""

    def __init__(
        self,
        events: list[tuple[object, ...]],
        *,
        legacy_lock_result: bool = True,
        fail_statement_prefix: str | None = None,
    ) -> None:
        self._events = events
        self._legacy_lock_result = legacy_lock_result
        self._fail_statement_prefix = fail_statement_prefix
        self._last_statement = ""

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, params: list[object] | None = None) -> None:
        self._last_statement = statement
        self._events.append(("sql", statement, params))
        if self._fail_statement_prefix is not None and statement.startswith(
            self._fail_statement_prefix
        ):
            raise DatabaseError("simulated relation lock failure")

    def fetchone(self) -> tuple[object, ...] | None:
        if self._last_statement == "SHOW transaction_isolation":
            return ("read committed",)
        if self._last_statement.startswith("SELECT pg_try_advisory_xact_lock"):
            return (self._legacy_lock_result,)
        return None


class _Operations:
    """Provide quoted model names for the simulated PostgreSQL connection."""

    def quote_name(self, name: str) -> str:
        return f'"{name}"'


class _Connection:
    """Expose only the connection properties consumed by the lock helpers."""

    alias = "default"
    vendor = "postgresql"
    in_atomic_block = True
    ops = _Operations()

    def __init__(
        self,
        events: list[tuple[object, ...]],
        *,
        legacy_lock_result: bool = True,
        fail_statement_prefix: str | None = None,
    ) -> None:
        self._events = events
        self._legacy_lock_result = legacy_lock_result
        self._fail_statement_prefix = fail_statement_prefix

    def get_autocommit(self) -> bool:
        return False

    def cursor(self) -> _Cursor:
        return _Cursor(
            self._events,
            legacy_lock_result=self._legacy_lock_result,
            fail_statement_prefix=self._fail_statement_prefix,
        )


def _record_scoped_acquirer(events: list[tuple[object, ...]], mode: str):
    """Return a fake scoped-lock acquirer that records its canonical plan."""

    def acquire(
        *, using: str, keys: Iterable[ScopedAdvisoryLockKey]
    ) -> tuple[ScopedAdvisoryLockKey, ...]:
        plan = tuple(keys)
        events.append(("scoped", mode, using, plan))
        return plan

    return acquire


def _record_atomic(events: list[tuple[object, ...]]):
    """Return a savepoint context manager that records commit and rollback."""

    @contextmanager
    def atomic(*, using: str) -> Iterator[None]:
        events.append(("savepoint", "begin", using))
        try:
            yield
        except Exception:
            events.append(("savepoint", "rollback", using))
            raise
        else:
            events.append(("savepoint", "release", using))

    return atomic


def test_evidence_v5_policy_lock_is_scoped_and_precedes_legacy_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same-policy readers/writers share one key; another policy gets its own."""

    events: list[tuple[object, ...]] = []
    monkeypatch.setattr(evidence_v5_repository.transaction, "atomic", _record_atomic(events))
    monkeypatch.setattr(evidence_v5_repository, "connections", {"default": _Connection(events)})
    monkeypatch.setattr(
        evidence_v5_repository,
        "try_acquire_scoped_advisory_shared",
        _record_scoped_acquirer(events, "shared"),
    )
    monkeypatch.setattr(
        evidence_v5_repository,
        "try_acquire_scoped_advisory_exclusive",
        _record_scoped_acquirer(events, "exclusive"),
    )

    evidence_v5_repository.lock_account_owner_assignment_evidence_v5_sources_for_read(
        using="default", policy_id="policy-a"
    )
    evidence_v5_repository.lock_account_owner_assignment_evidence_v5_sources_for_read(
        using="default", policy_id="policy-a"
    )
    evidence_v5_repository.lock_account_owner_assignment_evidence_v5_sources(
        using="default", policy_id="policy-a"
    )
    evidence_v5_repository.lock_account_owner_assignment_evidence_v5_sources(
        using="default", policy_id="policy-b"
    )

    scoped_calls = [event for event in events if event[0] == "scoped"]
    plans = [event[3] for event in scoped_calls]
    keys = [plan[0] for plan in plans]
    assert [event[1] for event in scoped_calls] == [
        "shared",
        "shared",
        "exclusive",
        "exclusive",
    ]
    assert keys[0] == keys[1] == keys[2]
    assert keys[3] != keys[0]
    assert derive_scoped_advisory_lock_id(keys[3]) != derive_scoped_advisory_lock_id(keys[0])
    assert keys[0].domain == "account.assignment-evidence-v5.policy"
    assert keys[0].components == ("policy-a",)

    first_shared_index = events.index(scoped_calls[0])
    following_sql = [event[1] for event in events[first_shared_index + 1 :] if event[0] == "sql"]
    assert following_sql[0].startswith("SELECT pg_try_advisory_xact_lock_shared")
    assert following_sql[1].startswith("LOCK TABLE ")


def test_authority_v3_policy_lock_follows_v5_and_precedes_v3_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authority V3 always locks its V5 parent first, then its own policy key."""

    events: list[tuple[object, ...]] = []
    monkeypatch.setattr(authority_v3_repository.transaction, "atomic", _record_atomic(events))
    monkeypatch.setattr(authority_v3_repository, "connections", {"default": _Connection(events)})

    def parent_read(*, using: str, policy_id: str) -> None:
        events.append(("v5-parent", "read", using, policy_id))

    def parent_write(*, using: str, policy_id: str) -> None:
        events.append(("v5-parent", "write", using, policy_id))

    monkeypatch.setattr(
        authority_v3_repository,
        "lock_account_owner_assignment_evidence_v5_sources_for_read",
        parent_read,
    )
    monkeypatch.setattr(
        authority_v3_repository,
        "lock_account_owner_assignment_evidence_v5_sources",
        parent_write,
    )
    monkeypatch.setattr(
        authority_v3_repository,
        "try_acquire_scoped_advisory_shared",
        _record_scoped_acquirer(events, "shared"),
    )
    monkeypatch.setattr(
        authority_v3_repository,
        "try_acquire_scoped_advisory_exclusive",
        _record_scoped_acquirer(events, "exclusive"),
    )

    authority_v3_repository.lock_owner_tenant_authority_v3_sources_for_read(
        using="default", policy_id="policy-a"
    )
    authority_v3_repository.lock_owner_tenant_authority_v3_sources_for_read(
        using="default", policy_id="policy-a"
    )
    authority_v3_repository.lock_owner_tenant_authority_v3_sources(
        using="default", policy_id="policy-a"
    )
    authority_v3_repository.lock_owner_tenant_authority_v3_sources(
        using="default", policy_id="policy-b"
    )

    parent_calls = [event for event in events if event[0] == "v5-parent"]
    scoped_calls = [event for event in events if event[0] == "scoped"]
    plans = [event[3] for event in scoped_calls]
    keys = [plan[0] for plan in plans]
    assert [event[1] for event in parent_calls] == ["read", "read", "write", "write"]
    assert [event[1] for event in scoped_calls] == [
        "shared",
        "shared",
        "exclusive",
        "exclusive",
    ]
    assert keys[0] == keys[1] == keys[2]
    assert keys[3] != keys[0]
    assert derive_scoped_advisory_lock_id(keys[3]) != derive_scoped_advisory_lock_id(keys[0])
    assert keys[0].domain == "account.owner-tenant-authority-v3.policy"
    assert keys[0].components == ("policy-a",)

    for parent_call, scoped_call in zip(parent_calls, scoped_calls, strict=True):
        assert events.index(parent_call) < events.index(scoped_call)
        scoped_index = events.index(scoped_call)
        following_sql = [event[1] for event in events[scoped_index + 1 :] if event[0] == "sql"]
        assert following_sql[0].startswith("LOCK TABLE ")


def test_scoped_lock_errors_map_to_existing_business_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed lock failures retain the public repositories' failure contracts."""

    events: list[tuple[object, ...]] = []
    monkeypatch.setattr(evidence_v5_repository.transaction, "atomic", _record_atomic(events))
    monkeypatch.setattr(evidence_v5_repository, "connections", {"default": _Connection(events)})

    def fail_evidence_lock(
        *, using: str, keys: Iterable[ScopedAdvisoryLockKey]
    ) -> tuple[ScopedAdvisoryLockKey, ...]:
        plan = tuple(keys)
        raise ScopedAdvisoryLockUnavailableError(using=using, key=plan[0])

    monkeypatch.setattr(
        evidence_v5_repository,
        "try_acquire_scoped_advisory_shared",
        fail_evidence_lock,
    )
    with pytest.raises(AccountOwnerAssignmentEvidenceV5Unavailable) as evidence_error:
        evidence_v5_repository.lock_account_owner_assignment_evidence_v5_sources_for_read(
            using="default", policy_id="policy-a"
        )
    assert isinstance(evidence_error.value.__cause__, ScopedAdvisoryLockUnavailableError)
    assert not any(
        event[0] == "sql" and str(event[1]).startswith("SELECT pg_try_advisory_xact_lock")
        for event in events
    )

    events.clear()
    monkeypatch.setattr(authority_v3_repository, "connections", {"default": _Connection(events)})

    def parent_read(*, using: str, policy_id: str) -> None:
        events.append(("v5-parent", "read", using, policy_id))

    def fail_authority_lock(
        *, using: str, keys: Iterable[ScopedAdvisoryLockKey]
    ) -> tuple[ScopedAdvisoryLockKey, ...]:
        plan = tuple(keys)
        raise ScopedAdvisoryLockUnavailableError(using=using, key=plan[0])

    monkeypatch.setattr(
        authority_v3_repository,
        "lock_account_owner_assignment_evidence_v5_sources_for_read",
        parent_read,
    )
    monkeypatch.setattr(
        authority_v3_repository,
        "try_acquire_scoped_advisory_shared",
        fail_authority_lock,
    )
    with pytest.raises(OwnerTenantAuthorityV3Unavailable) as authority_error:
        authority_v3_repository.lock_owner_tenant_authority_v3_sources_for_read(
            using="default", policy_id="policy-a"
        )
    assert isinstance(authority_error.value.__cause__, ScopedAdvisoryLockUnavailableError)
    assert not any(
        event[0] == "sql" and str(event[1]).startswith("LOCK TABLE ") for event in events
    )


@pytest.mark.parametrize(
    ("legacy_lock_result", "fail_statement_prefix"),
    ((False, None), (True, "LOCK TABLE ")),
)
def test_evidence_v5_legacy_failure_rolls_back_scoped_key_savepoint(
    monkeypatch: pytest.MonkeyPatch,
    legacy_lock_result: bool,
    fail_statement_prefix: str | None,
) -> None:
    """Legacy advisory and relation failures release this attempt's new key."""

    events: list[tuple[object, ...]] = []
    connection = _Connection(
        events,
        legacy_lock_result=legacy_lock_result,
        fail_statement_prefix=fail_statement_prefix,
    )
    monkeypatch.setattr(evidence_v5_repository, "connections", {"default": connection})
    monkeypatch.setattr(
        evidence_v5_repository,
        "try_acquire_scoped_advisory_shared",
        _record_scoped_acquirer(events, "shared"),
    )
    monkeypatch.setattr(
        evidence_v5_repository.transaction,
        "atomic",
        _record_atomic(events),
    )

    with pytest.raises(AccountOwnerAssignmentEvidenceV5Unavailable):
        evidence_v5_repository.lock_account_owner_assignment_evidence_v5_sources_for_read(
            using="default", policy_id="policy-a"
        )

    assert [event[1] for event in events if event[0] == "savepoint"] == [
        "begin",
        "rollback",
    ]
    scoped_index = next(index for index, event in enumerate(events) if event[0] == "scoped")
    rollback_index = next(
        index for index, event in enumerate(events) if event[0:2] == ("savepoint", "rollback")
    )
    assert scoped_index < rollback_index


def test_authority_v3_relation_failure_rolls_back_v5_and_v3_scoped_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The V3 savepoint covers parent V5, V3 key, and final relation locks."""

    events: list[tuple[object, ...]] = []
    connection = _Connection(events, fail_statement_prefix="LOCK TABLE ")
    monkeypatch.setattr(authority_v3_repository, "connections", {"default": connection})

    def parent_read(*, using: str, policy_id: str) -> None:
        events.append(("v5-parent", "read", using, policy_id))

    monkeypatch.setattr(
        authority_v3_repository,
        "lock_account_owner_assignment_evidence_v5_sources_for_read",
        parent_read,
    )
    monkeypatch.setattr(
        authority_v3_repository,
        "try_acquire_scoped_advisory_shared",
        _record_scoped_acquirer(events, "shared"),
    )
    monkeypatch.setattr(
        authority_v3_repository.transaction,
        "atomic",
        _record_atomic(events),
    )

    with pytest.raises(OwnerTenantAuthorityV3Unavailable):
        authority_v3_repository.lock_owner_tenant_authority_v3_sources_for_read(
            using="default", policy_id="policy-a"
        )

    savepoints = [event[1] for event in events if event[0] == "savepoint"]
    assert savepoints == ["begin", "rollback"]
    begin_index = events.index(("savepoint", "begin", "default"))
    parent_index = next(index for index, event in enumerate(events) if event[0] == "v5-parent")
    scoped_index = next(index for index, event in enumerate(events) if event[0] == "scoped")
    relation_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "sql" and str(event[1]).startswith("LOCK TABLE ")
    )
    rollback_index = events.index(("savepoint", "rollback", "default"))
    assert begin_index < parent_index < scoped_index < relation_index < rollback_index
