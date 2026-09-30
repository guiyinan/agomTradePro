"""Read-only owner adapter exposing raw-bound source-v2 rows to Account."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from threading import get_ident
from typing import cast

from django.db import DatabaseError, connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.physical_account_row_observation_v2 import (
    ExactPhysicalSimulatedAccountRowV2,
    PhysicalAccountRowObservationV2Corruption,
    PhysicalAccountRowObservationV2Unavailable,
    PhysicalAccountRowProviderIdentity,
    PhysicalAccountRowProviderReadClock,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
    SimulatedAccountRowSourceV2Conflict,
    SimulatedAccountRowSourceV2Corruption,
    SimulatedAccountRowSourceV2Repository,
    SimulatedAccountRowSourceV2Unavailable,
)


class DjangoExactPhysicalSimulatedAccountRowV2Provider:
    """Expose one exact logical-final source-v2 revision without rewriting it."""

    __slots__ = (
        "_identity",
        "_read_clock",
        "_read_clock_cutoff",
        "_repository",
        "_using",
    )

    def __init__(self, repository: SimulatedAccountRowSourceV2Repository) -> None:
        self._repository = repository
        using = getattr(repository, "database_alias", None)
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("physical row repository must expose its exact database alias")
        self._using = using
        self._identity: PhysicalAccountRowProviderIdentity | None = None
        self._read_clock: PhysicalAccountRowProviderReadClock | None = None
        self._read_clock_cutoff: datetime | None = None

    @property
    def unit_of_work_key(self) -> str:
        """Return the repository transaction identity."""

        return self._repository.unit_of_work_key

    @property
    def database_alias(self) -> str:
        """Return the concrete repository alias used by all source reads."""

        return self._using

    @contextmanager
    def bind_physical_identity(
        self,
        identity: PhysicalAccountRowProviderIdentity,
    ) -> Iterator[None]:
        """Bind one verified identity and reject any connection drift on exit."""

        if type(identity) is not PhysicalAccountRowProviderIdentity:
            raise TypeError("identity must be an exact PhysicalAccountRowProviderIdentity")
        if self._identity is not None:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider identity scope cannot be nested"
            )
        self._assert_identity(identity)
        self._identity = identity
        try:
            yield
            self._assert_identity(identity)
        finally:
            self._identity = None

    @contextmanager
    def bind_read_clock(
        self,
        clock: PhysicalAccountRowProviderReadClock,
    ) -> Iterator[None]:
        """Bind one aware cutoff and reject nested or drifting clock scopes."""

        if self._read_clock is not None:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider read clock scope cannot be nested"
            )
        cutoff = _read_clock_value(clock)
        self._read_clock = clock
        self._read_clock_cutoff = cutoff
        try:
            yield
            self._assert_read_clock()
        finally:
            self._read_clock = None
            self._read_clock_cutoff = None

    def lock_current_sources(self) -> None:
        """Exclusively stabilize the provider-owned source ledger for mutation."""

        with self._verified_operation():
            try:
                self._repository.lock_current_sources()
            except SimulatedAccountRowSourceV2Unavailable as error:
                raise PhysicalAccountRowObservationV2Unavailable(
                    "source-v2 ledger cannot be stabilized"
                ) from error

    def lock_current_sources_for_read(self) -> None:
        """Stabilize the provider source while allowing concurrent readers."""

        with self._verified_operation():
            try:
                self._repository.lock_current_sources_for_read()
            except SimulatedAccountRowSourceV2Unavailable as error:
                raise PhysicalAccountRowObservationV2Unavailable(
                    "source-v2 ledger cannot be stabilized"
                ) from error

    def get_exact_final(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> ExactPhysicalSimulatedAccountRowV2 | None:
        """Return an exact recorded and unexpired final, including tombstones."""

        with self._verified_operation():
            record = self._read_final(
                source_id=source_id,
                source_version=source_version,
                expected_content_hash=expected_content_hash,
                account_namespace=account_namespace,
                account_id=account_id,
                underlying_unified_account_namespace=underlying_unified_account_namespace,
                underlying_unified_account_id=underlying_unified_account_id,
                as_of=as_of,
            )
        if record is None or not record.source.is_knowable_at(as_of):
            return None
        return self._map(record)

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> ExactPhysicalSimulatedAccountRowV2 | None:
        """Return an exact final only while it is also a live source revision."""

        with self._verified_operation():
            record = self._read_final(
                source_id=source_id,
                source_version=source_version,
                expected_content_hash=expected_content_hash,
                account_namespace=account_namespace,
                account_id=account_id,
                underlying_unified_account_namespace=underlying_unified_account_namespace,
                underlying_unified_account_id=underlying_unified_account_id,
                as_of=as_of,
            )
        if record is None or not record.source.is_current_at(as_of):
            return None
        return self._map(record)

    @contextmanager
    def _verified_operation(self) -> Iterator[None]:
        """Check an active identity before and after one provider operation."""

        identity = self._identity
        if identity is not None:
            self._assert_identity(identity)
            if self._read_clock is None:
                raise PhysicalAccountRowObservationV2Unavailable(
                    "physical row provider read clock is not bound"
                )
        if self._read_clock is not None:
            self._assert_read_clock()
        try:
            yield
        finally:
            if self._read_clock is not None:
                self._assert_read_clock()
            if identity is not None:
                self._assert_identity(identity)

    def _assert_read_clock(self) -> None:
        """Require that the bound provider clock still returns its original cutoff."""

        clock = self._read_clock
        cutoff = self._read_clock_cutoff
        if clock is None or cutoff is None:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider read clock is not bound"
            )
        if _read_clock_value(clock) != cutoff:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider read clock drifted"
            )

    def _assert_identity(self, identity: PhysicalAccountRowProviderIdentity) -> None:
        """Require the repository and current Django connection to match identity."""

        repository_alias = getattr(self._repository, "database_alias", None)
        if repository_alias != self._using:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row repository database alias changed"
            )
        if identity.using != self._using:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider database alias differs from the bound identity"
            )
        if identity.thread_id != get_ident() or identity.task_token is not _current_task():
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider execution context changed"
            )
        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, DatabaseError, KeyError) as error:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider database alias is unavailable"
            ) from error
        if getattr(connection, "alias", None) != self._using:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider Django alias changed"
            )
        if connection is not identity.wrapper_token:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider Django connection wrapper changed"
            )
        if getattr(connection, "connection", None) is not identity.dbapi_token:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider physical connection changed"
            )
        if connection.vendor != "postgresql" or not connection.in_atomic_block:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider requires an active PostgreSQL transaction"
            )
        if connection.get_autocommit():
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider transaction became autocommit"
            )
        transaction_xid, backend_pid = _read_transaction_identity(connection)
        if transaction_xid != identity.transaction_xid or backend_pid != identity.backend_pid:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider transaction identity changed"
            )

    def _read_final(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
        authoritative_cutoff = self._authoritative_cutoff(as_of)
        try:
            if authoritative_cutoff is None:
                winner = self._repository.get_winner(
                    source_id=source_id,
                    source_version=source_version,
                    as_of=as_of,
                )
            else:
                winner = self._repository.get_winner(
                    source_id=source_id,
                    source_version=source_version,
                    as_of=as_of,
                    authoritative_cutoff=authoritative_cutoff,
                )
            if winner is None:
                return None
            if authoritative_cutoff is None:
                head = self._repository.get_current_head(
                    source_id=source_id,
                    account_namespace=account_namespace,
                    account_id=account_id,
                    underlying_unified_account_namespace=underlying_unified_account_namespace,
                    underlying_unified_account_id=underlying_unified_account_id,
                    as_of=as_of,
                )
            else:
                head = self._repository.get_current_head(
                    source_id=source_id,
                    account_namespace=account_namespace,
                    account_id=account_id,
                    underlying_unified_account_namespace=underlying_unified_account_namespace,
                    underlying_unified_account_id=underlying_unified_account_id,
                    as_of=as_of,
                    authoritative_cutoff=authoritative_cutoff,
                )
        except SimulatedAccountRowSourceV2Unavailable:
            return None
        except (
            SimulatedAccountRowSourceV2Conflict,
            SimulatedAccountRowSourceV2Corruption,
        ) as error:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 ledger failed closed-world verification"
            ) from error

        checked_winner = self._require_record(winner)
        if head is None:
            return None
        checked_head = self._require_record(head)
        if checked_head != checked_winner:
            return None
        source = checked_winner.source
        selectors = (
            source.source_id,
            source.source_version,
            source.content_hash,
            source.account_namespace,
            source.account_id,
            source.underlying_unified_account_namespace,
            source.underlying_unified_account_id,
        )
        expected = (
            source_id,
            source_version,
            expected_content_hash,
            account_namespace,
            account_id,
            underlying_unified_account_namespace,
            underlying_unified_account_id,
        )
        if selectors != expected:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 ledger selector substitution"
            )
        return checked_winner

    def _authoritative_cutoff(self, as_of: datetime) -> datetime | None:
        """Return the bound cutoff and reject future or unbound identity reads."""

        if self._read_clock is None:
            if self._identity is not None:
                raise PhysicalAccountRowObservationV2Unavailable(
                    "physical row provider read clock is not bound"
                )
            return None
        self._assert_read_clock()
        if type(as_of) is not datetime or not _is_aware(as_of):
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider as_of must be one aware datetime"
            )
        cutoff = self._read_clock_cutoff
        if cutoff is None:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider read clock is not bound"
            )
        if as_of > cutoff:
            raise PhysicalAccountRowObservationV2Unavailable(
                "physical row provider as_of exceeds its bound read cutoff"
            )
        return cutoff

    @staticmethod
    def _require_record(value: object) -> PersistedSimulatedAccountRowSourceV2:
        if type(value) is not PersistedSimulatedAccountRowSourceV2:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 ledger record type substitution"
            )
        try:
            PersistedSimulatedAccountRowSourceV2.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 ledger returned an invalid record"
            ) from error
        return value

    @staticmethod
    def _map(
        record: PersistedSimulatedAccountRowSourceV2,
    ) -> ExactPhysicalSimulatedAccountRowV2:
        source = record.source
        try:
            return ExactPhysicalSimulatedAccountRowV2(
                source_id=source.source_id,
                source_version=source.source_version,
                identity_hash=source.identity_hash,
                content_hash=source.content_hash,
                source_supersedes_content_hash=source.supersedes_content_hash,
                account_namespace=source.account_namespace,
                account_id=source.account_id,
                underlying_unified_account_namespace=(source.underlying_unified_account_namespace),
                underlying_unified_account_id=source.underlying_unified_account_id,
                row_user_id=source.row_user_id,
                raw_account_type=source.raw_account_type,
                is_active=source.is_active,
                row_created_at=source.row_created_at,
                row_updated_at=source.row_updated_at,
                is_present=source.is_present,
                is_tombstone=source.is_tombstone,
                observed_at=source.observed_at,
                recorded_at=source.recorded_at,
                source_valid_until=source.source_valid_until,
                ttl_valid_until=source.ttl_valid_until,
                valid_until=source.valid_until,
                raw_observation_id=source.raw_observation_id,
                raw_observation_version=source.raw_observation_version,
                raw_observation_identity_hash=source.raw_observation_identity_hash,
                raw_observation_content_hash=source.raw_observation_content_hash,
                raw_observation_supersedes_content_hash=(
                    source.raw_observation_supersedes_content_hash
                ),
                raw_observation_observed_at=source.raw_observation_observed_at,
                raw_observation_valid_until=source.raw_observation_valid_until,
                owner_assignment_state=source.owner_assignment_state,
                owner=source.owner,
                artifact_type=source.artifact_type,
                schema=source.schema,
                raw_observation_owner=source.raw_observation_owner,
                raw_observation_artifact_type=source.raw_observation_artifact_type,
                raw_observation_schema=source.raw_observation_schema,
            )
        except (TypeError, ValueError) as error:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 fields cannot be mapped without rewriting"
            ) from error


def _read_transaction_identity(connection: BaseDatabaseWrapper) -> tuple[str, int]:
    """Read PostgreSQL xid and backend PID on the exact Django connection."""

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_current_xact_id()::text, pg_backend_pid()")
            row = cast(tuple[object, ...] | None, cursor.fetchone())
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise PhysicalAccountRowObservationV2Unavailable(
            "physical row provider transaction identity is unavailable"
        ) from error
    if (
        row is None
        or len(row) != 2
        or type(row[0]) is not str
        or not row[0]
        or type(row[1]) is not int
        or row[1] <= 0
    ):
        raise PhysicalAccountRowObservationV2Unavailable(
            "physical row provider transaction identity is invalid"
        )
    return row[0], row[1]


def _current_task() -> object | None:
    """Return the current asyncio task for synchronous and async callers."""

    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


def _read_clock_value(clock: PhysicalAccountRowProviderReadClock) -> datetime:
    """Read and validate one exact aware datetime from a provider clock."""

    now = getattr(clock, "now", None)
    if not callable(now):
        raise PhysicalAccountRowObservationV2Unavailable(
            "physical row provider read clock must expose now"
        )
    try:
        value = now()
    except (AttributeError, RuntimeError, TypeError, ValueError) as error:
        raise PhysicalAccountRowObservationV2Unavailable(
            "physical row provider read clock is unavailable"
        ) from error
    if type(value) is not datetime or not _is_aware(value):
        raise PhysicalAccountRowObservationV2Unavailable(
            "physical row provider read clock must return one aware datetime"
        )
    return value


def _is_aware(value: datetime) -> bool:
    """Return whether a datetime carries a usable UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = ["DjangoExactPhysicalSimulatedAccountRowV2Provider"]
