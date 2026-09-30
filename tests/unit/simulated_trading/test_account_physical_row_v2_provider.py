from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import get_ident
from typing import cast

import pytest

from apps.account.application.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2Corruption,
    PhysicalAccountRowObservationV2Unavailable,
    PhysicalAccountRowProviderIdentity,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
    SimulatedAccountRowSourceV2Conflict,
    SimulatedAccountRowSourceV2Corruption,
    SimulatedAccountRowSourceV2Unavailable,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from apps.simulated_trading.infrastructure import (
    account_physical_row_v2_provider as provider_module,
)
from apps.simulated_trading.infrastructure.account_physical_row_v2_provider import (
    DjangoExactPhysicalSimulatedAccountRowV2Provider,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def _raw(**changes: object) -> SimulatedAccountRawObservation:
    values: dict[str, object] = {
        "observation_id": "simulated-account-row-7",
        "observation_version": "event-v1",
        "row_pk": 7,
        "row_user_id": 42,
        "raw_account_type": "PAPER",
        "is_active": True,
        "row_created_at": NOW - timedelta(days=20),
        "row_updated_at": NOW - timedelta(hours=2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": NOW - timedelta(hours=1),
        "valid_until": NOW + timedelta(days=2),
    }
    values.update(changes)
    return SimulatedAccountRawObservation(**values)  # type: ignore[arg-type]


def _record(**changes: object) -> PersistedSimulatedAccountRowSourceV2:
    raw = cast(SimulatedAccountRawObservation | None, changes.pop("raw", None)) or _raw()
    values: dict[str, object] = {
        "source_id": raw.observation_id,
        "source_version": raw.observation_version,
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": raw.row_pk,
        "row_user_id": raw.row_user_id,
        "raw_account_type": raw.raw_account_type,
        "is_active": raw.is_active,
        "row_created_at": raw.row_created_at,
        "row_updated_at": raw.row_updated_at,
        "is_present": raw.is_present,
        "is_tombstone": raw.is_tombstone,
        "observed_at": raw.observed_at,
        "recorded_at": NOW - timedelta(minutes=30),
        "source_valid_until": raw.valid_until,
        "ttl_valid_until": NOW + timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "raw_observation_id": raw.observation_id,
        "raw_observation_version": raw.observation_version,
        "raw_observation_identity_hash": raw.identity_hash,
        "raw_observation_content_hash": raw.content_hash,
        "raw_observation_observed_at": raw.observed_at,
        "raw_observation_valid_until": raw.valid_until,
        "raw_observation_supersedes_content_hash": raw.supersedes_content_hash,
    }
    values.update(changes)
    return PersistedSimulatedAccountRowSourceV2(
        SimulatedAccountRowSourceV2(**values)  # type: ignore[arg-type]
    )


class _Repository:
    def __init__(
        self,
        *,
        database_alias: str = "default",
        winner: PersistedSimulatedAccountRowSourceV2 | None = None,
        head: PersistedSimulatedAccountRowSourceV2 | None = None,
        error: ValueError | None = None,
    ) -> None:
        self.database_alias = database_alias
        self.winner = winner
        self.head = head
        self.error = error
        self.winner_calls: list[tuple[str, str, datetime]] = []
        self.head_calls: list[tuple[object, ...]] = []
        self.lock_calls = 0
        self.read_lock_calls = 0

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self.database_alias}"

    def lock_current_sources(self) -> None:
        self.lock_calls += 1
        if self.error is not None:
            raise self.error

    def lock_current_sources_for_read(self) -> None:
        self.read_lock_calls += 1
        if self.error is not None:
            raise self.error

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
        self.winner_calls.append((source_id, source_version, as_of))
        if self.error is not None:
            raise self.error
        return self.winner

    def get_current_head(self, **kwargs: object) -> PersistedSimulatedAccountRowSourceV2 | None:
        self.head_calls.append(tuple(kwargs.values()))
        return self.head

    def atomic(self) -> object:
        raise AssertionError("read-only provider must not open a write UOW")

    def now(self) -> datetime:
        raise AssertionError("read-only provider must not fabricate a clock")

    def append(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("read-only provider must not append")

    def get_exact_by_hash(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("provider must use winner plus full logical head")


class _IdentityCursor:
    def __init__(self, connection: _IdentityConnection) -> None:
        self._connection = connection

    def __enter__(self) -> _IdentityCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        del statement

    def fetchone(self) -> tuple[str, int]:
        return self._connection.transaction_xid, self._connection.backend_pid


class _IdentityConnection:
    def __init__(self, *, alias: str = "default") -> None:
        self.alias = alias
        self.vendor = "postgresql"
        self.in_atomic_block = True
        self.autocommit = False
        self.connection = object()
        self.transaction_xid = "41"
        self.backend_pid = 1234

    def get_autocommit(self) -> bool:
        return self.autocommit

    def cursor(self) -> _IdentityCursor:
        return _IdentityCursor(self)


def _identity(
    connection: _IdentityConnection,
    *,
    using: str = "default",
) -> PhysicalAccountRowProviderIdentity:
    return PhysicalAccountRowProviderIdentity(
        using=using,
        wrapper_token=connection,
        dbapi_token=connection.connection,
        backend_pid=connection.backend_pid,
        transaction_xid=connection.transaction_xid,
        thread_id=get_ident(),
        task_token=provider_module._current_task(),
    )


def _read(
    repository: _Repository,
    *,
    record: PersistedSimulatedAccountRowSourceV2 | None = None,
    current: bool = False,
    as_of: datetime = NOW,
):
    expected = record or _record()
    method = (
        DjangoExactPhysicalSimulatedAccountRowV2Provider(repository).get_exact_current
        if current
        else DjangoExactPhysicalSimulatedAccountRowV2Provider(repository).get_exact_final
    )
    source = expected.source
    return method(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
        account_namespace=source.account_namespace,
        account_id=source.account_id,
        underlying_unified_account_namespace=source.underlying_unified_account_namespace,
        underlying_unified_account_id=source.underlying_unified_account_id,
        as_of=as_of,
    )


def test_provider_exposes_same_uow_and_delegates_current_source_lock() -> None:
    repository = _Repository()
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(repository)

    assert provider.unit_of_work_key == "django:default"
    provider.lock_current_sources()

    assert repository.lock_calls == 1


def test_provider_delegates_concurrent_read_source_lock() -> None:
    repository = _Repository()
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(repository)

    provider.lock_current_sources_for_read()

    assert repository.read_lock_calls == 1


def test_bound_provider_reads_only_on_exact_wrapper_connection_pid_and_xid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _IdentityConnection()
    monkeypatch.setattr(provider_module, "connections", {"default": connection})
    record = _record()
    source = record.source
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(
        _Repository(winner=record, head=record)
    )

    with provider.bind_physical_identity(_identity(connection)):
        value = provider.get_exact_final(
            source_id=source.source_id,
            source_version=source.source_version,
            expected_content_hash=source.content_hash,
            account_namespace=source.account_namespace,
            account_id=source.account_id,
            underlying_unified_account_namespace=source.underlying_unified_account_namespace,
            underlying_unified_account_id=source.underlying_unified_account_id,
            as_of=NOW,
        )

    assert value is not None


def test_bound_provider_rejects_cross_alias_and_different_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _IdentityConnection()
    other = _IdentityConnection(alias="other")
    monkeypatch.setattr(provider_module, "connections", {"default": connection})
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(_Repository())

    with pytest.raises(PhysicalAccountRowObservationV2Unavailable, match="alias"):
        with provider.bind_physical_identity(_identity(other, using="other")):
            pass

    with pytest.raises(PhysicalAccountRowObservationV2Unavailable, match="wrapper"):
        with provider.bind_physical_identity(_identity(other)):
            pass


@pytest.mark.parametrize(
    ("changed", "message"),
    (
        ("connection", "physical connection"),
        ("backend_pid", "transaction identity"),
        ("transaction_xid", "transaction identity"),
    ),
)
def test_bound_provider_rejects_reconnect_pid_and_xid_drift(
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
    message: str,
) -> None:
    connection = _IdentityConnection()
    monkeypatch.setattr(provider_module, "connections", {"default": connection})
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(_Repository())
    original = getattr(connection, changed)

    with provider.bind_physical_identity(_identity(connection)):
        setattr(connection, changed, object() if changed == "connection" else "42")
        with pytest.raises(PhysicalAccountRowObservationV2Unavailable, match=message):
            provider.lock_current_sources_for_read()
        setattr(connection, changed, original)


def test_bound_provider_rejects_inherited_identity_in_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _IdentityConnection()
    monkeypatch.setattr(provider_module, "connections", {"default": connection})
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(_Repository())

    with provider.bind_physical_identity(_identity(connection)):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(provider.lock_current_sources_for_read)
            with pytest.raises(PhysicalAccountRowObservationV2Unavailable, match="context"):
                future.result()


def test_bound_provider_rejects_inherited_identity_in_child_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _IdentityConnection()
    monkeypatch.setattr(provider_module, "connections", {"default": connection})
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(_Repository())

    async def child() -> None:
        with pytest.raises(PhysicalAccountRowObservationV2Unavailable, match="context"):
            provider.lock_current_sources_for_read()

    async def parent() -> None:
        with provider.bind_physical_identity(_identity(connection)):
            await asyncio.create_task(child())

    asyncio.run(parent())


def test_provider_maps_source_lock_unavailability_to_account_boundary() -> None:
    repository = _Repository(error=SimulatedAccountRowSourceV2Unavailable("busy"))
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(repository)

    with pytest.raises(PhysicalAccountRowObservationV2Unavailable, match="stabilized"):
        provider.lock_current_sources()

    with pytest.raises(PhysicalAccountRowObservationV2Unavailable, match="stabilized"):
        provider.lock_current_sources_for_read()


def test_zero_rows_returns_none_without_reading_a_logical_head() -> None:
    repository = _Repository()
    assert _read(repository) is None
    assert repository.head_calls == []


def test_exact_winner_and_full_logical_head_maps_all_source_and_raw_seals() -> None:
    record = _record()
    repository = _Repository(winner=record, head=record)
    value = _read(repository, record=record)
    assert value is not None
    source = record.source
    assert (
        value.source_id,
        value.source_version,
        value.identity_hash,
        value.content_hash,
        value.source_supersedes_content_hash,
        value.recorded_at,
        value.source_valid_until,
        value.ttl_valid_until,
        value.valid_until,
    ) == (
        source.source_id,
        source.source_version,
        source.identity_hash,
        source.content_hash,
        source.supersedes_content_hash,
        source.recorded_at,
        source.source_valid_until,
        source.ttl_valid_until,
        source.valid_until,
    )
    assert (
        value.raw_observation_id,
        value.raw_observation_version,
        value.raw_observation_identity_hash,
        value.raw_observation_content_hash,
        value.raw_observation_supersedes_content_hash,
        value.raw_observation_observed_at,
        value.raw_observation_valid_until,
    ) == (
        source.raw_observation_id,
        source.raw_observation_version,
        source.raw_observation_identity_hash,
        source.raw_observation_content_hash,
        source.raw_observation_supersedes_content_hash,
        source.raw_observation_observed_at,
        source.raw_observation_valid_until,
    )
    assert repository.head_calls == [
        (
            source.source_id,
            source.account_namespace,
            source.account_id,
            source.underlying_unified_account_namespace,
            source.underlying_unified_account_id,
            NOW,
        )
    ]


def test_final_allows_terminal_tombstone_but_current_does_not() -> None:
    raw = _raw(is_active=False, is_present=False, is_tombstone=True)
    record = _record(raw=raw, is_active=False, is_present=False, is_tombstone=True)
    repository = _Repository(winner=record, head=record)
    assert _read(repository, record=record) is not None
    assert _read(repository, record=record, current=True) is None


def test_superseded_missing_and_expired_final_return_none_without_fallback() -> None:
    record = _record()
    other = _record(account_id="0008")
    assert _read(_Repository(winner=record, head=other), record=record) is None
    assert _read(_Repository(winner=record, head=None), record=record) is None
    assert (
        _read(
            _Repository(winner=record, head=record), record=record, as_of=record.source.valid_until
        )
        is None
    )


def test_selector_substitution_fails_closed_in_account_taxonomy() -> None:
    record = _record(account_id="0008")
    expected = _record()
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(
        _Repository(winner=record, head=record)
    )
    with pytest.raises(PhysicalAccountRowObservationV2Corruption, match="selector"):
        provider.get_exact_final(
            source_id=expected.source.source_id,
            source_version=expected.source.source_version,
            expected_content_hash=record.source.content_hash,
            account_namespace=expected.source.account_namespace,
            account_id=expected.source.account_id,
            underlying_unified_account_namespace=(
                expected.source.underlying_unified_account_namespace
            ),
            underlying_unified_account_id=expected.source.underlying_unified_account_id,
            as_of=NOW,
        )


def test_record_type_substitution_fails_closed() -> None:
    invalid = cast(PersistedSimulatedAccountRowSourceV2, {})
    with pytest.raises(PhysicalAccountRowObservationV2Corruption, match="record type"):
        _read(_Repository(winner=invalid, head=invalid))


@pytest.mark.parametrize(
    "error",
    [
        SimulatedAccountRowSourceV2Conflict("ambiguous head"),
        SimulatedAccountRowSourceV2Corruption("bad ledger seal"),
    ],
)
def test_source_closed_world_failures_translate_to_account_corruption(error: ValueError) -> None:
    with pytest.raises(PhysicalAccountRowObservationV2Corruption, match="closed-world"):
        _read(_Repository(error=error))


def test_unavailable_cutoff_and_composition_remain_read_only() -> None:
    assert _read(_Repository(error=SimulatedAccountRowSourceV2Unavailable("future"))) is None
    provider_source = Path(
        "apps/simulated_trading/infrastructure/account_physical_row_v2_provider.py"
    ).read_text(encoding="utf-8")
    composition_source = Path(
        "apps/simulated_trading/account_physical_row_v2_composition.py"
    ).read_text(encoding="utf-8")
    assert ".atomic(" not in provider_source
    assert ".append(" not in provider_source
    assert "CapturePhysicalAccountRowObservationV2" not in composition_source
    assert "CaptureSimulatedAccountRowSourceV2" not in composition_source
