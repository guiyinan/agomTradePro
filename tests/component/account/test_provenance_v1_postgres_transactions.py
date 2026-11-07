"""Native PostgreSQL transaction cases for the V1 provenance receipt ledger."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier, local

import pytest
from django.db import IntegrityError, connections, transaction

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceiptConflict,
    PersistedAccountOwnerAssignmentProvenanceReceipt,
)
from apps.account.domain.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceipt,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
)
from apps.account.infrastructure import (
    account_owner_assignment_provenance_receipt_repository as repository_module,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_models import (
    AccountOwnerAssignmentProvenanceReceiptModel,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
)

_NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class _Clock:
    """Supply the same deterministic Account clock to independent sessions."""

    def now(self) -> datetime:
        return _NOW


class _IntentionalRollback(RuntimeError):
    """Mark the explicit outer transaction rollback in its test."""


@dataclass(frozen=True, slots=True)
class _AppendOutcome:
    """Capture one worker result without hiding unexpected database errors."""

    backend_pid: int
    record: PersistedAccountOwnerAssignmentProvenanceReceipt | None
    conflict: AccountOwnerAssignmentProvenanceReceiptConflict | None


def _actor() -> AccountOwnerAssignmentServerActor:
    """Build a synthetic human claimant used only by this isolated test."""

    return AccountOwnerAssignmentServerActor(
        actor_id="claimant:19",
        user_id=19,
        role="account_owner_claimant",
        kind="human",
        is_staff=False,
    )


def _physical_row() -> PhysicalAccountRowObservation:
    """Build a synthetic, internally valid physical-row observation."""

    return PhysicalAccountRowObservation(
        observation_id="pg-transaction-row-7",
        observation_version="physical-account-row.v1",
        account_namespace="account",
        account_id="synthetic-real-account-7",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=7,
        raw_source_owner="simulated_trading",
        raw_source_artifact_type="simulated_account_row",
        raw_source_id="synthetic-simulated-account-row-7",
        raw_source_version="simulated-account-row.v1",
        raw_source_content_hash="a" * 64,
        row_user_id=19,
        account_type="real",
        is_active=True,
        row_created_at=_NOW - timedelta(hours=2),
        row_updated_at=_NOW - timedelta(hours=1),
        observed_at=_NOW - timedelta(minutes=30),
        recorded_at=_NOW - timedelta(minutes=20),
        raw_source_valid_until=_NOW + timedelta(days=10),
        ttl_valid_until=_NOW + timedelta(days=10),
        valid_until=_NOW + timedelta(days=10),
    )


def _record(
    *,
    receipt_version: str = "account-assignment-provenance.v1",
    recorded_at: datetime = _NOW - timedelta(minutes=10),
    supersedes_content_hash: str | None = None,
) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
    """Create one valid V1 receipt record for repository-level transaction tests."""

    row = _physical_row()
    actor = _actor()
    receipt = AccountOwnerAssignmentProvenanceReceipt(
        receipt_id="pg-v1-transaction-receipt-7",
        receipt_version=receipt_version,
        provenance_kind="creation",
        artifact_type="account_creation_receipt",
        assignment_state="authoritative",
        assigned_owner_user_id=actor.user_id,
        account_namespace=row.account_namespace,
        account_id=row.account_id,
        underlying_unified_account_namespace=row.underlying_unified_account_namespace,
        underlying_unified_account_id=row.underlying_unified_account_id,
        row_observation_owner=row.owner,
        row_observation_artifact_type=row.artifact_type,
        row_observation_id=row.observation_id,
        row_observation_version=row.observation_version,
        row_observation_identity_hash=row.identity_hash,
        row_observation_content_hash=row.content_hash,
        row_observation_valid_until=row.valid_until,
        claimant=actor.to_domain(),
        issued_at=recorded_at,
        recorded_at=recorded_at,
        valid_until=_NOW + timedelta(days=5),
        supersedes_content_hash=supersedes_content_hash,
    )
    return PersistedAccountOwnerAssignmentProvenanceReceipt(receipt, actor)


def _require_postgresql(alias: str = "default") -> None:
    """Skip this explicitly PG-only test under portable SQLite CI."""

    if connections[alias].vendor != "postgresql":
        pytest.skip("V1 independent-transaction behavior requires PostgreSQL")


def _synchronize_after_missing_winner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    barrier: Barrier,
    receipt_id: str,
) -> None:
    """Align workers after each exact-winner probe and before repository CAS."""

    original = DjangoAccountOwnerAssignmentProvenanceReceiptRepository._exact_model
    per_thread = local()

    def synchronized_probe(
        repository: DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
        record: PersistedAccountOwnerAssignmentProvenanceReceipt,
    ) -> object | None:
        result = original(repository, record)
        if (
            record.receipt.receipt_id == receipt_id
            and result is None
            and not getattr(per_thread, "aligned", False)
        ):
            per_thread.aligned = True
            barrier.wait(timeout=30)
        return result

    monkeypatch.setattr(
        DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
        "_exact_model",
        synchronized_probe,
    )


def _append_worker(
    *,
    alias: str,
    record: PersistedAccountOwnerAssignmentProvenanceReceipt,
    expected_predecessor_hash: str | None,
) -> _AppendOutcome:
    """Append from one independent Django thread-local PostgreSQL connection."""

    connection = connections[alias]
    try:
        repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(
            using=alias,
            clock=_Clock(),
        )
        with repository.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend_pid = int(cursor.fetchone()[0])
            try:
                value = repository.append(
                    record,
                    expected_predecessor_hash=expected_predecessor_hash,
                    recorded_at=record.receipt.recorded_at,
                )
            except AccountOwnerAssignmentProvenanceReceiptConflict as error:
                return _AppendOutcome(backend_pid, None, error)
            return _AppendOutcome(backend_pid, value, None)
    finally:
        connection.close()


def _run_two_appends(
    *,
    records: tuple[PersistedAccountOwnerAssignmentProvenanceReceipt, ...],
    expected_predecessor_hash: str | None,
    alias: str = "default",
) -> tuple[_AppendOutcome, _AppendOutcome]:
    """Run two repository appends concurrently, preserving unexpected exceptions."""

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(
            executor.submit(
                _append_worker,
                alias=alias,
                record=record,
                expected_predecessor_hash=expected_predecessor_hash,
            )
            for record in records
        )
        first = futures[0].result(timeout=45)
        second = futures[1].result(timeout=45)
    return first, second


@pytest.mark.django_db(transaction=True)
def test_postgresql_same_root_race_returns_one_identical_first_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two independent sessions racing the same root retain one exact winner."""

    _require_postgresql()
    record = _record()
    barrier = Barrier(2)
    _synchronize_after_missing_winner(
        monkeypatch,
        barrier=barrier,
        receipt_id=record.receipt.receipt_id,
    )

    outcomes = _run_two_appends(
        records=(record, record),
        expected_predecessor_hash=None,
    )

    assert len({outcome.backend_pid for outcome in outcomes}) == 2
    assert tuple(outcome.record for outcome in outcomes) == (record, record)
    assert all(outcome.conflict is None for outcome in outcomes)
    assert AccountOwnerAssignmentProvenanceReceiptModel._default_manager.count() == 1
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    assert repository.get_current_head(receipt_id=record.receipt.receipt_id, as_of=_NOW) == record
    assert (
        repository.get_exact_by_hash(
            receipt_id=record.receipt.receipt_id,
            receipt_version=record.receipt.receipt_version,
            expected_content_hash=record.receipt.content_hash,
            as_of=_NOW,
        )
        == record
    )


@pytest.mark.django_db(transaction=True)
def test_postgresql_competing_successors_preserve_one_stable_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent candidates for one predecessor edge cannot both append."""

    _require_postgresql()
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    root = _record()
    with repository.atomic():
        repository.append(
            root,
            expected_predecessor_hash=None,
            recorded_at=root.receipt.recorded_at,
        )

    candidates = (
        _record(
            receipt_version="account-assignment-provenance.v2-a",
            recorded_at=_NOW - timedelta(minutes=5),
            supersedes_content_hash=root.receipt.content_hash,
        ),
        _record(
            receipt_version="account-assignment-provenance.v2-b",
            recorded_at=_NOW - timedelta(minutes=4),
            supersedes_content_hash=root.receipt.content_hash,
        ),
    )
    barrier = Barrier(2)
    _synchronize_after_missing_winner(
        monkeypatch,
        barrier=barrier,
        receipt_id=root.receipt.receipt_id,
    )

    outcomes = _run_two_appends(
        records=candidates,
        expected_predecessor_hash=root.receipt.content_hash,
    )

    assert len({outcome.backend_pid for outcome in outcomes}) == 2
    winners = tuple(outcome.record for outcome in outcomes if outcome.record is not None)
    conflicts = tuple(outcome.conflict for outcome in outcomes if outcome.conflict is not None)
    assert len(winners) == 1
    assert winners[0] in candidates
    assert len(conflicts) == 1
    assert AccountOwnerAssignmentProvenanceReceiptModel._default_manager.count() == 2
    first_head = repository.get_current_head(
        receipt_id=root.receipt.receipt_id,
        as_of=_NOW,
    )
    second_head = repository.get_current_head(
        receipt_id=root.receipt.receipt_id,
        as_of=_NOW,
    )
    assert first_head == second_head == winners[0]
    assert (
        repository.get_exact_by_hash(
            receipt_id=winners[0].receipt.receipt_id,
            receipt_version=winners[0].receipt.receipt_version,
            expected_content_hash=winners[0].receipt.content_hash,
            as_of=_NOW,
        )
        == winners[0]
    )


@pytest.mark.django_db(transaction=True)
def test_postgresql_outer_rollback_removes_append_and_retry_is_one_winner() -> None:
    """A caller rollback removes a nested repository append and permits exact retry."""

    _require_postgresql()
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    record = _record()

    with pytest.raises(_IntentionalRollback):
        with transaction.atomic():
            with repository.atomic():
                repository.append(
                    record,
                    expected_predecessor_hash=None,
                    recorded_at=record.receipt.recorded_at,
                )
            assert AccountOwnerAssignmentProvenanceReceiptModel._default_manager.count() == 1
            raise _IntentionalRollback("force caller rollback after nested append")

    assert AccountOwnerAssignmentProvenanceReceiptModel._default_manager.count() == 0
    with repository.atomic():
        retried = repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=record.receipt.recorded_at,
        )
    assert retried == record
    assert AccountOwnerAssignmentProvenanceReceiptModel._default_manager.count() == 1
    assert (
        repository.get_current_head(
            receipt_id=record.receipt.receipt_id,
            as_of=_NOW,
        )
        == record
    )


@pytest.mark.django_db(transaction=True)
def test_postgresql_nonduplicate_check_failure_keeps_database_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real DB check violation is not translated into a receipt business conflict."""

    _require_postgresql()
    original = repository_module._model_values

    def violate_actor_check(
        record: PersistedAccountOwnerAssignmentProvenanceReceipt,
        *,
        recorded_at: datetime,
    ) -> dict[str, object]:
        values = original(record, recorded_at=recorded_at)
        values["issuer_user_id"] = int(values["issuer_user_id"]) + 1
        return values

    monkeypatch.setattr(repository_module, "_model_values", violate_actor_check)
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    record = _record()

    with pytest.raises(IntegrityError) as captured:
        with repository.atomic():
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=record.receipt.recorded_at,
            )

    assert captured.value.__cause__ is not None
    cause = captured.value.__cause__
    diagnostic = getattr(cause, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if constraint_name is not None:
        assert constraint_name == "acct_prov_receipt_actor_ck"
    else:
        assert "acct_prov_receipt_actor_ck" in str(cause)
    assert AccountOwnerAssignmentProvenanceReceiptModel._default_manager.count() == 0


@pytest.mark.django_db(transaction=True)
def test_postgresql_unrelated_primary_key_failure_does_not_probe_a_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrelated real primary-key failure stays an infrastructure error."""

    _require_postgresql()
    connection = connections["default"]
    table = connection.ops.quote_name("django_migrations")
    fields = tuple(connection.ops.quote_name(name) for name in ("id", "app", "name", "applied"))
    selected_fields = ", ".join(fields)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {fields[0]} FROM {table} ORDER BY {fields[0]} LIMIT 1")
        migration_row = cursor.fetchone()
        assert migration_row is not None
        migration_id = int(migration_row[0])
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        migration_count_before = int(cursor.fetchone()[0])

    original_save = AccountOwnerAssignmentProvenanceReceiptModel.save
    save_calls = 0

    def duplicate_migration_primary_key(
        model: AccountOwnerAssignmentProvenanceReceiptModel,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal save_calls
        save_calls += 1
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {table} ({selected_fields}) "
                f"SELECT {selected_fields} FROM {table} WHERE {fields[0]} = %s",
                [migration_id],
            )
        original_save(model, *args, **kwargs)

    original_exact_model = DjangoAccountOwnerAssignmentProvenanceReceiptRepository._exact_model
    exact_probe_calls = 0

    def count_exact_probe(
        repository: DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
        record: PersistedAccountOwnerAssignmentProvenanceReceipt,
    ) -> object | None:
        nonlocal exact_probe_calls
        exact_probe_calls += 1
        return original_exact_model(repository, record)

    monkeypatch.setattr(
        AccountOwnerAssignmentProvenanceReceiptModel,
        "save",
        duplicate_migration_primary_key,
    )
    monkeypatch.setattr(
        DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
        "_exact_model",
        count_exact_probe,
    )
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    record = _record()

    with pytest.raises(IntegrityError) as captured:
        with repository.atomic():
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=record.receipt.recorded_at,
            )

    assert save_calls == 1
    assert exact_probe_calls == 1
    assert captured.value.__cause__ is not None
    diagnostic = getattr(captured.value.__cause__, "diag", None)
    assert getattr(diagnostic, "table_name", None) == "django_migrations"
    constraint_name = getattr(diagnostic, "constraint_name", None)
    assert isinstance(constraint_name, str) and constraint_name.endswith("_pkey")
    assert AccountOwnerAssignmentProvenanceReceiptModel._default_manager.count() == 0
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        assert int(cursor.fetchone()[0]) == migration_count_before
