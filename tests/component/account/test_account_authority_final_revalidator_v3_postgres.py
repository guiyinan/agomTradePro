"""PostgreSQL contracts for the disconnected Authority V3 final-check slice."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from queue import Queue
from threading import Event
from typing import cast

import pytest
from django.db import close_old_connections, connections

from apps.account.application.account_authority_final_revalidation_v3_contracts import (
    AccountAuthorityV3FinalRootSelection,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    PersistedOwnerTenantAuthorityV3,
)
from apps.account.infrastructure.account_authority_final_revalidation_v3_repository import (
    DjangoAccountAuthorityV3RootRevocationRevalidationRepository,
)
from apps.account.infrastructure.account_authority_final_revalidator_v3 import (
    AccountAuthorityFinalRevalidationProofV3,
    AccountAuthorityFinalRevalidationUnavailable,
    AccountAuthorityFinalRevalidatorV3,
    AccountAuthorityV3RootRevocationRevalidationResult,
)
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationChanged,
    verify_account_authority_generation_coverage,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityShadowScanResultV3,
    _compare_current_observations,
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
        statement.lstrip().split(None, 1)[0].upper() in {"SELECT", "SET"}
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
