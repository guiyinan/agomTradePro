from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol, cast

import pytest
from django.utils import timezone

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerTenantAuthorityV3,
    OwnerTenantAuthorityV3Conflict,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PhysicalAccountRowProviderIdentity,
)
from apps.account.infrastructure import account_authority_generation as generation_module
from apps.account.infrastructure import account_authority_shadow_scanner as shadow_module
from apps.account.infrastructure import (
    generation_fenced_owner_tenant_authority_v3_repository as generation_fenced_repository_module,
)
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationProof,
    AccountAuthorityGenerationUnavailable,
    caller_owned_account_authority_generation_fence,
    capture_active_account_authority_physical_provider_identity,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityCurrentGraphReaderV3,
    AccountAuthorityCurrentGraphReadV3,
    AccountAuthorityShadowScannerV3,
    DjangoAccountAuthorityNoLockSnapshotBundleProviderV3,
)
from apps.account.infrastructure.generation_fenced_owner_tenant_authority_v3_repository import (
    GenerationFencedOwnerTenantAuthorityV3Repository,
)
from tests.unit.audit.test_system_audit_authority_v3_reader import (
    _authority,
    _authority_source,
    _PhysicalProvider,
)


class _PhysicalProviderWithoutReadClock(_PhysicalProvider):
    bind_read_clock = None


class _Clock(Protocol):
    def now(self) -> datetime: ...


class _Cursor:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.statements: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str, params: object = None) -> None:
        del params
        self.statements.append(statement)

    def fetchone(self) -> tuple[object, ...]:
        statement = self.connection.cursor_value.statements[-1].lower()
        if "clock_timestamp()" in statement:
            return (self.connection.database_clock_timestamp,)
        if "current_setting" in statement and "pg_current_xact_id" in statement:
            return (
                self.connection.isolation,
                self.connection.read_only,
                self.connection.transaction_id,
                self.connection.backend_pid,
                self.connection.generation,
            )
        if "current_setting" in statement:
            return (self.connection.isolation, self.connection.read_only)
        if "pg_current_xact_id" in statement:
            return (self.connection.transaction_id, self.connection.backend_pid)
        return (self.connection.generation,)


class _Connection:
    def __init__(
        self,
        *,
        alias: str = "default",
        vendor: str = "postgresql",
        isolation: str = "repeatable read",
        read_only: str = "on",
        in_atomic_block: bool = True,
        autocommit: bool = False,
        database_clock_timestamp: datetime | None = None,
    ) -> None:
        self.alias = alias
        self.vendor = vendor
        self.isolation = isolation
        self.read_only = read_only
        self.generation = 41
        self.transaction_id = "41"
        self.backend_pid = 1234
        self.database_clock_timestamp = (
            database_clock_timestamp
            if database_clock_timestamp is not None
            else _legacy_current().observed_at
        )
        self.rollback_only = False
        self.in_atomic_block = in_atomic_block
        self.autocommit = autocommit
        self.atomic_blocks = [object()] if in_atomic_block else []
        self.connection = object()
        self.cursor_value = _Cursor(self)

    def get_autocommit(self) -> bool:
        return self.autocommit

    def cursor(self) -> _Cursor:
        return self.cursor_value


class _Atomic:
    def __init__(self, connection: _Connection, events: list[str]) -> None:
        self.connection = connection
        self.events = events

    def __enter__(self) -> None:
        self.events.append("transaction.begin")
        self.connection.in_atomic_block = True
        self.connection.autocommit = False

    def __exit__(self, *args: object) -> None:
        self.events.append("transaction.end")
        self.connection.in_atomic_block = False
        self.connection.autocommit = True


def _scanner() -> AccountAuthorityShadowScannerV3:
    return AccountAuthorityShadowScannerV3(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="c" * 64,
        physical_row_provider=_PhysicalProvider(),
        using="default",
    )


def _legacy_current() -> CurrentOwnerTenantAuthorityV3:
    authority = _authority()
    observed_at = authority.recorded_at + timedelta(microseconds=1)
    authentication = _authority_source(
        authority.assignment,
        valid_until=authority.valid_until,
    )
    return CurrentOwnerTenantAuthorityV3(
        authority=authority,
        authentication=authentication,
        observed_at=observed_at,
        valid_until=min(
            authority.valid_until,
            authority.assignment.valid_until,
            authority.policy.valid_until,
            authentication.valid_until,
        ),
    )


def test_no_lock_actor_snapshot_requires_one_active_rr_read_only_alias() -> None:
    connection = _Connection()
    provider = DjangoAccountAuthorityNoLockSnapshotBundleProviderV3(using="default")

    with provider._snapshot(connection):  # type: ignore[arg-type]
        pass

    assert len(connection.cursor_value.statements) == 1
    statement = connection.cursor_value.statements[0].lower()
    assert "current_setting" in statement
    assert "lock table" not in statement
    assert "pg_advisory" not in statement


def test_generation_fenced_authority_repository_joins_outer_uow_without_savepoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the complete graph read in the finalizer's single outer transaction."""

    connection = _Connection(isolation="read committed", read_only="off")
    checks: list[tuple[str, int, int]] = []
    monkeypatch.setattr(
        generation_fenced_repository_module,
        "connections",
        {"default": connection},
    )
    monkeypatch.setattr(
        generation_fenced_repository_module,
        "require_active_account_authority_generation_fence",
        lambda *, using, connection, generation: checks.append(
            (using, generation, len(connection.atomic_blocks))
        ),
    )
    repository = GenerationFencedOwnerTenantAuthorityV3Repository(
        expected_generation=41,
        using="default",
        clock=shadow_module._AuthorityGraphFrozenClock(_legacy_current().observed_at),
        assignments=shadow_module.DjangoAccountOwnerAssignmentEvidenceV5Repository(),
        policies=shadow_module.DjangoSingleOwnerAuthorityPolicyV1Repository(),
        actors=shadow_module.DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(),
    )
    monkeypatch.setattr(repository, "_postgresql", lambda: None)

    with repository.atomic():
        assert repository._active is True
        assert repository._uow is None
        with pytest.raises(OwnerTenantAuthorityV3Conflict, match="private UOW"):
            repository._require_uow()

    assert checks == [("default", 41, 1), ("default", 41, 1)]
    assert repository._active is False
    assert repository._uow is None


def test_generation_fenced_authority_repository_fails_closed_without_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject caller-owned UOW use unless the exact generation fence is active."""

    connection = _Connection(isolation="read committed", read_only="off")
    monkeypatch.setattr(
        generation_fenced_repository_module,
        "connections",
        {"default": connection},
    )
    monkeypatch.setattr(
        generation_fenced_repository_module,
        "require_active_account_authority_generation_fence",
        lambda **_kwargs: (_ for _ in ()).throw(
            AccountAuthorityGenerationUnavailable("active generation fence is unavailable")
        ),
    )
    repository = GenerationFencedOwnerTenantAuthorityV3Repository(
        expected_generation=41,
        using="default",
        clock=shadow_module._AuthorityGraphFrozenClock(_legacy_current().observed_at),
        assignments=shadow_module.DjangoAccountOwnerAssignmentEvidenceV5Repository(),
        policies=shadow_module.DjangoSingleOwnerAuthorityPolicyV1Repository(),
        actors=shadow_module.DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(),
    )
    monkeypatch.setattr(repository, "_postgresql", lambda: None)

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="active generation fence"):
        with repository.atomic():
            pytest.fail("unfenced caller-owned UOW must not execute")

    assert repository._active is False
    assert repository._uow is None


def test_generation_fenced_graph_composes_caller_owned_authority_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire only the final generation-fenced graph to the caller-owned UOW."""

    current = _legacy_current()
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    observed_generations: list[int] = []

    def no_winner(
        repository: GenerationFencedOwnerTenantAuthorityV3Repository,
        **_kwargs: object,
    ) -> None:
        observed_generations.append(repository._expected_generation)
        return None

    monkeypatch.setattr(
        GenerationFencedOwnerTenantAuthorityV3Repository,
        "get_winner",
        no_winner,
    )
    monkeypatch.setattr(
        GenerationFencedOwnerTenantAuthorityV3Repository,
        "now",
        lambda _repository: current.observed_at,
    )
    reader = AccountAuthorityCurrentGraphReaderV3(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="c" * 64,
        physical_row_provider=_PhysicalProvider(),
        using="default",
        transaction_mode="generation_fenced_read_committed_read_write",
    )

    assert (
        reader._read_application_graph(
            command,
            clock=shadow_module._AuthorityGraphFrozenClock(current.observed_at),
            generation=41,
        )
        is None
    )
    assert observed_generations == [41]


def test_generation_fence_uses_share_row_lock_for_compatible_final_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(isolation="read committed", read_only="off")
    proof = AccountAuthorityGenerationProof(using="default", generation=41)
    monkeypatch.setattr(generation_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        generation_module,
        "_require_transaction_mode",
        lambda received, *, isolation, read_only: None,
    )
    monkeypatch.setattr(
        generation_module,
        "verify_account_authority_generation_coverage",
        lambda *, using: object(),
    )
    monkeypatch.setattr(
        generation_module,
        "verify_account_authority_generation_runtime_acl",
        lambda *, using: None,
    )

    assert generation_module.lock_account_authority_generation_fence(proof, using="default") == 41

    statement = connection.cursor_value.statements[-1].lower()
    assert "account_authority_generation_lock()" in statement
    assert "for share" not in statement
    assert "for update" not in statement


@pytest.mark.parametrize(
    ("mode", "isolation", "read_only"),
    [
        ("repeatable_read_read_only", "repeatable read", "on"),
        ("generation_fenced_read_committed_read_write", "read committed", "off"),
    ],
)
def test_current_graph_reader_accepts_only_its_caller_owned_transaction_mode(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    isolation: str,
    read_only: str,
) -> None:
    current = _legacy_current()
    connection = _Connection(
        isolation=isolation,
        read_only=read_only,
        database_clock_timestamp=current.observed_at,
    )
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    reads: list[GetCurrentOwnerTenantAuthorityV3Command] = []
    expected_generation = 41 if mode == "generation_fenced_read_committed_read_write" else None

    def graph_read(
        _self: AccountAuthorityCurrentGraphReaderV3,
        received: GetCurrentOwnerTenantAuthorityV3Command,
        *,
        clock: _Clock,
        generation: int | None,
    ) -> CurrentOwnerTenantAuthorityV3:
        assert clock.now() is current.observed_at
        assert generation == expected_generation
        reads.append(received)
        return current

    monkeypatch.setattr(shadow_module, "_connection", lambda using: connection)
    monkeypatch.setattr(AccountAuthorityCurrentGraphReaderV3, "_read_application_graph", graph_read)
    monkeypatch.setattr(
        shadow_module.transaction,
        "atomic",
        lambda **_kwargs: pytest.fail("current graph reader must not own a transaction"),
    )
    reader = AccountAuthorityCurrentGraphReaderV3(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="c" * 64,
        physical_row_provider=_PhysicalProvider(),
        using="default",
        transaction_mode=mode,
    )

    if mode == "repeatable_read_read_only":
        result = reader.read(command)
    else:
        proof = AccountAuthorityGenerationProof(using="default", generation=41)
        monkeypatch.setattr(generation_module, "_connection", lambda using: connection)
        monkeypatch.setattr(
            generation_module,
            "lock_account_authority_generation_fence",
            lambda received, *, using: received.generation,
        )
        with caller_owned_account_authority_generation_fence(proof, using="default") as generation:
            result = reader.read(command, generation=generation)
    assert type(result) is AccountAuthorityCurrentGraphReadV3
    assert result.authority is current
    assert result.checked_at is current.observed_at
    assert reads == [command]
    assert connection.in_atomic_block is True
    assert connection.get_autocommit() is False
    assert len(connection.cursor_value.statements) >= 1
    setting_reads = sum(
        "current_setting" in statement.lower() for statement in connection.cursor_value.statements
    )
    assert setting_reads >= (1 if mode == "repeatable_read_read_only" else 2)


@pytest.mark.parametrize(
    ("offset_microseconds", "is_current"),
    ((-1, True), (0, False), (1, False)),
)
def test_current_graph_reader_applies_one_database_cutoff_at_valid_until_boundary(
    monkeypatch: pytest.MonkeyPatch,
    offset_microseconds: int,
    is_current: bool,
) -> None:
    current = _legacy_current()
    cutoff = current.valid_until + timedelta(microseconds=offset_microseconds)
    connection = _Connection(database_clock_timestamp=cutoff)
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    cutoffs: list[datetime] = []

    def graph_read(
        _self: AccountAuthorityCurrentGraphReaderV3,
        _command: GetCurrentOwnerTenantAuthorityV3Command,
        *,
        clock: _Clock,
        generation: int | None,
    ) -> CurrentOwnerTenantAuthorityV3 | None:
        assert generation is None
        cutoff = clock.now()
        cutoffs.append(cutoff)
        if cutoff >= current.valid_until:
            return None
        return replace(current, observed_at=clock.now())

    monkeypatch.setattr(shadow_module, "_connection", lambda _using: connection)
    monkeypatch.setattr(AccountAuthorityCurrentGraphReaderV3, "_read_application_graph", graph_read)
    reader = AccountAuthorityCurrentGraphReaderV3(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="c" * 64,
        physical_row_provider=_PhysicalProvider(),
        using="default",
        transaction_mode="repeatable_read_read_only",
    )

    result = reader.read(command)

    assert result.checked_at == cutoff
    assert (result.authority is not None) is is_current
    if result.authority is not None:
        assert result.authority.observed_at == cutoff
    assert cutoffs == [cutoff]
    clock_queries = sum(
        "clock_timestamp()" in statement.lower() for statement in connection.cursor_value.statements
    )
    assert clock_queries == 1


def test_current_graph_reader_keeps_one_cutoff_while_application_clock_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _legacy_current()
    cutoff = current.observed_at
    connection = _Connection(database_clock_timestamp=cutoff)
    application_clock_reads: list[datetime] = []
    clock_calls = 0
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    repository_cutoffs: list[datetime] = []

    def graph_read(
        _self: AccountAuthorityCurrentGraphReaderV3,
        _command: GetCurrentOwnerTenantAuthorityV3Command,
        *,
        clock: _Clock,
        generation: int | None,
    ) -> CurrentOwnerTenantAuthorityV3:
        assert generation is None
        before = timezone.now()
        repository_cutoffs.extend(clock.now() for _ in range(8))
        after = timezone.now()
        assert before != after
        return current

    def moving_application_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        value = cutoff + timedelta(seconds=clock_calls)
        application_clock_reads.append(value)
        return value

    monkeypatch.setattr(timezone, "now", moving_application_clock)
    monkeypatch.setattr(shadow_module, "_connection", lambda _using: connection)
    monkeypatch.setattr(AccountAuthorityCurrentGraphReaderV3, "_read_application_graph", graph_read)
    reader = AccountAuthorityCurrentGraphReaderV3(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="c" * 64,
        physical_row_provider=_PhysicalProvider(),
        using="default",
        transaction_mode="repeatable_read_read_only",
    )

    result = reader.read(command)

    assert result.checked_at == cutoff
    assert result.authority is current
    assert repository_cutoffs == [cutoff] * 8
    assert application_clock_reads[-2] != application_clock_reads[-1]


@pytest.mark.parametrize(
    ("mode", "connection", "message"),
    [
        ("repeatable_read_read_only", _Connection(alias="other"), "alias"),
        ("repeatable_read_read_only", _Connection(vendor="sqlite"), "PostgreSQL"),
        (
            "repeatable_read_read_only",
            _Connection(isolation="read committed", read_only="on"),
            "transaction mode",
        ),
        (
            "generation_fenced_read_committed_read_write",
            _Connection(isolation="repeatable read", read_only="off"),
            "transaction mode",
        ),
        (
            "generation_fenced_read_committed_read_write",
            _Connection(isolation="read committed", read_only="on"),
            "transaction mode",
        ),
        (
            "generation_fenced_read_committed_read_write",
            _Connection(in_atomic_block=False, autocommit=True),
            "active caller-owned transaction",
        ),
    ],
)
def test_current_graph_reader_fails_closed_before_graph_read_on_mode_drift(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    connection: _Connection,
    message: str,
) -> None:
    current = _legacy_current()
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    graph_reads: list[object] = []
    monkeypatch.setattr(shadow_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        AccountAuthorityCurrentGraphReaderV3,
        "_read_application_graph",
        lambda self, value: graph_reads.append(value),
    )
    reader = AccountAuthorityCurrentGraphReaderV3(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="c" * 64,
        physical_row_provider=_PhysicalProvider(),
        using="default",
        transaction_mode=mode,
    )

    with pytest.raises(AccountAuthorityGenerationUnavailable, match=message):
        reader.read(command)

    assert graph_reads == []


def test_generation_fenced_reader_rejects_ordinary_rc_rw_transaction_before_graph_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(isolation="read committed", read_only="off")
    current = _legacy_current()
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    graph_reads: list[object] = []
    monkeypatch.setattr(shadow_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        AccountAuthorityCurrentGraphReaderV3,
        "_read_application_graph",
        lambda self, value: graph_reads.append(value),
    )
    reader = AccountAuthorityCurrentGraphReaderV3(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="c" * 64,
        physical_row_provider=_PhysicalProvider(),
        using="default",
        transaction_mode="generation_fenced_read_committed_read_write",
    )

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="active generation fence"):
        reader.read(command, generation=41)

    assert graph_reads == []


@pytest.mark.parametrize(
    ("mismatch", "message"),
    (
        ("alias", "another database alias"),
        ("physical_connection", "another physical connection"),
        ("connection_wrapper", "another Django connection wrapper"),
        ("transaction_id", "transaction identity changed"),
    ),
)
def test_active_generation_fence_rejects_alias_and_physical_connection_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
    message: str,
) -> None:
    connection = _Connection(isolation="read committed", read_only="off")
    proof = AccountAuthorityGenerationProof(using="default", generation=41)
    monkeypatch.setattr(generation_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        generation_module,
        "lock_account_authority_generation_fence",
        lambda received, *, using: received.generation,
    )

    with caller_owned_account_authority_generation_fence(proof, using="default"):
        if mismatch == "alias":
            other = _Connection(alias="other", isolation="read committed", read_only="off")
            using = "other"
        elif mismatch == "transaction_id":
            connection.transaction_id = "42"
            other = connection
            using = "default"
        elif mismatch == "connection_wrapper":
            other = _Connection(isolation="read committed", read_only="off")
            other.connection = connection.connection
            using = "default"
        else:
            other = _Connection(isolation="read committed", read_only="off")
            using = "default"
        with pytest.raises(AccountAuthorityGenerationUnavailable, match=message):
            generation_module.require_active_account_authority_generation_fence(
                using=using,
                connection=other,  # type: ignore[arg-type]
                generation=41,
            )
        if mismatch == "transaction_id":
            connection.transaction_id = "41"


def test_generation_fence_exports_wrapper_connection_pid_xid_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(isolation="read committed", read_only="off")
    proof = AccountAuthorityGenerationProof(using="default", generation=41)
    monkeypatch.setattr(generation_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        generation_module,
        "lock_account_authority_generation_fence",
        lambda received, *, using: received.generation,
    )

    with caller_owned_account_authority_generation_fence(proof, using="default") as generation:
        identity = capture_active_account_authority_physical_provider_identity(
            using="default",
            connection=connection,  # type: ignore[arg-type]
            generation=generation,
        )

    assert identity.using == "default"
    assert identity.wrapper_token is connection
    assert identity.dbapi_token is connection.connection
    assert identity.backend_pid == connection.backend_pid
    assert identity.transaction_xid == connection.transaction_id
    assert identity.thread_id > 0
    assert identity.generation == generation


@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("physical_connection", "another physical connection"),
        ("transaction", "active outer transaction"),
    ],
)
def test_generation_fence_context_fails_closed_on_normal_exit_drift_and_resets(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
    message: str,
) -> None:
    connection = _Connection(isolation="read committed", read_only="off")
    proof = AccountAuthorityGenerationProof(using="default", generation=41)
    monkeypatch.setattr(generation_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        generation_module,
        "lock_account_authority_generation_fence",
        lambda received, *, using: received.generation,
    )

    with pytest.raises(AccountAuthorityGenerationUnavailable, match=message):
        with caller_owned_account_authority_generation_fence(proof, using="default"):
            if drift == "physical_connection":
                connection.connection = object()
            else:
                connection.in_atomic_block = False
                connection.autocommit = True
                connection.atomic_blocks = []

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="active generation fence"):
        generation_module.require_active_account_authority_generation_fence(
            using="default",
            connection=connection,  # type: ignore[arg-type]
            generation=41,
        )


def test_generation_fence_context_cleans_context_after_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(isolation="read committed", read_only="off")
    proof = AccountAuthorityGenerationProof(using="default", generation=41)
    monkeypatch.setattr(generation_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        generation_module,
        "lock_account_authority_generation_fence",
        lambda received, *, using: received.generation,
    )

    monkeypatch.setattr(
        generation_module.transaction,
        "set_rollback",
        lambda rollback, *, using: setattr(connection, "rollback_only", rollback),
    )
    try:
        with caller_owned_account_authority_generation_fence(proof, using="default"):
            raise RuntimeError("caller failure")
    except RuntimeError as error:
        assert str(error) == "caller failure"
    else:
        raise AssertionError("caller exception was swallowed")
    assert connection.rollback_only is True

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="active generation fence"):
        generation_module.require_active_account_authority_generation_fence(
            using="default",
            connection=connection,  # type: ignore[arg-type]
            generation=41,
        )


def test_generation_fence_context_marks_rollback_when_exit_recheck_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(isolation="read committed", read_only="off")
    proof = AccountAuthorityGenerationProof(using="default", generation=41)
    monkeypatch.setattr(generation_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        generation_module,
        "lock_account_authority_generation_fence",
        lambda received, *, using: received.generation,
    )
    monkeypatch.setattr(
        generation_module.transaction,
        "set_rollback",
        lambda rollback, *, using: setattr(connection, "rollback_only", rollback),
    )

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="fence state is invalid"):
        with caller_owned_account_authority_generation_fence(proof, using="default"):
            connection.read_only = "on"

    assert connection.rollback_only is True


def test_generation_fence_rejects_live_inherited_child_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(isolation="read committed", read_only="off")
    proof = AccountAuthorityGenerationProof(using="default", generation=41)
    monkeypatch.setattr(generation_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        generation_module,
        "lock_account_authority_generation_fence",
        lambda received, *, using: received.generation,
    )

    async def child_read() -> None:
        with pytest.raises(
            AccountAuthorityGenerationUnavailable, match="execution context changed"
        ):
            generation_module.require_active_account_authority_generation_fence(
                using="default",
                connection=connection,  # type: ignore[arg-type]
                generation=41,
            )

    async def parent_scope() -> None:
        with caller_owned_account_authority_generation_fence(proof, using="default"):
            await asyncio.create_task(child_read())

    asyncio.run(parent_scope())


def test_generation_fence_scope_end_rejects_following_transaction_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(isolation="read committed", read_only="off")
    proof = AccountAuthorityGenerationProof(using="default", generation=41)
    monkeypatch.setattr(generation_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        generation_module,
        "lock_account_authority_generation_fence",
        lambda received, *, using: received.generation,
    )

    with caller_owned_account_authority_generation_fence(proof, using="default"):
        pass
    connection.transaction_id = "42"

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="active generation fence"):
        generation_module.require_active_account_authority_generation_fence(
            using="default",
            connection=connection,  # type: ignore[arg-type]
            generation=41,
        )


def test_current_graph_reader_rejects_unknown_mode_and_exact_alias_mismatch() -> None:
    with pytest.raises(ValueError, match="transaction_mode"):
        AccountAuthorityCurrentGraphReaderV3(
            actor_source_id="audit-actor-v3",
            actor_source_version="v1",
            actor_content_hash="c" * 64,
            physical_row_provider=_PhysicalProvider(),
            using="default",
            transaction_mode="read committed",
        )

    with pytest.raises(TypeError, match="bind_read_clock"):
        AccountAuthorityCurrentGraphReaderV3(
            actor_source_id="audit-actor-v3",
            actor_source_version="v1",
            actor_content_hash="c" * 64,
            physical_row_provider=_PhysicalProviderWithoutReadClock(),
            using="default",
            transaction_mode="repeatable_read_read_only",
        )


def test_current_graph_reader_rejects_non_exact_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    current = _legacy_current()
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    monkeypatch.setattr(shadow_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        AccountAuthorityCurrentGraphReaderV3,
        "_read_application_graph",
        lambda self, value, *, clock, generation: cast(
            CurrentOwnerTenantAuthorityV3 | None, object()
        ),
    )
    reader = AccountAuthorityCurrentGraphReaderV3(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="c" * 64,
        physical_row_provider=_PhysicalProvider(),
        using="default",
        transaction_mode="repeatable_read_read_only",
    )

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="invalid Authority V3"):
        reader.read(command)

    with pytest.raises(ValueError, match="alias"):
        AccountAuthorityCurrentGraphReaderV3(
            actor_source_id="audit-actor-v3",
            actor_source_version="v1",
            actor_content_hash="c" * 64,
            physical_row_provider=_PhysicalProvider(),
            using=" default",
            transaction_mode="repeatable_read_read_only",
        )


@pytest.mark.parametrize(
    ("connection", "error_type", "message"),
    [
        (_Connection(alias="other"), AccountActorAuthorityRawSourceV3Corruption, "alias"),
        (_Connection(vendor="sqlite"), AccountActorAuthorityRawSourceV3Unavailable, "PostgreSQL"),
        (
            _Connection(isolation="read committed"),
            AccountActorAuthorityRawSourceV3Unavailable,
            "repeatable read",
        ),
        (
            _Connection(read_only="off"),
            AccountActorAuthorityRawSourceV3Unavailable,
            "read-only",
        ),
        (
            _Connection(in_atomic_block=False, autocommit=True),
            AccountActorAuthorityRawSourceV3Unavailable,
            "active transaction",
        ),
    ],
)
def test_no_lock_actor_snapshot_fails_closed_on_alias_or_transaction_drift(
    connection: _Connection,
    error_type: type[Exception],
    message: str,
) -> None:
    provider = DjangoAccountAuthorityNoLockSnapshotBundleProviderV3(using="default")

    with pytest.raises(error_type, match=message):
        provider._snapshot(connection)  # type: ignore[arg-type]


def test_shadow_proof_and_closed_world_reader_share_one_rr_transaction_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=False, autocommit=True)
    events: list[str] = []
    baseline = _legacy_current()
    legacy = replace(
        baseline,
        authentication=replace(
            baseline.authentication,
            source_id="audit-actor-v3",
            source_version="v1",
            source_content_hash="c" * 64,
        ),
    )
    legacy.__post_init__()
    legacy_before = legacy
    command = GetCurrentOwnerTenantAuthorityV3Command(
        legacy.authority.authority_id,
        legacy.authority.authority_version,
        legacy.authority.content_hash,
    )
    scanner = _scanner()
    current_reads: list[tuple[object, bool, str, str]] = []

    def proof_reader(*, using: str) -> AccountAuthorityGenerationProof:
        events.append("proof")
        assert using == "default"
        assert connection.in_atomic_block
        assert not connection.get_autocommit()
        assert connection.isolation == "repeatable read"
        assert connection.read_only == "on"
        return AccountAuthorityGenerationProof(using=using, generation=41)

    def current_reader(
        _self: AccountAuthorityShadowScannerV3,
        _command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> AccountAuthorityCurrentGraphReadV3:
        events.append("scan")
        current_reads.append(
            (connection, connection.in_atomic_block, connection.isolation, connection.read_only)
        )
        return AccountAuthorityCurrentGraphReadV3(
            checked_at=legacy.observed_at,
            authority=legacy,
            physical_identity=PhysicalAccountRowProviderIdentity(
                using="default",
                wrapper_token=connection,
                dbapi_token=object(),
                backend_pid=4321,
                transaction_xid="rr-test-xid",
                thread_id=1,
                task_token=None,
            ),
        )

    monkeypatch.setattr(shadow_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        shadow_module.transaction,
        "atomic",
        lambda *, using: _Atomic(connection, events),
    )
    monkeypatch.setattr(shadow_module, "read_account_authority_generation_proof", proof_reader)
    monkeypatch.setattr(AccountAuthorityShadowScannerV3, "_read_shadow", current_reader)

    result = scanner.scan(command, legacy)

    assert events.index("proof") < events.index("scan")
    assert current_reads == [(connection, True, "repeatable read", "on")]
    assert result.database_alias == "default"
    assert result.proof_generation == 41
    assert result.comparison.matches is True
    assert result.comparison.differing_fields == ()
    assert result.selector is not None
    assert result.comparison.shadow is not None
    assert result.selector == scanner._graph_reader().selector_for(command)
    assert legacy is legacy_before
    assert legacy == legacy_before
    forbidden = ("lock table", "pg_advisory", "insert ", "update ", "delete ", "truncate ")
    assert not any(
        token in statement.lower()
        for statement in connection.cursor_value.statements
        for token in forbidden
    )


@pytest.mark.parametrize(
    "changed_selector",
    ("authority_id", "authority_version", "content_hash"),
)
def test_shadow_rejects_legacy_authority_selector_mismatch_before_opening_transaction(
    monkeypatch: pytest.MonkeyPatch,
    changed_selector: str,
) -> None:
    legacy = _legacy_current()
    selectors = (
        legacy.authority.authority_id,
        legacy.authority.authority_version,
        legacy.authority.content_hash,
    )
    selector_values = list(selectors)
    changed_index = {
        "authority_id": 0,
        "authority_version": 1,
        "content_hash": 2,
    }[changed_selector]
    selector_values[changed_index] = (
        "different-authority"
        if changed_selector == "authority_id"
        else "different-version" if changed_selector == "authority_version" else "0" * 64
    )
    command = GetCurrentOwnerTenantAuthorityV3Command(
        selector_values[0],
        selector_values[1],
        selector_values[2],
    )

    def unexpected_connection(_using: str) -> object:
        pytest.fail("selector mismatch must fail before resolving a database connection")

    monkeypatch.setattr(shadow_module, "_connection", unexpected_connection)

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="selectors"):
        _scanner().scan(command, legacy)


def test_shadow_rejects_a_proof_bound_to_another_alias_before_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=False, autocommit=True)
    events: list[str] = []
    legacy = _legacy_current()
    command = GetCurrentOwnerTenantAuthorityV3Command(
        legacy.authority.authority_id,
        legacy.authority.authority_version,
        legacy.authority.content_hash,
    )
    scanner = _scanner()
    scan_calls: list[object] = []

    monkeypatch.setattr(shadow_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        shadow_module.transaction,
        "atomic",
        lambda *, using: _Atomic(connection, events),
    )
    monkeypatch.setattr(
        shadow_module,
        "read_account_authority_generation_proof",
        lambda *, using: AccountAuthorityGenerationProof(using="other", generation=9),
    )
    monkeypatch.setattr(
        AccountAuthorityShadowScannerV3,
        "_read_shadow",
        lambda self, value: scan_calls.append(value),
    )

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="alias"):
        scanner.scan(command, legacy)

    assert scan_calls == []
