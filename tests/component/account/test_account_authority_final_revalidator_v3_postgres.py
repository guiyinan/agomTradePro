"""PostgreSQL contracts for the disconnected Authority V3 final-check slice."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timedelta
from queue import Queue
from threading import Event
from typing import cast

import pytest
from django.db import close_old_connections, connections, transaction

from apps.account.application.account_authority_final_revalidation_v3_contracts import (
    AccountAuthorityV3FinalRootSelection,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PhysicalAccountRowProviderIdentity,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
    _canonical_hash,
)
from apps.account.infrastructure.account_authority_final_revalidation_v3_repository import (
    DjangoAccountAuthorityV3RootRevocationRevalidationRepository,
)
from apps.account.infrastructure.account_authority_final_revalidator_v3 import (
    AccountAuthorityCompleteGraphFinalRevalidationProofV3,
    AccountAuthorityFinalRevalidationProofV3,
    AccountAuthorityFinalRevalidationUnavailable,
    AccountAuthorityFinalRevalidatorV3,
    AccountAuthorityV3CompleteGraphRevalidationResult,
    AccountAuthorityV3RootRevocationRevalidationResult,
)
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationChanged,
    capture_account_authority_snapshot_physical_provider_identity,
    capture_active_account_authority_physical_provider_identity,
    read_account_authority_generation_proof,
    verify_account_authority_generation_coverage,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityCurrentGraphReadV3,
    AccountAuthorityCurrentGraphSelectorV3,
    AccountAuthorityShadowScanResultV3,
    AccountAuthorityV3CallerTransactionMode,
    _AuthorityGraphFrozenClock,
    _compare_current_observations,
    _GenerationFencedOwnerTenantAuthorityV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from tests.component.account.test_account_authority_generation_postgres import (
    _generation,
    _wait_for_lock_wait,
)
from tests.unit.account.test_account_authority_shadow_scanner import _legacy_current

pytest_plugins = ["tests.component.account.test_account_authority_generation_postgres"]

_SOURCE_TABLE = "public.account_user_authority_source_v3_anchor"


class _MemorySelectionRepository:
    """Supply one synthetic selection while PostgreSQL owns transaction fencing."""

    def __init__(self, using: str) -> None:
        current = _legacy_current()
        self.selection = AccountAuthorityV3FinalRootSelection(
            row_id=41,
            record=PersistedOwnerTenantAuthorityV3(
                authority=current.authority,
                authentication=current.authentication,
            ),
        )
        self._using = using
        self._clock = current.observed_at + timedelta(seconds=1)
        self.clock_calls = 0
        self.selected_reads = 0
        self.revocation_reads = 0

    @property
    def database_alias(self) -> str:
        """Return the cloned PostgreSQL alias used by the fake row provider."""

        return self._using

    def database_clock(self):
        """Return a fixed test clock and expose the post-fence wait point."""

        self.clock_calls += 1
        return self._clock

    def get_selected_root(
        self,
        *,
        authority_id: str,
        authority_version: str,
        expected_content_hash: str,
        as_of: object,
    ):
        """Return the sealed in-memory selection for this PostgreSQL lock test."""

        self.selected_reads += 1
        authority = self.selection.record.authority
        if (authority_id, authority_version, expected_content_hash) != (
            authority.authority_id,
            authority.authority_version,
            authority.content_hash,
        ):
            return None
        if authority.recorded_at > as_of:
            return None
        return self.selection

    def get_exact_revocation(self, *, selection: object, as_of: object) -> None:
        """Report an empty synthetic revocation slot for generation ordering."""

        self.revocation_reads += 1
        assert selection == self.selection
        assert as_of == self._clock
        return None


def _finalizer(
    using: str,
    repository: _MemorySelectionRepository,
) -> tuple[
    AccountAuthorityFinalRevalidatorV3,
    GetCurrentOwnerTenantAuthorityV3Command,
    AccountAuthorityShadowScanResultV3,
]:
    """Build a finalizer with one synthetic selection and real PG generations."""

    current = _legacy_current()
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    scan_generation = verify_account_authority_generation_coverage(using=using).generation
    scan = AccountAuthorityShadowScanResultV3(
        database_alias=using,
        proof_generation=scan_generation,
        comparison=_compare_current_observations(current, current),
    )
    return AccountAuthorityFinalRevalidatorV3(repository, using=using), command, scan


def _shift_graph_datetimes(
    value: object,
    delta: timedelta,
    remapped_hashes: dict[str, str],
) -> object:
    """Move every nested graph clock while rebuilding its immutable content seals."""

    if type(value) is datetime:
        return value + delta
    if type(value) is str:
        return remapped_hashes.get(value, value)
    if type(value) is tuple:
        return tuple(_shift_graph_datetimes(item, delta, remapped_hashes) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        updates: dict[str, object] = {}
        old_hashes: dict[str, str] = {}
        for field in fields(value):
            previous = getattr(value, field.name)
            if type(previous) is str and field.name.endswith("_hash"):
                old_hashes[field.name] = previous
                if field.name in {"identity_hash", "content_hash"}:
                    updates[field.name] = ""
                else:
                    updates[field.name] = remapped_hashes.get(previous, previous)
            else:
                updates[field.name] = _shift_graph_datetimes(
                    previous,
                    delta,
                    remapped_hashes,
                )
        shifted = object.__new__(type(value))
        for name, field_value in updates.items():
            object.__setattr__(shifted, name, field_value)
        if type(shifted) is PhysicalAccountRowObservationV2:
            object.__setattr__(
                shifted,
                "raw_observation_identity_hash",
                _canonical_hash(shifted._raw_identity_payload()),
            )
            object.__setattr__(
                shifted,
                "raw_observation_content_hash",
                _canonical_hash(shifted._raw_content_payload()),
            )
            object.__setattr__(
                shifted,
                "source_identity_hash",
                _canonical_hash(shifted._source_identity_payload()),
            )
            object.__setattr__(
                shifted,
                "source_content_hash",
                _canonical_hash(shifted._source_content_payload()),
            )
        shifted.__post_init__()
        for name, old_hash in old_hashes.items():
            new_hash = getattr(shifted, name)
            if old_hash and old_hash != new_hash and type(new_hash) is str:
                remapped_hashes[old_hash] = new_hash
        return shifted
    return value


class _PostgresCompleteGraphReader:
    """Exercise complete-read orchestration using the caller's live PG transaction."""

    def __init__(
        self,
        using: str,
        current: CurrentOwnerTenantAuthorityV3,
        selector: AccountAuthorityCurrentGraphSelectorV3,
    ) -> None:
        self._using = using
        self._current = current
        self._selector = selector
        self.read_identities: list[PhysicalAccountRowProviderIdentity] = []
        self.outer_uow_depths: list[int] = []

    @property
    def database_alias(self) -> str:
        """Return the alias bound to the complete graph test reader."""

        return self._using

    @property
    def transaction_mode(self) -> AccountAuthorityV3CallerTransactionMode:
        """Require the generation-fenced RC/RW mode used by the finalizer."""

        return "generation_fenced_read_committed_read_write"

    def selector_for(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> AccountAuthorityCurrentGraphSelectorV3:
        """Return the exact selector bound into the synthetic shadow result."""

        assert command.expected_content_hash == self._selector.authority_content_hash
        return self._selector

    def read(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        *,
        generation: int | None = None,
    ) -> AccountAuthorityCurrentGraphReadV3:
        """Read the PostgreSQL cutoff and physical identity without taking source locks."""

        assert command.expected_content_hash == self._selector.authority_content_hash
        assert type(generation) is int
        connection = connections[self._using]
        assert connection.in_atomic_block
        repository = _GenerationFencedOwnerTenantAuthorityV3Repository(
            expected_generation=generation,
            using=self._using,
            clock=_AuthorityGraphFrozenClock(self._current.observed_at),
            assignments=DjangoAccountOwnerAssignmentEvidenceV5Repository(using=self._using),
            policies=DjangoSingleOwnerAuthorityPolicyV1Repository(using=self._using),
            actors=DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=self._using),
        )
        with repository.atomic():
            self.outer_uow_depths.append(len(connection.atomic_blocks))
        with connection.cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cast(tuple[object, ...] | None, cursor.fetchone())
        if row is None or type(row[0]) is not datetime:
            raise AssertionError("complete graph PostgreSQL cutoff was not returned")
        identity = capture_active_account_authority_physical_provider_identity(
            using=self._using,
            connection=connection,
            generation=generation,
        )
        self.read_identities.append(identity)
        current = replace(self._current, observed_at=row[0])
        current.__post_init__()
        return AccountAuthorityCurrentGraphReadV3(
            checked_at=row[0],
            authority=current,
            physical_identity=identity,
        )


def _complete_finalizer(
    using: str,
) -> tuple[
    AccountAuthorityFinalRevalidatorV3,
    GetCurrentOwnerTenantAuthorityV3Command,
    AccountAuthorityShadowScanResultV3,
    _PostgresCompleteGraphReader,
]:
    """Build a current synthetic scan and a no-lock reader over one PG alias."""

    repository = DjangoAccountAuthorityV3RootRevocationRevalidationRepository(using=using)
    basis = _legacy_current()
    database_now = repository.database_clock()
    scan_basis = cast(
        CurrentOwnerTenantAuthorityV3,
        _shift_graph_datetimes(
            basis,
            database_now - timedelta(seconds=2) - basis.observed_at,
            {},
        ),
    )
    scan_basis.__post_init__()
    connection = connections[using]
    with transaction.atomic(using=using):
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        generation_proof = read_account_authority_generation_proof(using=using)
        if generation_proof.using != using:
            raise AssertionError("complete shadow proof used another alias")
        scan_identity = capture_account_authority_snapshot_physical_provider_identity(
            using=using,
            connection=connection,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cast(tuple[object, ...] | None, cursor.fetchone())
        if row is None or type(row[0]) is not datetime:
            raise AssertionError("shadow graph PostgreSQL cutoff was not returned")
    scan_current = replace(scan_basis, observed_at=row[0])
    scan_current.__post_init__()
    command = GetCurrentOwnerTenantAuthorityV3Command(
        scan_current.authority.authority_id,
        scan_current.authority.authority_version,
        scan_current.authority.content_hash,
    )
    comparison = _compare_current_observations(scan_current, scan_current)
    fingerprint = comparison.shadow
    if fingerprint is None or fingerprint.complete_graph_hash is None:
        raise AssertionError("complete shadow fingerprint was not constructed")
    selector = AccountAuthorityCurrentGraphSelectorV3(
        database_alias=using,
        authority_selector_hash=fingerprint.authority_identity_hash,
        authority_content_hash=command.expected_content_hash,
        actor_source_selector_hash=fingerprint.actor_source_identity_hash,
        actor_source_content_hash=scan_current.authentication.source_content_hash,
    )
    scan = AccountAuthorityShadowScanResultV3(
        database_alias=using,
        proof_generation=generation_proof.generation,
        comparison=comparison,
        selector=selector,
        checked_at=row[0],
        physical_identity=scan_identity,
    )
    graph_reader = _PostgresCompleteGraphReader(using, scan_current, selector)
    finalizer = AccountAuthorityFinalRevalidatorV3(
        repository,
        using=using,
        complete_graph_reader=graph_reader,
    )
    return finalizer, command, scan, graph_reader


def test_postgres_targeted_repository_uses_only_selected_root_and_revocation_queries(
    generation_alias: str,
) -> None:
    """Prove the new repository reads only exact Authority V3 row selectors."""

    repository = DjangoAccountAuthorityV3RootRevocationRevalidationRepository(
        using=generation_alias
    )
    clock = repository.database_clock()
    current = _legacy_current()
    selection = AccountAuthorityV3FinalRootSelection(
        row_id=999_999,
        record=PersistedOwnerTenantAuthorityV3(
            authority=current.authority,
            authentication=current.authentication,
        ),
    )
    statements: list[str] = []

    def collect(
        execute: Callable[..., object],
        sql: str,
        params: object,
        many: bool,
        context: object,
    ) -> object:
        statements.append(sql)
        return execute(sql, params, many, context)

    with connections[generation_alias].execute_wrapper(collect):
        assert (
            repository.get_selected_root(
                authority_id="missing-final-check-root",
                authority_version="v1",
                expected_content_hash="a" * 64,
                as_of=clock,
            )
            is None
        )
        assert repository.get_exact_revocation(selection=selection, as_of=clock) is None

    lowered_sql = "\n".join(statements).lower()
    assert "account_owner_tenant_authority_v3_ledger" in lowered_sql
    assert "account_owner_tenant_authority_v3_revocation_ledger" in lowered_sql
    assert "where" in lowered_sql
    assert "lock table" not in lowered_sql
    assert "pg_advisory" not in lowered_sql
    assert not any(
        token in lowered_sql for token in ("insert ", "update ", "delete ", "truncate ", "outbox")
    )


def test_postgres_rr_proof_rejects_a_committed_source_change_before_any_final_read(
    runtime_alias: str,
) -> None:
    """Prove the RC generation lock rejects an RR proof after one committed DML."""

    repository = _MemorySelectionRepository(runtime_alias)
    finalizer, command, scan = _finalizer(runtime_alias, repository)
    proof = finalizer.capture(command, scan)

    with connections[runtime_alias].cursor() as cursor:
        cursor.execute(f"UPDATE {_SOURCE_TABLE} SET id = id WHERE id = %s", [-1])
    statements: list[str] = []

    def collect(
        execute: Callable[..., object],
        sql: str,
        params: object,
        many: bool,
        context: object,
    ) -> object:
        statements.append(sql)
        return execute(sql, params, many, context)

    repository_reads_before = (repository.clock_calls, repository.selected_reads)
    with connections[runtime_alias].execute_wrapper(collect):
        with pytest.raises(AccountAuthorityGenerationChanged):
            with finalizer.fence(proof):
                pytest.fail("a stale generation must not yield a final result")

    assert _generation(runtime_alias) == scan.proof_generation + 1
    assert (repository.clock_calls, repository.selected_reads) == repository_reads_before
    assert all(
        statement.lstrip().split(None, 1)[0].upper() in {"SELECT", "SET", "WITH"}
        for statement in statements
    )
    lowered_sql = "\n".join(statements).lower()
    assert "lock table" not in lowered_sql
    assert "pg_advisory" not in lowered_sql
    assert not any(
        token in lowered_sql for token in ("insert ", "update ", "delete ", "truncate ", "outbox")
    )
    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="consumed"):
        with finalizer.fence(proof):
            pytest.fail("a consumed proof must not enter the final fence")


def test_postgres_generation_fence_holds_source_writer_until_final_reads_finish(
    runtime_alias: str,
) -> None:
    """Prove a real source-trigger writer waits while the RC revalidator holds its fence."""

    repository = _MemorySelectionRepository(runtime_alias)
    finalizer, command, scan = _finalizer(runtime_alias, repository)
    proof = finalizer.capture(command, scan)
    competing_alias = "account_authority_final_revalidator_writer"
    if competing_alias in connections.databases:
        raise AssertionError("test writer alias already exists")
    connections.databases[competing_alias] = deepcopy(connections[runtime_alias].settings_dict)
    writer_started = Event()
    writer_backend_pids: Queue[int] = Queue()
    fence_entered = Event()
    exit_fence = Event()
    caller_hook_ran: list[bool] = []
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            final_check = executor.submit(
                _run_final_fence_with_caller_hook,
                finalizer,
                proof,
                runtime_alias,
                fence_entered,
                exit_fence,
                caller_hook_ran,
            )
            assert fence_entered.wait(timeout=5)
            assert caller_hook_ran == [True]
            writer = executor.submit(
                _write_zero_row_source_statement,
                competing_alias,
                writer_started,
                writer_backend_pids,
            )
            assert writer_started.wait(timeout=5)
            backend_pid = writer_backend_pids.get(timeout=5)
            assert _wait_for_lock_wait(runtime_alias, backend_pid)
            assert not writer.done()
            exit_fence.set()
            result = final_check.result(timeout=10)
            assert result.generation == scan.proof_generation
            assert writer.result(timeout=10) == scan.proof_generation + 1
    finally:
        exit_fence.set()
        connections[competing_alias].close()
        del connections[competing_alias]
        connections.databases.pop(competing_alias, None)


def test_postgres_complete_fence_locks_generation_before_same_transaction_graph_reread(
    runtime_alias: str,
) -> None:
    """Prove generation is the first business lock and graph reread shares its xid."""

    finalizer, command, scan, graph_reader = _complete_finalizer(runtime_alias)
    proof = finalizer.capture_complete(command, scan)
    statements: list[str] = []

    def collect(
        execute: Callable[..., object],
        sql: str,
        params: object,
        many: bool,
        context: object,
    ) -> object:
        statements.append(sql)
        return execute(sql, params, many, context)

    with connections[runtime_alias].execute_wrapper(collect):
        with finalizer.fence_complete(proof) as result:
            assert connections[runtime_alias].in_atomic_block
            assert result.scope == "account_authority_complete_graph"
            assert result.generation == scan.proof_generation
            assert result.transaction_xid == graph_reader.read_identities[-1].transaction_xid
            assert result.backend_pid == graph_reader.read_identities[-1].backend_pid

    assert graph_reader.outer_uow_depths == [1]

    lowered = [statement.lower() for statement in statements]
    lock_indices = [
        index
        for index, statement in enumerate(lowered)
        if "account_authority_generation_lock()" in statement
    ]
    clock_indices = [
        index for index, statement in enumerate(lowered) if "clock_timestamp()" in statement
    ]
    assert len(lock_indices) == 1
    assert len(clock_indices) == 2
    assert lock_indices[0] < clock_indices[0] < clock_indices[1]
    assert not any(
        token in "\n".join(lowered)
        for token in ("lock table", "pg_advisory", "insert ", "update ", "delete ", "outbox")
    )


def test_postgres_complete_graph_mismatch_fails_closed_and_consumes_proof(
    runtime_alias: str,
) -> None:
    """Reject a changed stable graph digest after locking, before yielding scope."""

    finalizer, command, scan, graph_reader = _complete_finalizer(runtime_alias)
    proof = finalizer.capture_complete(command, scan)
    graph_reader._current = replace(
        graph_reader._current,
        valid_until=graph_reader._current.valid_until - timedelta(seconds=1),
    )

    with pytest.raises(AccountAuthorityGenerationChanged, match="fingerprint"):
        with finalizer.fence_complete(proof):
            pytest.fail("a complete graph mismatch must not be yielded")
    assert not connections[runtime_alias].in_atomic_block
    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="consumed"):
        with finalizer.fence_complete(proof):
            pytest.fail("a rejected complete proof must remain one-use")


def test_postgres_complete_caller_failure_rolls_back_same_transaction_write(
    runtime_alias: str,
) -> None:
    """Prove caller exceptions unwind and roll back the complete generation fence."""

    finalizer, command, scan, _graph_reader = _complete_finalizer(runtime_alias)
    proof = finalizer.capture_complete(command, scan)
    table_name = "account_authority_complete_finalizer_rollback_probe"
    with connections[runtime_alias].cursor() as cursor:
        cursor.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {table_name} (probe_id integer) "
            "ON COMMIT PRESERVE ROWS"
        )
        cursor.execute(f"TRUNCATE {table_name}")

    with pytest.raises(RuntimeError, match="caller work failed"):
        with finalizer.fence_complete(proof):
            with connections[runtime_alias].cursor() as cursor:
                cursor.execute(f"INSERT INTO {table_name} (probe_id) VALUES (1)")
            raise RuntimeError("caller work failed")

    with connections[runtime_alias].cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table_name}")
        row = cast(tuple[object, ...] | None, cursor.fetchone())
    assert row == (0,)


def test_postgres_complete_fence_holds_source_writer_until_scope_exits(
    runtime_alias: str,
) -> None:
    """Prove the generation row share lock blocks source-trigger writers in scope."""

    finalizer, command, scan, _graph_reader = _complete_finalizer(runtime_alias)
    proof = finalizer.capture_complete(command, scan)
    competing_alias = "account_authority_complete_finalizer_writer"
    if competing_alias in connections.databases:
        raise AssertionError("complete-fence writer alias already exists")
    connections.databases[competing_alias] = deepcopy(connections[runtime_alias].settings_dict)
    writer_started = Event()
    writer_backend_pids: Queue[int] = Queue()
    fence_entered = Event()
    exit_fence = Event()
    caller_hook_ran: list[bool] = []
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            final_check = executor.submit(
                _run_complete_fence_with_caller_hook,
                finalizer,
                proof,
                runtime_alias,
                fence_entered,
                exit_fence,
                caller_hook_ran,
            )
            assert fence_entered.wait(timeout=5)
            assert caller_hook_ran == [True]
            writer = executor.submit(
                _write_zero_row_source_statement,
                competing_alias,
                writer_started,
                writer_backend_pids,
            )
            assert writer_started.wait(timeout=5)
            backend_pid = writer_backend_pids.get(timeout=5)
            assert _wait_for_lock_wait(runtime_alias, backend_pid)
            assert not writer.done()
            exit_fence.set()
            result = final_check.result(timeout=10)
            assert result.scope == "account_authority_complete_graph"
            assert result.generation == scan.proof_generation
            assert writer.result(timeout=10) == scan.proof_generation + 1
    finally:
        exit_fence.set()
        connections[competing_alias].close()
        del connections[competing_alias]
        connections.databases.pop(competing_alias, None)


def _run_final_fence_with_caller_hook(
    finalizer: AccountAuthorityFinalRevalidatorV3,
    proof: AccountAuthorityFinalRevalidationProofV3,
    using: str,
    fence_entered: Event,
    exit_fence: Event,
    caller_hook_ran: list[bool],
) -> AccountAuthorityV3RootRevocationRevalidationResult:
    """Keep a caller hook inside the generation fence until the test releases it."""

    with finalizer.fence(proof) as result:
        caller_hook_ran.append(connections[using].in_atomic_block)
        fence_entered.set()
        if not exit_fence.wait(timeout=10):
            raise AssertionError("test did not release the caller-owned fence")
        return result


def _run_complete_fence_with_caller_hook(
    finalizer: AccountAuthorityFinalRevalidatorV3,
    proof: AccountAuthorityCompleteGraphFinalRevalidationProofV3,
    using: str,
    fence_entered: Event,
    exit_fence: Event,
    caller_hook_ran: list[bool],
) -> AccountAuthorityV3CompleteGraphRevalidationResult:
    """Hold a complete graph scope open until a competing source writer waits."""

    with finalizer.fence_complete(proof) as result:
        caller_hook_ran.append(connections[using].in_atomic_block)
        fence_entered.set()
        if not exit_fence.wait(timeout=10):
            raise AssertionError("test did not release the complete graph fence")
        return result


def _write_zero_row_source_statement(
    using: str,
    started: Event,
    backend_pids: Queue[int],
) -> int:
    """Issue a zero-row source UPDATE whose statement trigger bumps generation."""

    close_old_connections()
    try:
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            row = cast(tuple[object, ...] | None, cursor.fetchone())
        if row is None or type(row[0]) is not int:
            raise AssertionError("writer backend PID was not returned")
        backend_pids.put(row[0])
        started.set()
        with connections[using].cursor() as cursor:
            cursor.execute(f"UPDATE {_SOURCE_TABLE} SET id = id WHERE id = %s", [-1])
        return _generation(using)
    finally:
        connections[using].close()
