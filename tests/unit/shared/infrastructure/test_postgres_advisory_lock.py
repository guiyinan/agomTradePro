"""Pure contract tests for PostgreSQL scoped advisory lock primitives."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from django.db import DatabaseError

from shared.infrastructure import postgres_advisory_lock as subject


class _Cursor:
    def __init__(self, results: tuple[object, ...]) -> None:
        self._results = iter(results)
        self.calls: list[tuple[str, list[int]]] = []

    def execute(self, statement: str, params: list[int]) -> None:
        self.calls.append((statement, params))

    def fetchone(self) -> tuple[object, ...] | None:
        result = next(self._results)
        if result is None:
            return None
        return (result,)


class _Connection:
    def __init__(
        self,
        *,
        results: tuple[object, ...] = (),
        alias: str = "lock-test",
        vendor: str = "postgresql",
        in_atomic_block: bool = True,
        autocommit: bool = False,
    ) -> None:
        self.alias = alias
        self.vendor = vendor
        self.in_atomic_block = in_atomic_block
        self._autocommit = autocommit
        self.cursor_object = _Cursor(results)

    def get_autocommit(self) -> bool:
        """Return the fake connection's transaction mode."""

        return self._autocommit

    @contextmanager
    def cursor(self) -> Iterator[_Cursor]:
        """Yield the fake cursor used by one lock plan."""

        yield self.cursor_object


def _key(domain: str, *components: str) -> subject.ScopedAdvisoryLockKey:
    """Build one test key with the production constructor."""

    return subject.ScopedAdvisoryLockKey(domain=domain, components=components)


def _bind(monkeypatch: pytest.MonkeyPatch, connection: _Connection) -> None:
    """Bind one fake alias without opening a database connection."""

    monkeypatch.setattr(subject, "connections", {connection.alias: connection})

    @contextmanager
    def atomic(*, using: str) -> Iterator[None]:
        """Model the nested savepoint used by the production helper."""

        assert using == connection.alias
        yield

    monkeypatch.setattr(subject.transaction, "atomic", atomic)


def test_key_derivation_is_deterministic_and_domain_scoped() -> None:
    """Equal canonical keys match while domains occupy separate hash inputs."""

    authority = _key("authority", "tenant-1", "selector-1")
    same_authority = _key("authority", "tenant-1", "selector-1")
    physical = _key("physical", "tenant-1", "selector-1")

    assert subject.derive_scoped_advisory_lock_id(
        authority
    ) == subject.derive_scoped_advisory_lock_id(same_authority)
    assert subject.derive_scoped_advisory_lock_id(
        authority
    ) != subject.derive_scoped_advisory_lock_id(physical)


def test_key_derivation_matches_the_v1_golden_vector() -> None:
    """The namespace and serialization contract remain stable across releases."""

    key = _key("account.audit", "authority", "tenant-1", "selector-1")

    assert subject.derive_scoped_advisory_lock_id(key) == 7659460284993968939


def test_lock_plan_is_sorted_and_deduplicated() -> None:
    """Every caller gets one stable order even when a key appears twice."""

    first = _key("authority", "b")
    second = _key("authority", "a")

    expected = tuple(
        sorted(
            {first, second},
            key=lambda key: (subject.derive_scoped_advisory_lock_id(key), key),
        )
    )

    assert subject.canonicalize_scoped_advisory_lock_keys((first, second, first)) == expected
    assert [subject.derive_scoped_advisory_lock_id(key) for key in expected] == sorted(
        subject.derive_scoped_advisory_lock_id(key) for key in expected
    )


def test_empty_or_invalid_key_plan_is_rejected() -> None:
    """An empty plan cannot accidentally be mistaken for a protected operation."""

    with pytest.raises(subject.ScopedAdvisoryLockConfigurationError, match="at least one key"):
        subject.canonicalize_scoped_advisory_lock_keys(())
    with pytest.raises(subject.ScopedAdvisoryLockConfigurationError, match="contains an invalid"):
        subject.canonicalize_scoped_advisory_lock_keys((object(),))  # type: ignore[arg-type]


def test_shared_try_acquire_uses_canonical_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shared mode uses PostgreSQL's non-blocking shared xact function."""

    connection = _Connection(results=(True, True))
    _bind(monkeypatch, connection)
    first = _key("authority", "b")
    second = _key("authority", "a")
    expected = subject.canonicalize_scoped_advisory_lock_keys((first, second))

    assert subject.try_acquire_scoped_advisory_shared(using="lock-test", keys=(first, second)) == (
        expected
    )
    assert [call[0] for call in connection.cursor_object.calls] == [
        "SELECT pg_try_advisory_xact_lock_shared(%s)",
        "SELECT pg_try_advisory_xact_lock_shared(%s)",
    ]
    assert [call[1][0] for call in connection.cursor_object.calls] == [
        subject.derive_scoped_advisory_lock_id(expected[0]),
        subject.derive_scoped_advisory_lock_id(expected[1]),
    ]


def test_exclusive_try_acquire_uses_exclusive_function(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exclusive mode uses PostgreSQL's non-blocking exclusive xact function."""

    connection = _Connection(results=(True,))
    _bind(monkeypatch, connection)
    key = _key("authority", "one")

    assert subject.try_acquire_scoped_advisory_exclusive(using="lock-test", keys=(key,)) == (key,)
    assert connection.cursor_object.calls == [
        ("SELECT pg_try_advisory_xact_lock(%s)", [subject.derive_scoped_advisory_lock_id(key)])
    ]


def test_false_result_raises_and_stops_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contention is typed and non-blocking; later keys are never attempted."""

    connection = _Connection(results=(False, True))
    _bind(monkeypatch, connection)
    first = _key("authority", "selector-secret")
    second = _key("authority", "b")
    expected = subject.canonicalize_scoped_advisory_lock_keys((first, second))

    with pytest.raises(subject.ScopedAdvisoryLockUnavailableError) as raised:
        subject.try_acquire_scoped_advisory_shared(using="lock-test", keys=(first, second))

    assert raised.value.using == "lock-test"
    assert raised.value.key == expected[0]
    assert raised.value.details == {}
    assert "selector-secret" not in str(raised.value)
    assert "selector-secret" not in repr(raised.value.details)
    assert len(connection.cursor_object.calls) == 1


def test_failed_plan_uses_nested_transaction_rollback_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed multi-key plan exits through the savepoint rollback path."""

    events: list[str] = []
    connection = _Connection(results=(False, True))
    monkeypatch.setattr(subject, "connections", {connection.alias: connection})

    @contextmanager
    def atomic(*, using: str) -> Iterator[None]:
        """Record the savepoint lifecycle without opening PostgreSQL."""

        assert using == connection.alias
        events.append("enter")
        try:
            yield
        except subject.ScopedAdvisoryLockError:
            events.append("rollback")
            raise
        else:
            events.append("release")

    monkeypatch.setattr(subject.transaction, "atomic", atomic)

    with pytest.raises(subject.ScopedAdvisoryLockUnavailableError):
        subject.try_acquire_scoped_advisory_shared(
            using="lock-test", keys=(_key("authority", "a"), _key("authority", "b"))
        )

    assert events == ["enter", "rollback"]


@pytest.mark.parametrize(
    ("connection", "message"),
    (
        (_Connection(vendor="sqlite"), "require PostgreSQL"),
        (_Connection(in_atomic_block=False), "active non-autocommit transaction"),
        (_Connection(autocommit=True), "active non-autocommit transaction"),
        (_Connection(alias="other"), "does not match"),
    ),
)
def test_transaction_and_alias_validation(
    monkeypatch: pytest.MonkeyPatch, connection: _Connection, message: str
) -> None:
    """The helper rejects the wrong backend, transaction state, or alias binding."""

    monkeypatch.setattr(subject, "connections", {"lock-test": connection})

    with pytest.raises(subject.ScopedAdvisoryLockTransactionError, match=message):
        subject.try_acquire_scoped_advisory_shared(
            using="lock-test", keys=(_key("authority", "one"),)
        )


@pytest.mark.parametrize("using", ["", " lock-test", "lock-test ", True])
def test_invalid_database_alias_is_rejected_without_lookup(
    monkeypatch: pytest.MonkeyPatch, using: object
) -> None:
    """Aliases must be exact strings before the connection handler is consulted."""

    monkeypatch.setattr(subject, "connections", {})

    with pytest.raises(subject.ScopedAdvisoryLockConfigurationError, match="alias is invalid"):
        subject.try_acquire_scoped_advisory_shared(
            using=using,  # type: ignore[arg-type]
            keys=(_key("authority", "one"),),
        )


def test_database_error_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Driver failures become a typed lock error for callers to handle."""

    connection = _Connection(results=(True,))
    _bind(monkeypatch, connection)

    def fail(statement: str, params: list[int]) -> None:
        raise DatabaseError("database unavailable")

    connection.cursor_object.execute = fail

    with pytest.raises(subject.ScopedAdvisoryLockDatabaseError, match="operation is unavailable"):
        subject.try_acquire_scoped_advisory_shared(
            using="lock-test", keys=(_key("authority", "one"),)
        )
