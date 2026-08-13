"""Component coverage for Broker account identity append-only persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations import RunPython, RunSQL

from apps.broker_execution.application.broker_account_identity_snapshot import (
    BrokerAccountIdentityIssuanceActor,
    BrokerAccountIdentitySnapshotConflict,
    BrokerAccountIdentitySnapshotCorruption,
    BrokerAccountIdentitySnapshotRepository,
    BrokerAccountIdentitySnapshotUnavailable,
    PersistedBrokerAccountIdentitySnapshot,
)
from apps.broker_execution.domain.broker_account_identity_snapshot import (
    AccountIdentitySourceRef,
    BrokerAccountIdentitySnapshot,
    KeyedBrokerAccountReferenceDigest,
)
from apps.broker_execution.infrastructure.broker_account_identity_snapshot_codec import (
    BrokerAccountIdentitySnapshotCodecError,
    decode_broker_account_identity_snapshot,
    encode_broker_account_identity_snapshot,
)
from apps.broker_execution.infrastructure.broker_account_identity_snapshot_models import (
    BrokerAccountIdentitySnapshotModel,
)
from apps.broker_execution.infrastructure.broker_account_identity_snapshot_repository import (
    DjangoBrokerAccountIdentitySnapshotRepository,
    _model_values,
    _validate_closed_world,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_models import (
    _activate_pre_risk_scope_uow,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _snapshot(**changes: object) -> BrokerAccountIdentitySnapshot:
    values: dict[str, object] = {
        "snapshot_id": "broker-account-identity-1",
        "snapshot_version": "v1",
        "broker_account_namespace": "qmt-live",
        "broker_account_id": 42,
        "owner_user_id": 7,
        "account_type": "real",
        "is_active": True,
        "account_source_ref": AccountIdentitySourceRef(
            source_id="account-source-1",
            source_version="v1",
            content_hash="a" * 64,
            account_namespace="account-primary",
            account_id="portfolio-account-alpha",
            owner_user_id=7,
            account_type="real",
            is_active=True,
            recorded_at=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(hours=3),
        ),
        "binding_revision": 3,
        "binding_owner_user_id": 7,
        "binding_content_hash": "b" * 64,
        "agent_id": "agent-1",
        "agent_version": "v4",
        "agent_owner_user_id": 7,
        "agent_content_hash": "c" * 64,
        "qmt_account_ref_digest": KeyedBrokerAccountReferenceDigest(
            algorithm="hmac-sha256", key_id="qmt-key-v2", digest="d" * 64
        ),
        "broker_account_category": "STOCK",
        "issued_at": NOW,
        "recorded_at": NOW,
        "ttl_valid_until": NOW + timedelta(hours=2),
        "valid_until": NOW + timedelta(hours=2),
    }
    values.update(changes)
    return BrokerAccountIdentitySnapshot(**values)  # type: ignore[arg-type]


def _actor(**changes: object) -> BrokerAccountIdentityIssuanceActor:
    values: dict[str, object] = {
        "actor_id": "staff-user-9",
        "user_id": 9,
        "kind": "human",
        "is_staff": True,
    }
    values.update(changes)
    return BrokerAccountIdentityIssuanceActor(**values)  # type: ignore[arg-type]


def _record(
    snapshot: BrokerAccountIdentitySnapshot | None = None,
    actor: BrokerAccountIdentityIssuanceActor | None = None,
) -> PersistedBrokerAccountIdentitySnapshot:
    return PersistedBrokerAccountIdentitySnapshot(snapshot or _snapshot(), actor or _actor())


def _successor(
    previous: BrokerAccountIdentitySnapshot, **changes: object
) -> BrokerAccountIdentitySnapshot:
    values: dict[str, object] = {
        "snapshot_id": "broker-account-identity-2",
        "binding_revision": previous.binding_revision + 1,
        "recorded_at": NOW + timedelta(minutes=1),
        "issued_at": NOW + timedelta(minutes=1),
        "supersedes_snapshot_hash": previous.content_hash,
    }
    values.update(changes)
    return _snapshot(**values)


def _repository(
    clock: FixedClock | None = None,
) -> DjangoBrokerAccountIdentitySnapshotRepository:
    return DjangoBrokerAccountIdentitySnapshotRepository(
        clock=clock or FixedClock(NOW + timedelta(minutes=10))
    )


def _accepts_application_protocol(
    repository: BrokerAccountIdentitySnapshotRepository,
) -> BrokerAccountIdentitySnapshotRepository:
    return repository


@pytest.mark.django_db
def test_append_round_trip_protocol_actor_and_exact_pit() -> None:
    repository = _repository()
    assert _accepts_application_protocol(repository) is repository
    record = _record()
    with repository.atomic():
        persisted = repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)

    assert persisted == record
    assert BrokerAccountIdentitySnapshotModel._default_manager.count() == 1
    assert (
        decode_broker_account_identity_snapshot(
            encode_broker_account_identity_snapshot(record.snapshot)
        )
        == record.snapshot
    )
    assert (
        repository.get_exact_by_hash(
            snapshot_id=record.snapshot.snapshot_id,
            snapshot_version=record.snapshot.snapshot_version,
            expected_content_hash=record.snapshot.content_hash,
            as_of=NOW,
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            snapshot_id=record.snapshot.snapshot_id,
            snapshot_version=record.snapshot.snapshot_version,
            expected_content_hash=record.snapshot.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db
def test_full_chain_current_head_and_expired_successor_never_falls_back() -> None:
    repository = _repository()
    root = _record()
    successor_snapshot = _successor(
        root.snapshot,
        ttl_valid_until=NOW + timedelta(minutes=2),
        valid_until=NOW + timedelta(minutes=2),
    )
    successor = _record(successor_snapshot)
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.snapshot.content_hash,
            recorded_at=successor_snapshot.recorded_at,
        )

    assert (
        repository.get_current_head(
            broker_account_namespace="qmt-live",
            broker_account_id=42,
            as_of=NOW,
        )
        == root
    )
    assert (
        repository.get_current_head(
            broker_account_namespace="qmt-live",
            broker_account_id=42,
            as_of=successor_snapshot.valid_until,
        )
        is None
    )


@pytest.mark.django_db
def test_private_uow_and_foreign_ledger_token_are_rejected() -> None:
    repository = _repository()
    record = _record()
    with pytest.raises(BrokerAccountIdentitySnapshotConflict, match="private unit"):
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)
    foreign_token = object()
    with (
        _activate_pre_risk_scope_uow(foreign_token),
        pytest.raises(BrokerAccountIdentitySnapshotConflict, match="private unit"),
    ):
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)


@pytest.mark.django_db
def test_identity_root_and_predecessor_claims_are_first_winner_only() -> None:
    repository = _repository()
    root = _record()
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)

    conflicting_identity = _record(
        _snapshot(binding_content_hash="e" * 64), _actor(actor_id="staff-user-10")
    )
    with (
        repository.atomic(),
        pytest.raises(BrokerAccountIdentitySnapshotConflict, match="first winner"),
    ):
        repository.append(conflicting_identity, expected_predecessor_hash=None, recorded_at=NOW)
    conflicting_root = _record(_snapshot(snapshot_id="another-root", binding_content_hash="f" * 64))
    with (
        repository.atomic(),
        pytest.raises(BrokerAccountIdentitySnapshotConflict, match="claim"),
    ):
        repository.append(conflicting_root, expected_predecessor_hash=None, recorded_at=NOW)

    successor = _record(_successor(root.snapshot))
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.snapshot.content_hash,
            recorded_at=successor.snapshot.recorded_at,
        )
    competing = _record(
        _successor(
            root.snapshot,
            snapshot_id="competing-successor",
            binding_content_hash="0" * 64,
        )
    )
    with (
        repository.atomic(),
        pytest.raises(BrokerAccountIdentitySnapshotConflict, match="claim"),
    ):
        repository.append(
            competing,
            expected_predecessor_hash=root.snapshot.content_hash,
            recorded_at=competing.snapshot.recorded_at,
        )


@pytest.mark.django_db
def test_direct_save_update_delete_bulk_raw_and_unclaimed_create_are_blocked() -> None:
    repository = _repository()
    record = _record()
    with repository.atomic():
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerAccountIdentitySnapshotModel._default_manager.get()

    row.agent_id = "tampered"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        BrokerAccountIdentitySnapshotModel._default_manager.update(agent_id="tampered")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        BrokerAccountIdentitySnapshotModel._default_manager.all().delete()
    values = _model_values(record, recorded_at=NOW)
    with pytest.raises(ValidationError, match="exact insert claim"):
        BrokerAccountIdentitySnapshotModel._default_manager.create(**values)
    with pytest.raises(ValidationError, match="exact repository appends"):
        BrokerAccountIdentitySnapshotModel._default_manager.bulk_create(
            [BrokerAccountIdentitySnapshotModel(**values)]
        )
    with pytest.raises(ValidationError, match="append-only"):
        BrokerAccountIdentitySnapshotModel(**values).save_base(raw=True)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("actor_id", "substituted-actor"),
        ("account_id", "substituted-account"),
        ("binding_content_hash", "9" * 64),
        ("agent_content_hash", "8" * 64),
        ("qmt_digest", "7" * 64),
        ("persisted_at", NOW + timedelta(seconds=1)),
    ],
)
def test_actor_source_and_persistence_header_tamper_fail_closed(
    column: str, replacement: object
) -> None:
    repository = _repository()
    record = _record()
    with repository.atomic():
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerAccountIdentitySnapshotModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE broker_execution_account_identity_snapshot SET {column} = %s WHERE id = %s",
            [replacement, row.pk],
        )
    with pytest.raises(BrokerAccountIdentitySnapshotCorruption):
        repository.get_identity_winner(
            snapshot_id=record.snapshot.snapshot_id,
            snapshot_version=record.snapshot.snapshot_version,
            as_of=NOW,
        )


@pytest.mark.django_db
def test_double_chain_and_exact_selector_tamper_cannot_hide_rows() -> None:
    repository = _repository()
    root = _record()
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerAccountIdentitySnapshotModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_account_identity_snapshot "
            "SET broker_account_namespace = %s, broker_account_id = %s, "
            "snapshot_id = %s, content_hash = %s WHERE id = %s",
            ["hidden", 99, "hidden-id", "9" * 64, row.pk],
        )

    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="headers"):
        repository.get_current_head(
            broker_account_namespace="qmt-live", broker_account_id=42, as_of=NOW
        )
    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="headers"):
        repository.get_exact_by_hash(
            snapshot_id=root.snapshot.snapshot_id,
            snapshot_version=root.snapshot.snapshot_version,
            expected_content_hash=root.snapshot.content_hash,
            as_of=NOW,
        )


def test_closed_world_rejects_orphan_fork_and_cross_account_link() -> None:
    root = _record()
    orphan = _record(_successor(root.snapshot, supersedes_snapshot_hash="9" * 64))
    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="missing"):
        _validate_closed_world((orphan,))

    first = _record(_successor(root.snapshot))
    second = _record(_successor(root.snapshot, snapshot_id="fork", binding_content_hash="8" * 64))
    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="multiple"):
        _validate_closed_world((root, first, second))

    cross_account = _record(
        _successor(
            root.snapshot,
            snapshot_id="cross-account",
            broker_account_namespace="other-broker",
            broker_account_id=43,
        )
    )
    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="link"):
        _validate_closed_world((root, cross_account))


@pytest.mark.django_db
def test_noncanonical_payload_and_future_cutoff_fail_closed() -> None:
    repository = _repository(FixedClock(NOW))
    record = _record()
    with repository.atomic():
        repository.append(record, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerAccountIdentitySnapshotModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_account_identity_snapshot "
            "SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="canonical"):
        repository.get_identity_winner(
            snapshot_id=record.snapshot.snapshot_id,
            snapshot_version=record.snapshot.snapshot_version,
            as_of=NOW,
        )
    with pytest.raises(BrokerAccountIdentitySnapshotUnavailable, match="future"):
        repository.get_current_head(
            broker_account_namespace="qmt-live",
            broker_account_id=42,
            as_of=NOW + timedelta(microseconds=1),
        )


def test_codec_strict_and_migration_schema_only_zero_seed() -> None:
    payload = encode_broker_account_identity_snapshot(_snapshot())
    with pytest.raises(BrokerAccountIdentitySnapshotCodecError, match="shape"):
        decode_broker_account_identity_snapshot({**payload, "unknown": True})

    migration = importlib.import_module(
        "apps.broker_execution.migrations.0010_broker_account_identity_snapshot"
    ).Migration
    assert migration.dependencies == [("broker_execution", "0009_pre_risk_execution_scope")]
    assert migration.operations
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)
