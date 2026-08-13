"""Component coverage for Account identity snapshot append-only persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations import RunPython, RunSQL

from apps.account.application.account_identity_snapshot import (
    AccountIdentitySnapshotActor,
    AccountIdentitySnapshotRepository,
    GetExactAccountIdentitySnapshot,
    GetExactAccountIdentitySnapshotCommand,
    PersistedAccountIdentitySnapshot,
)
from apps.account.domain.account_identity_snapshot import AccountIdentitySnapshot
from apps.account.infrastructure.account_identity_snapshot_codec import (
    AccountIdentitySnapshotCodecError,
    decode_account_identity_snapshot_record,
    encode_account_identity_snapshot_record,
)
from apps.account.infrastructure.account_identity_snapshot_models import (
    AccountIdentitySnapshotModel,
)
from apps.account.infrastructure.account_identity_snapshot_repository import (
    DjangoAccountIdentitySnapshotConflict,
    DjangoAccountIdentitySnapshotCorruption,
    DjangoAccountIdentitySnapshotRepository,
    DjangoAccountIdentitySnapshotUnavailable,
    _model_values,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _actor(**changes: object) -> AccountIdentitySnapshotActor:
    values: dict[str, object] = {
        "actor_id": "user:19",
        "user_id": 19,
        "role": "account_identity_issuer",
    }
    values.update(changes)
    return AccountIdentitySnapshotActor(**values)  # type: ignore[arg-type]


def _snapshot(**changes: object) -> AccountIdentitySnapshot:
    values: dict[str, object] = {
        "source_id": "account-identity-source-7",
        "source_version": "account-identity-source.v1",
        "account_namespace": "portfolio.transition_plan_account",
        "account_id": "portfolio-account-7",
        "underlying_unified_account_namespace": "simulated_trading.unified_account",
        "underlying_unified_account_id": 7,
        "owner_user_id": 19,
        "provenance_kind": "authoritative",
        "legacy_default_user_assignment": False,
        "underlying_source_id": "simulated-account-row-7",
        "underlying_source_version": "simulated-account-row.v17",
        "underlying_source_content_hash": "7" * 64,
        "underlying_source_recorded_at": NOW - timedelta(minutes=5),
        "underlying_source_valid_until": NOW + timedelta(hours=2),
        "ttl_valid_until": NOW + timedelta(hours=1),
        "issued_at": NOW,
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return AccountIdentitySnapshot(**values)  # type: ignore[arg-type]


def _manual_snapshot(**changes: object) -> AccountIdentitySnapshot:
    values: dict[str, object] = {
        "provenance_kind": "manual_reclaim",
        "legacy_default_user_assignment": True,
        "reclaim_receipt_owner": "account",
        "reclaim_receipt_artifact_type": "account_owner_reclaim_receipt",
        "reclaim_receipt_id": "account-owner-reclaim-7",
        "reclaim_receipt_version": "account-owner-reclaim.v1",
        "reclaim_receipt_content_hash": "a" * 64,
    }
    values.update(changes)
    return _snapshot(**values)


def _record(
    snapshot: AccountIdentitySnapshot | None = None,
    *,
    actor: AccountIdentitySnapshotActor | None = None,
) -> PersistedAccountIdentitySnapshot:
    return PersistedAccountIdentitySnapshot(snapshot or _snapshot(), actor or _actor())


def _successor(previous: AccountIdentitySnapshot) -> AccountIdentitySnapshot:
    return _snapshot(
        source_version="account-identity-source.v2",
        issued_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1),
        supersedes_content_hash=previous.content_hash,
    )


def _repository(
    clock: FixedClock | None = None,
) -> DjangoAccountIdentitySnapshotRepository:
    return DjangoAccountIdentitySnapshotRepository(
        clock=clock or FixedClock(NOW + timedelta(minutes=3))
    )


def _accepts_application_protocol(
    repository: AccountIdentitySnapshotRepository,
) -> AccountIdentitySnapshotRepository:
    return repository


@pytest.mark.django_db
def test_append_round_trip_protocol_actor_and_exact_historical_pit() -> None:
    repository = _repository()
    assert _accepts_application_protocol(repository) is repository
    record = _record()

    with repository.atomic():
        persisted = repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=NOW,
        )

    assert persisted == record
    assert AccountIdentitySnapshotModel._default_manager.count() == 1
    assert (
        decode_account_identity_snapshot_record(encode_account_identity_snapshot_record(record))
        == record
    )
    assert (
        repository.get_winner(
            source_id=record.snapshot.source_id,
            source_version=record.snapshot.source_version,
            as_of=NOW,
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            source_id=record.snapshot.source_id,
            source_version=record.snapshot.source_version,
            expected_content_hash=record.snapshot.content_hash,
            as_of=NOW,
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            source_id=record.snapshot.source_id,
            source_version=record.snapshot.source_version,
            expected_content_hash=record.snapshot.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db
def test_manual_reclaim_persists_exact_receipt_references_without_receipt_fabrication() -> None:
    repository = _repository()
    record = _record(_manual_snapshot())

    with repository.atomic():
        persisted = repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=NOW,
        )

    assert persisted == record
    row = AccountIdentitySnapshotModel._default_manager.get()
    assert row.provenance_kind == "manual_reclaim"
    assert row.legacy_default_user_assignment is True
    assert row.reclaim_receipt_owner == "account"
    assert row.reclaim_receipt_artifact_type == "account_owner_reclaim_receipt"
    assert row.reclaim_receipt_id == "account-owner-reclaim-7"
    assert row.reclaim_receipt_version == "account-owner-reclaim.v1"
    assert row.reclaim_receipt_content_hash == "a" * 64


@pytest.mark.django_db
def test_full_chain_restores_historical_and_latest_heads() -> None:
    repository = _repository()
    root = _snapshot()
    successor = _successor(root)
    with repository.atomic():
        repository.append(_record(root), expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )

    assert repository.get_current_head(
        account_namespace=root.account_namespace,
        account_id=root.account_id,
        as_of=NOW,
    ) == _record(root)
    assert repository.get_current_head(
        account_namespace=root.account_namespace,
        account_id=root.account_id,
        as_of=successor.recorded_at,
    ) == _record(successor)


@pytest.mark.django_db
def test_expired_successor_remains_head_and_application_reader_never_revives_root() -> None:
    repository = _repository(FixedClock(NOW + timedelta(minutes=3)))
    root = _snapshot()
    successor = _snapshot(
        source_version="account-identity-source.v2",
        underlying_source_valid_until=NOW + timedelta(minutes=2),
        ttl_valid_until=NOW + timedelta(minutes=2),
        issued_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=2),
        supersedes_content_hash=root.content_hash,
    )
    with repository.atomic():
        repository.append(_record(root), expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )

    assert repository.get_current_head(
        account_namespace=root.account_namespace,
        account_id=root.account_id,
        as_of=successor.valid_until,
    ) == _record(successor)
    assert (
        GetExactAccountIdentitySnapshot(repository).execute(
            GetExactAccountIdentitySnapshotCommand(
                source_id=successor.source_id,
                source_version=successor.source_version,
                expected_content_hash=successor.content_hash,
                as_of=successor.valid_until,
            )
        )
        is None
    )


@pytest.mark.django_db
def test_private_uow_and_exact_insert_claim_are_required() -> None:
    repository = _repository()
    record = _record()
    with pytest.raises(DjangoAccountIdentitySnapshotConflict, match="private unit"):
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)

    values = _model_values(record, recorded_at=NOW)
    with pytest.raises(ValidationError, match="exact insert claim"):
        AccountIdentitySnapshotModel._default_manager.create(**values)


@pytest.mark.django_db
def test_root_predecessor_and_identity_claims_are_first_winner_cas() -> None:
    repository = _repository()
    root = _snapshot()
    with repository.atomic():
        repository.append(_record(root), expected_predecessor_hash=None, recorded_at=NOW)

    other_root = _snapshot(
        source_id="other-source",
        underlying_source_content_hash="6" * 64,
    )
    with (
        repository.atomic(),
        pytest.raises(DjangoAccountIdentitySnapshotConflict, match="claim"),
    ):
        repository.append(
            _record(other_root),
            expected_predecessor_hash=None,
            recorded_at=NOW,
        )

    identity_conflict = _snapshot(underlying_source_content_hash="5" * 64)
    with (
        repository.atomic(),
        pytest.raises(DjangoAccountIdentitySnapshotConflict, match="first winner"),
    ):
        repository.append(
            _record(identity_conflict),
            expected_predecessor_hash=None,
            recorded_at=NOW,
        )

    successor = _successor(root)
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )
    competing = _snapshot(
        source_id=root.source_id,
        source_version="account-identity-source.v3",
        underlying_source_content_hash="4" * 64,
        issued_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1),
        supersedes_content_hash=root.content_hash,
    )
    with (
        repository.atomic(),
        pytest.raises(DjangoAccountIdentitySnapshotConflict, match="claim"),
    ):
        repository.append(
            _record(competing),
            expected_predecessor_hash=root.content_hash,
            recorded_at=competing.recorded_at,
        )
    assert AccountIdentitySnapshotModel._default_manager.count() == 2


@pytest.mark.django_db
def test_update_delete_bulk_raw_and_unclaimed_paths_are_blocked() -> None:
    repository = _repository()
    record = _record()
    with repository.atomic():
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)
    row = AccountIdentitySnapshotModel._default_manager.get()

    row.owner_user_id = 20
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        AccountIdentitySnapshotModel._default_manager.update(owner_user_id=20)
    with pytest.raises(ValidationError, match="bulk updated"):
        AccountIdentitySnapshotModel._default_manager.bulk_update(
            [row],
            ["owner_user_id"],
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        AccountIdentitySnapshotModel._default_manager.all().delete()
    values = _model_values(record, recorded_at=NOW)
    with pytest.raises(ValidationError, match="exact repository appends"):
        AccountIdentitySnapshotModel._default_manager.bulk_create(
            [AccountIdentitySnapshotModel(**values)]
        )
    raw = AccountIdentitySnapshotModel(**values)
    with pytest.raises(ValidationError, match="append-only"):
        raw.save_base(raw=True)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("column", "replacement", "message"),
    [
        ("issued_actor_id", "user:20", "headers"),
        ("provenance_kind", "manual_reclaim", "headers"),
        ("ledger_header_hash", "0" * 64, "header seal"),
        ("actor_binding_hash", "1" * 64, "actor binding"),
    ],
)
def test_actor_provenance_header_and_ledger_tamper_fail_closed(
    column: str,
    replacement: str,
    message: str,
) -> None:
    repository = _repository()
    record = _record()
    with repository.atomic():
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)
    row = AccountIdentitySnapshotModel._default_manager.get()

    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE account_identity_snapshot_ledger SET {column} = %s WHERE id = %s",
            [replacement, row.pk],
        )
    with pytest.raises(DjangoAccountIdentitySnapshotCorruption, match=message):
        repository.get_winner(
            source_id=record.snapshot.source_id,
            source_version=record.snapshot.source_version,
            as_of=NOW,
        )


@pytest.mark.django_db
def test_manual_reclaim_receipt_reference_tamper_fails_closed() -> None:
    repository = _repository()
    record = _record(_manual_snapshot())
    with repository.atomic():
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)
    row = AccountIdentitySnapshotModel._default_manager.get()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_identity_snapshot_ledger " "SET reclaim_receipt_id = %s WHERE id = %s",
            ["substituted-receipt", row.pk],
        )
    with pytest.raises(DjangoAccountIdentitySnapshotCorruption, match="headers"):
        repository.get_winner(
            source_id=record.snapshot.source_id,
            source_version=record.snapshot.source_version,
            as_of=NOW,
        )


@pytest.mark.django_db
def test_double_logical_selector_tamper_cannot_hide_successor_and_revive_root() -> None:
    repository = _repository()
    root = _snapshot()
    successor = _successor(root)
    with repository.atomic():
        repository.append(_record(root), expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )
    row = AccountIdentitySnapshotModel._default_manager.get(source_version=successor.source_version)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_identity_snapshot_ledger "
            "SET account_namespace = %s, account_id = %s WHERE id = %s",
            ["account.other", "hidden-account", row.pk],
        )

    with pytest.raises(DjangoAccountIdentitySnapshotCorruption, match="headers"):
        repository.get_current_head(
            account_namespace=root.account_namespace,
            account_id=root.account_id,
            as_of=successor.recorded_at,
        )


@pytest.mark.django_db
def test_double_exact_selector_tamper_cannot_hide_identity_and_content_anchors() -> None:
    repository = _repository()
    record = _record()
    with repository.atomic():
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)
    row = AccountIdentitySnapshotModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_identity_snapshot_ledger "
            "SET source_id = %s, content_hash = %s WHERE id = %s",
            ["hidden-source", "9" * 64, row.pk],
        )

    with pytest.raises(DjangoAccountIdentitySnapshotCorruption, match="headers"):
        repository.get_exact_by_hash(
            source_id=record.snapshot.source_id,
            source_version=record.snapshot.source_version,
            expected_content_hash=record.snapshot.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db
def test_noncanonical_payload_persisted_clock_and_future_cutoff_fail_closed() -> None:
    repository = _repository(FixedClock(NOW))
    record = _record()
    with repository.atomic():
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)
    row = AccountIdentitySnapshotModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_identity_snapshot_ledger " "SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(DjangoAccountIdentitySnapshotCorruption, match="payload"):
        repository.get_winner(
            source_id=record.snapshot.source_id,
            source_version=record.snapshot.source_version,
            as_of=NOW,
        )
    with pytest.raises(DjangoAccountIdentitySnapshotUnavailable, match="future"):
        repository.get_current_head(
            account_namespace=record.snapshot.account_namespace,
            account_id=record.snapshot.account_id,
            as_of=NOW + timedelta(microseconds=1),
        )


def test_codec_is_strict_model_export_and_migration_is_schema_only_zero_seed() -> None:
    record = _record()
    payload = encode_account_identity_snapshot_record(record)
    with pytest.raises(AccountIdentitySnapshotCodecError, match="shape"):
        decode_account_identity_snapshot_record({**payload, "unknown": True})

    from apps.account.infrastructure.models import AccountIdentitySnapshotModel as Exported

    assert Exported is AccountIdentitySnapshotModel
    migration = importlib.import_module(
        "apps.account.migrations.0037_account_identity_snapshot_ledger"
    ).Migration
    assert migration.dependencies == [
        (
            "account",
            "0036_assetcategorymodel_account_asset_category_level_positive_and_more",
        )
    ]
    assert migration.operations
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)
