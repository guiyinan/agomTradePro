"""Component tests for the Account provenance receipt append-only ledger."""

import importlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.state import ModelState, ProjectState

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceiptConflict,
    AccountOwnerAssignmentProvenanceReceiptCorruption,
    PersistedAccountOwnerAssignmentProvenanceReceipt,
)
from apps.account.domain.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceipt,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_codec import (
    AccountOwnerAssignmentProvenanceReceiptCodecError,
    decode_account_owner_assignment_provenance_receipt_record,
    encode_account_owner_assignment_provenance_receipt_record,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_models import (
    AccountOwnerAssignmentProvenanceReceiptModel,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _actor() -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(
        actor_id="claimant:19", user_id=19, role="account_owner_claimant"
    )


def _row() -> PhysicalAccountRowObservation:
    return PhysicalAccountRowObservation(
        observation_id="physical-account-row-7",
        observation_version="physical-account-row.v1",
        account_namespace="account",
        account_id="real-account-7",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=7,
        raw_source_owner="simulated_trading",
        raw_source_artifact_type="simulated_account_row",
        raw_source_id="simulated-account-row-7",
        raw_source_version="simulated-account-row.v1",
        raw_source_content_hash="a" * 64,
        row_user_id=19,
        account_type="real",
        is_active=True,
        row_created_at=NOW - timedelta(hours=2),
        row_updated_at=NOW - timedelta(hours=1),
        observed_at=NOW - timedelta(minutes=30),
        recorded_at=NOW - timedelta(minutes=20),
        raw_source_valid_until=NOW + timedelta(days=10),
        ttl_valid_until=NOW + timedelta(days=10),
        valid_until=NOW + timedelta(days=10),
    )


def _record(
    *,
    receipt_version: str = "account-assignment-provenance.v1",
    recorded_at: datetime = NOW - timedelta(minutes=10),
    supersedes: str | None = None,
    valid_until: datetime = NOW + timedelta(days=5),
) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
    row = _row()
    actor = _actor()
    receipt = AccountOwnerAssignmentProvenanceReceipt(
        receipt_id="account-assignment-provenance-7",
        receipt_version=receipt_version,
        provenance_kind="creation",
        artifact_type="account_creation_receipt",
        assignment_state="authoritative",
        assigned_owner_user_id=19,
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
        valid_until=valid_until,
        supersedes_content_hash=supersedes,
    )
    return PersistedAccountOwnerAssignmentProvenanceReceipt(receipt, actor)


@pytest.mark.django_db(transaction=True)
def test_codec_append_exact_and_current_roundtrip() -> None:
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    record = _record()
    assert (
        decode_account_owner_assignment_provenance_receipt_record(
            encode_account_owner_assignment_provenance_receipt_record(record)
        )
        == record
    )
    with repository.atomic():
        assert (
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=record.receipt.recorded_at,
            )
            == record
        )
    assert (
        repository.get_winner(
            receipt_id=record.receipt.receipt_id,
            receipt_version=record.receipt.receipt_version,
            as_of=NOW,
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=record.receipt.receipt_id,
            receipt_version=record.receipt.receipt_version,
            expected_content_hash=record.receipt.content_hash,
            as_of=NOW,
        )
        == record
    )
    assert repository.get_current_head(receipt_id=record.receipt.receipt_id, as_of=NOW) == record


@pytest.mark.django_db(transaction=True)
def test_private_uow_first_winner_and_successor_cas() -> None:
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    root = _record()
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptConflict):
        repository.append(
            root, expected_predecessor_hash=None, recorded_at=root.receipt.recorded_at
        )
    with repository.atomic():
        repository.append(
            root, expected_predecessor_hash=None, recorded_at=root.receipt.recorded_at
        )
    successor = _record(
        receipt_version="account-assignment-provenance.v2",
        recorded_at=NOW - timedelta(minutes=5),
        supersedes=root.receipt.content_hash,
    )
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.receipt.content_hash,
            recorded_at=successor.receipt.recorded_at,
        )
    assert repository.get_current_head(receipt_id=root.receipt.receipt_id, as_of=NOW) == successor
    with repository.atomic():
        assert (
            repository.append(
                root,
                expected_predecessor_hash=None,
                recorded_at=root.receipt.recorded_at,
            )
            == root
        )


@pytest.mark.django_db(transaction=True)
def test_expired_successor_remains_logical_head_without_fallback() -> None:
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    root = _record(valid_until=NOW + timedelta(days=1))
    with repository.atomic():
        repository.append(
            root, expected_predecessor_hash=None, recorded_at=root.receipt.recorded_at
        )
    successor = _record(
        receipt_version="account-assignment-provenance.v2",
        recorded_at=NOW - timedelta(minutes=5),
        valid_until=NOW - timedelta(minutes=1),
        supersedes=root.receipt.content_hash,
    )
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.receipt.content_hash,
            recorded_at=successor.receipt.recorded_at,
        )
    assert repository.get_current_head(receipt_id=root.receipt.receipt_id, as_of=NOW) == successor
    assert (
        repository.get_exact_by_hash(
            receipt_id=successor.receipt.receipt_id,
            receipt_version=successor.receipt.receipt_version,
            expected_content_hash=successor.receipt.content_hash,
            as_of=NOW,
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_mutation_bulk_delete_and_noncanonical_codec_are_rejected() -> None:
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    record = _record()
    with repository.atomic():
        repository.append(
            record, expected_predecessor_hash=None, recorded_at=record.receipt.recorded_at
        )
    model = AccountOwnerAssignmentProvenanceReceiptModel._default_manager.get()
    with pytest.raises(ValidationError):
        model.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        AccountOwnerAssignmentProvenanceReceiptModel._default_manager.update(status="bad")
    with pytest.raises(ValidationError):
        model.delete()
    with pytest.raises(ValidationError):
        AccountOwnerAssignmentProvenanceReceiptModel._default_manager.bulk_create([model])
    payload = encode_account_owner_assignment_provenance_receipt_record(record)
    payload["unexpected"] = True
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptCodecError):
        decode_account_owner_assignment_provenance_receipt_record(payload)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "column", ["receipt_id", "content_hash", "row_binding_hash", "ledger_header_hash"]
)
def test_closed_world_restore_rejects_header_and_clock_tamper(column: str) -> None:
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptRepository(clock=_Clock())
    record = _record()
    with repository.atomic():
        repository.append(
            record, expected_predecessor_hash=None, recorded_at=record.receipt.recorded_at
        )
    table = AccountOwnerAssignmentProvenanceReceiptModel._meta.db_table
    value: object = "tampered-value"
    with connection.cursor() as cursor:
        cursor.execute(f'UPDATE "{table}" SET "{column}" = %s', [value])
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptCorruption):
        repository.get_current_head(receipt_id=record.receipt.receipt_id, as_of=NOW)


def test_0041_migration_is_schema_only_and_zero_seed() -> None:
    path = Path(
        "apps/account/migrations/0041_account_owner_assignment_provenance_receipt_ledger.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "CreateModel" in text
    assert "RunPython" not in text
    assert "RunSQL" not in text
    assert "0040_physical_account_row_observation_ledger" in text


def test_0041_migration_state_matches_the_live_ledger_model() -> None:
    module = importlib.import_module(
        "apps.account.migrations.0041_account_owner_assignment_provenance_receipt_ledger"
    )
    operation = module.Migration.operations[0]
    state = ProjectState()
    operation.state_forwards("account", state)
    migrated = state.models[("account", "accountownerassignmentprovenancereceiptmodel")]
    live = ModelState.from_model(AccountOwnerAssignmentProvenanceReceiptModel)
    assert set(migrated.fields) == set(live.fields)
    for field_name in migrated.fields:
        assert (
            migrated.fields[field_name].deconstruct()[1:]
            == live.fields[field_name].deconstruct()[1:]
        )
    assert migrated.options["db_table"] == live.options["db_table"]
    assert [value.deconstruct() for value in migrated.options["indexes"]] == [
        value.deconstruct() for value in live.options["indexes"]
    ]
    assert [value.deconstruct() for value in migrated.options["constraints"]] == [
        value.deconstruct() for value in live.options["constraints"]
    ]
