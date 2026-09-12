"""Unit boundaries for the new-only simulated-account row writer.

These tests use a small in-memory ORM double.  The component tests own the
real PostgreSQL and Django model verification; this file focuses on alias
propagation, transaction ordering, input rejection, and savepoint behavior.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any, cast

import pytest
from django.db import DatabaseError, IntegrityError

from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowCommand,
    CanonicalAccountCreationRowConflict,
    CanonicalAccountCreationRowCorruption,
    CanonicalAccountCreationRowInvalid,
    CanonicalAccountCreationRowUnavailable,
)
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from apps.simulated_trading.infrastructure import (
    canonical_account_creation_row_writer as writer_module,
)

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
ROW_CREATED = datetime(2026, 9, 11, 11, 59, tzinfo=UTC)
ROW_UPDATED = datetime(2026, 9, 11, 12, tzinfo=UTC)


def _account(**changes: object) -> SimulatedAccount:
    values: dict[str, object] = {
        "account_id": 0,
        "account_name": "new-account",
        "account_type": AccountType.SIMULATED,
        "initial_capital": 100_000.0,
        "current_cash": 100_000.0,
        "current_market_value": 0.0,
        "total_value": 100_000.0,
        "start_date": date(2026, 9, 11),
    }
    values.update(changes)
    return SimulatedAccount(**cast(dict[str, Any], values))


def _command(**changes: object) -> CanonicalAccountCreationRowCommand:
    values: dict[str, object] = {
        "requester_user_id": 19,
        "account": _account(),
        "observation_id": "account-row-create-19",
        "mutation_version": "mutation-1",
    }
    values.update(changes)
    return CanonicalAccountCreationRowCommand(**cast(dict[str, Any], values))


class _FakeDatabase:
    def __init__(self, *, in_atomic_block: bool = True) -> None:
        self.events: list[str] = []
        self.rows: list[_FakeModel] = []
        self.next_pk = 73
        self.save_error: DatabaseError | None = None
        self.refresh_error: DatabaseError | None = None
        self.connection = _FakeConnection(self, in_atomic_block=in_atomic_block)


class _FakeConnection:
    def __init__(self, database: _FakeDatabase, *, in_atomic_block: bool) -> None:
        self._database = database
        self.in_atomic_block = in_atomic_block


class _FakeConnections:
    def __init__(self, database: _FakeDatabase, *, available_alias: str = "owner") -> None:
        self._database = database
        self._available_alias = available_alias

    def __getitem__(self, alias: str) -> _FakeConnection:
        self._database.events.append(f"connections[{alias}]")
        if alias != self._available_alias:
            raise KeyError(alias)
        return self._database.connection


class _FakeSavepoint:
    def __init__(self, database: _FakeDatabase, alias: str) -> None:
        self._database = database
        self._alias = alias
        self._row_count = 0

    def __enter__(self) -> None:
        self._database.events.append(f"savepoint.enter:{self._alias}")
        self._row_count = len(self._database.rows)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        if exc_type is not None:
            del self._database.rows[self._row_count :]
            self._database.events.append("savepoint.rollback")
        else:
            self._database.events.append("savepoint.commit")
        return False


class _FakeTransaction:
    def __init__(self, database: _FakeDatabase) -> None:
        self._database = database

    def atomic(self, *, using: str) -> _FakeSavepoint:
        return _FakeSavepoint(self._database, using)


class _FakeUser:
    def __init__(self, user_id: int = 19, *, is_active: object = True) -> None:
        self.pk = user_id
        self.is_active = is_active


class _FakeUserManager:
    def __init__(self, database: _FakeDatabase, user: _FakeUser | None) -> None:
        self._database = database
        self._user = user
        self._selected_alias: str | None = None

    def using(self, alias: str) -> _FakeUserManager:
        self._selected_alias = alias
        self._database.events.append(f"user.using:{alias}")
        return self

    def select_for_update(self) -> _FakeUserManager:
        self._database.events.append("user.select_for_update")
        return self

    def filter(self, **filters: object) -> _FakeUserManager:
        self._database.events.append("user.filter")
        assert filters == {"pk": 19}
        return self

    def first(self) -> _FakeUser | None:
        self._database.events.append("user.first")
        return self._user


class _FakeUserModel:
    def __init__(self, manager: _FakeUserManager) -> None:
        self._default_manager = manager


class _FakeModel:
    def __init__(self, database: _FakeDatabase, source: SimulatedAccount) -> None:
        self._database = database
        self._source = source
        self.pk: int | None = 0
        self.user_id: int | None = None
        self.account_type = source.account_type.value
        self.is_active = source.is_active
        self.created_at = ROW_CREATED
        self.updated_at = ROW_UPDATED

    def save(self, *, force_insert: bool, using: str) -> None:
        self._database.events.append(f"model.save:{using}")
        assert force_insert is True
        if self._database.save_error is not None:
            raise self._database.save_error
        self.pk = self._database.next_pk
        self._database.next_pk += 1
        self._database.rows.append(self)

    def refresh_from_db(self, *, using: str) -> None:
        self._database.events.append(f"model.refresh:{using}")
        if self._database.refresh_error is not None:
            raise self._database.refresh_error


class _FakeMapper:
    database: _FakeDatabase

    @classmethod
    def to_model(cls, account: SimulatedAccount) -> _FakeModel:
        cls.database.events.append("mapper.to_model")
        return _FakeModel(cls.database, account)

    @staticmethod
    def to_entity(model: _FakeModel) -> SimulatedAccount:
        model._database.events.append("mapper.to_entity")
        return replace(model._source, account_id=cast(int, model.pk))


class _FakeClock:
    def __init__(self, database: _FakeDatabase, value: datetime = NOW) -> None:
        self._database = database
        self.value = value

    def now(self) -> datetime:
        self._database.events.append("clock.now")
        return self.value


class _FailingClock:
    def now(self) -> datetime:
        raise RuntimeError("sensitive clock implementation detail")


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    user: _FakeUser | None = _FakeUser(),
    in_atomic_block: bool = True,
    clock: object | None = None,
) -> tuple[writer_module.DjangoCanonicalAccountCreationRowWriter, _FakeDatabase]:
    database = _FakeDatabase(in_atomic_block=in_atomic_block)
    manager = _FakeUserManager(database, user)
    monkeypatch.setattr(
        writer_module,
        "connections",
        _FakeConnections(database),
    )
    monkeypatch.setattr(
        writer_module,
        "transaction",
        _FakeTransaction(database),
    )
    monkeypatch.setattr(writer_module, "get_user_model", lambda: _FakeUserModel(manager))
    _FakeMapper.database = database
    monkeypatch.setattr(writer_module, "SimulatedAccountMapper", _FakeMapper)
    selected_clock = clock if clock is not None else _FakeClock(database)
    return (
        writer_module.DjangoCanonicalAccountCreationRowWriter(
            using="owner", clock=cast(Any, selected_clock)
        ),
        database,
    )


def test_execute_propagates_alias_locks_active_user_and_refreshes_real_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, database = _install(monkeypatch)

    writer.execute(_command())

    assert database.events == [
        "connections[owner]",
        "savepoint.enter:owner",
        "user.using:owner",
        "user.select_for_update",
        "user.filter",
        "user.first",
        "mapper.to_model",
        "model.save:owner",
        "model.refresh:owner",
        "clock.now",
        "mapper.to_entity",
        "savepoint.commit",
    ]


def test_execute_returns_account_and_mutation_for_new_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, database = _install(monkeypatch)

    result = writer.execute(_command())

    assert result.account.account_id == 73
    assert result.account.account_type is AccountType.SIMULATED
    assert result.account.is_active is True
    assert result.mutation.row_pk == 73
    assert result.mutation.row_user_id == 19
    assert result.mutation.raw_account_type == "simulated"
    assert result.mutation.is_active is True
    assert result.mutation.row_created_at == ROW_CREATED
    assert result.mutation.row_updated_at == ROW_UPDATED
    assert result.mutation.observed_at == NOW
    assert len(database.rows) == 1


def test_execute_requires_caller_owned_transaction_without_touching_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, database = _install(monkeypatch, in_atomic_block=False)

    with pytest.raises(CanonicalAccountCreationRowUnavailable, match="caller-owned"):
        writer.execute(_command())

    assert database.events == ["connections[owner]"]
    assert database.rows == []


@pytest.mark.parametrize("using", [None, True, 0, "", " ", " owner", "owner ", "owner alias"])
def test_writer_rejects_invalid_alias_before_database_lookup(
    monkeypatch: pytest.MonkeyPatch,
    using: object,
) -> None:
    database = _FakeDatabase()
    monkeypatch.setattr(writer_module, "connections", _FakeConnections(database))

    with pytest.raises(CanonicalAccountCreationRowInvalid, match="database alias"):
        writer_module.DjangoCanonicalAccountCreationRowWriter(using=cast(str, using))

    assert database.events == []


def test_command_rejects_existing_account_id_as_new_only_conflict() -> None:
    with pytest.raises(CanonicalAccountCreationRowConflict, match="existing account_id"):
        _command(account=_account(account_id=7))


@pytest.mark.parametrize("requester_user_id", [True, 0, -1])
def test_command_rejects_non_positive_or_boolean_requester(
    requester_user_id: object,
) -> None:
    with pytest.raises(CanonicalAccountCreationRowInvalid, match="requester_user_id"):
        _command(requester_user_id=requester_user_id)


def test_command_maps_huge_integer_to_stable_invalid_error() -> None:
    with pytest.raises(CanonicalAccountCreationRowInvalid, match="initial_capital"):
        _command(account=_account(initial_capital=10**1000))


def test_inactive_locked_user_is_rejected_before_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, database = _install(monkeypatch, user=_FakeUser(is_active=False))

    with pytest.raises(CanonicalAccountCreationRowUnavailable, match="requester user"):
        writer.execute(_command())

    assert database.rows == []
    assert database.events[-1] == "savepoint.rollback"
    assert "mapper.to_model" not in database.events


@pytest.mark.parametrize(
    ("database_error", "expected_error", "message"),
    [
        (IntegrityError("duplicate row"), CanonicalAccountCreationRowConflict, "conflicted"),
        (
            DatabaseError("database down"),
            CanonicalAccountCreationRowUnavailable,
            "cannot be inserted",
        ),
    ],
)
def test_insert_database_errors_are_typed_and_savepoint_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    database_error: DatabaseError,
    expected_error: type[Exception],
    message: str,
) -> None:
    writer, database = _install(monkeypatch)
    database.save_error = database_error

    with pytest.raises(expected_error, match=message):
        writer.execute(_command())

    assert database.rows == []
    assert database.events[-1] == "savepoint.rollback"


def test_refresh_database_error_is_unavailable_and_savepoint_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, database = _install(monkeypatch)
    database.refresh_error = DatabaseError("database down")

    with pytest.raises(CanonicalAccountCreationRowUnavailable, match="refreshed"):
        writer.execute(_command())

    assert database.rows == []
    assert database.events[-1] == "savepoint.rollback"


@pytest.mark.parametrize("user", [None, _FakeUser(user_id=20), _FakeUser(is_active=1)])
def test_missing_or_malformed_user_is_rejected_and_savepoint_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    user: _FakeUser | None,
) -> None:
    writer, database = _install(monkeypatch, user=user)

    with pytest.raises(CanonicalAccountCreationRowUnavailable, match="requester user"):
        writer.execute(_command())

    assert database.rows == []
    assert database.events[-1] == "savepoint.rollback"


def test_clock_exception_is_redacted_and_savepoint_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, database = _install(monkeypatch, clock=_FailingClock())

    with pytest.raises(CanonicalAccountCreationRowCorruption, match="server clock") as error:
        writer.execute(_command())

    assert "sensitive" not in str(error.value)
    assert database.rows == []
    assert database.events[-1] == "savepoint.rollback"


def test_clock_before_database_timestamps_is_corruption_with_no_half_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, database = _install(
        monkeypatch,
        clock=None,
    )
    clock = _FakeClock(database, value=ROW_CREATED)
    writer = writer_module.DjangoCanonicalAccountCreationRowWriter(using="owner", clock=clock)

    with pytest.raises(CanonicalAccountCreationRowCorruption, match="physical-row mutation"):
        writer.execute(_command())

    assert database.rows == []
    assert database.events[-1] == "savepoint.rollback"


def test_refreshed_account_scope_mismatch_is_corruption_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, database = _install(monkeypatch)

    original_mapper = writer_module.SimulatedAccountMapper

    class _MismatchingMapper:
        @staticmethod
        def to_model(account: SimulatedAccount) -> _FakeModel:
            return original_mapper.to_model(account)

        @staticmethod
        def to_entity(model: _FakeModel) -> SimulatedAccount:
            return replace(original_mapper.to_entity(model), account_id=999)

    monkeypatch.setattr(writer_module, "SimulatedAccountMapper", _MismatchingMapper)

    with pytest.raises(CanonicalAccountCreationRowCorruption, match="correspond"):
        writer.execute(_command())

    assert database.rows == []
    assert database.events[-1] == "savepoint.rollback"
