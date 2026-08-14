"""Component coverage for Account physical-row append-only persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations import RunPython, RunSQL

from apps.account.application.physical_account_row_observation import (
    GetCurrentPhysicalAccountRowObservation,
    GetCurrentPhysicalAccountRowObservationCommand,
    GetExactPhysicalAccountRowObservation,
    GetExactPhysicalAccountRowObservationCommand,
    PersistedPhysicalAccountRowObservation,
    PhysicalAccountRowObservationActor,
    PhysicalAccountRowObservationRepository,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
)
from apps.account.infrastructure.physical_account_row_observation_codec import (
    PhysicalAccountRowObservationCodecError,
    decode_physical_account_row_observation_record,
    encode_physical_account_row_observation_record,
)
from apps.account.infrastructure.physical_account_row_observation_models import (
    PhysicalAccountRowObservationModel,
)
from apps.account.infrastructure.physical_account_row_observation_repository import (
    DjangoPhysicalAccountRowObservationConflict,
    DjangoPhysicalAccountRowObservationCorruption,
    DjangoPhysicalAccountRowObservationRepository,
    DjangoPhysicalAccountRowObservationUnavailable,
    _model_values,
)

NOW = datetime(2026, 8, 13, 7, 0, tzinfo=UTC)


@dataclass
class _Clock:
    value: datetime = NOW + timedelta(hours=1)

    def now(self) -> datetime:
        return self.value


def _actor(**changes: object) -> PhysicalAccountRowObservationActor:
    values: dict[str, object] = {
        "actor_id": "account-evidence-staff-17",
        "user_id": 17,
        "role": "account_evidence_recorder",
    }
    values.update(changes)
    return PhysicalAccountRowObservationActor(**values)  # type: ignore[arg-type]


def _observation(**changes: object) -> PhysicalAccountRowObservation:
    values: dict[str, object] = {
        "observation_id": "physical-account-row-observation-7",
        "observation_version": "physical-account-row-observation.v1",
        "account_namespace": "account",
        "account_id": "physical-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "raw_source_owner": "simulated_trading",
        "raw_source_artifact_type": "simulated_account_row",
        "raw_source_id": "simulated-account-row-7",
        "raw_source_version": "simulated-account-row.v3",
        "raw_source_content_hash": "a" * 64,
        "row_user_id": 29,
        "account_type": "real",
        "is_active": True,
        "row_created_at": NOW - timedelta(days=20),
        "row_updated_at": NOW - timedelta(minutes=2),
        "observed_at": NOW,
        "recorded_at": NOW + timedelta(seconds=1),
        "raw_source_valid_until": NOW + timedelta(minutes=10),
        "ttl_valid_until": NOW + timedelta(minutes=5),
        "valid_until": NOW + timedelta(minutes=5),
    }
    values.update(changes)
    return PhysicalAccountRowObservation(**values)  # type: ignore[arg-type]


def _successor(
    previous: PhysicalAccountRowObservation,
    **changes: object,
) -> PhysicalAccountRowObservation:
    values: dict[str, object] = {
        **{
            field_name: getattr(previous, field_name)
            for field_name in (
                "observation_id",
                "account_namespace",
                "account_id",
                "underlying_unified_account_namespace",
                "underlying_unified_account_id",
                "raw_source_owner",
                "raw_source_artifact_type",
                "raw_source_id",
                "row_user_id",
                "account_type",
                "is_active",
                "row_created_at",
            )
        },
        "observation_version": "physical-account-row-observation.v2",
        "raw_source_version": "simulated-account-row.v4",
        "raw_source_content_hash": "b" * 64,
        "row_updated_at": NOW + timedelta(seconds=30),
        "observed_at": NOW + timedelta(minutes=1),
        "recorded_at": NOW + timedelta(minutes=1, seconds=1),
        "raw_source_valid_until": NOW + timedelta(minutes=11),
        "ttl_valid_until": NOW + timedelta(minutes=6),
        "valid_until": NOW + timedelta(minutes=6),
        "supersedes_content_hash": previous.content_hash,
    }
    values.update(changes)
    return PhysicalAccountRowObservation(**values)  # type: ignore[arg-type]


def _record(
    observation: PhysicalAccountRowObservation | None = None,
    *,
    actor: PhysicalAccountRowObservationActor | None = None,
) -> PersistedPhysicalAccountRowObservation:
    return PersistedPhysicalAccountRowObservation(
        observation=observation or _observation(),
        captured_by=actor or _actor(),
    )


def _repository(
    clock: _Clock | None = None,
) -> DjangoPhysicalAccountRowObservationRepository:
    return DjangoPhysicalAccountRowObservationRepository(clock=clock or _Clock())


def _accepts_protocol(
    repository: PhysicalAccountRowObservationRepository,
) -> PhysicalAccountRowObservationRepository:
    return repository


def _current(
    repository: DjangoPhysicalAccountRowObservationRepository,
    observation: PhysicalAccountRowObservation,
    *,
    as_of: datetime,
) -> PersistedPhysicalAccountRowObservation | None:
    return repository.get_current_head(
        account_namespace=observation.account_namespace,
        account_id=observation.account_id,
        underlying_unified_account_namespace=(observation.underlying_unified_account_namespace),
        underlying_unified_account_id=observation.underlying_unified_account_id,
        raw_source_id=observation.raw_source_id,
        as_of=as_of,
    )


@pytest.mark.django_db(transaction=True)
def test_append_roundtrip_protocol_winner_exact_and_historical_pit() -> None:
    repository = _repository()
    record = _record()
    observation = record.observation

    with repository.atomic():
        persisted = repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=observation.recorded_at,
        )

    assert _accepts_protocol(repository) is repository
    assert persisted == record
    assert PhysicalAccountRowObservationModel._default_manager.count() == 1
    assert (
        repository.get_winner(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            as_of=observation.recorded_at,
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            expected_content_hash=observation.content_hash,
            as_of=observation.recorded_at,
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            expected_content_hash=observation.content_hash,
            as_of=observation.recorded_at - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_raw_row_source_actor_identity_content_and_ledger_seals_are_stored() -> None:
    repository = _repository()
    observation = _observation(row_user_id=None, account_type="simulated")
    with repository.atomic():
        repository.append(
            _record(observation),
            expected_predecessor_hash=None,
            recorded_at=observation.recorded_at,
        )

    row = PhysicalAccountRowObservationModel._default_manager.get()
    assert row.row_user_id is None
    assert row.account_type == "simulated"
    assert row.row_created_at == observation.row_created_at
    assert row.row_updated_at == observation.row_updated_at
    assert row.raw_source_id == observation.raw_source_id
    assert row.raw_source_version == observation.raw_source_version
    assert row.raw_source_content_hash == observation.raw_source_content_hash
    assert row.captured_actor_id == "account-evidence-staff-17"
    assert row.identity_hash == observation.identity_hash
    assert row.content_hash == observation.content_hash
    assert row.persisted_at == row.recorded_at == observation.recorded_at
    for value in (
        row.raw_row_hash,
        row.raw_source_binding_hash,
        row.actor_binding_hash,
        row.record_header_hash,
        row.ledger_header_hash,
    ):
        assert len(value) == 64


@pytest.mark.django_db(transaction=True)
def test_full_chain_restores_historical_and_latest_heads() -> None:
    repository = _repository()
    root = _observation()
    successor = _successor(root)
    with repository.atomic():
        repository.append(
            _record(root), expected_predecessor_hash=None, recorded_at=root.recorded_at
        )
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )

    assert _current(repository, root, as_of=root.recorded_at) == _record(root)
    assert _current(repository, root, as_of=successor.recorded_at) == _record(successor)


@pytest.mark.django_db(transaction=True)
def test_inactive_expired_final_head_is_never_replaced_by_the_root() -> None:
    repository = _repository(_Clock(NOW + timedelta(minutes=4)))
    root = _observation(
        raw_source_valid_until=NOW + timedelta(minutes=20),
        ttl_valid_until=NOW + timedelta(minutes=20),
        valid_until=NOW + timedelta(minutes=20),
    )
    successor = _successor(
        root,
        is_active=False,
        raw_source_valid_until=NOW + timedelta(minutes=2),
        ttl_valid_until=NOW + timedelta(minutes=2),
        valid_until=NOW + timedelta(minutes=2),
    )
    with repository.atomic():
        repository.append(
            _record(root), expected_predecessor_hash=None, recorded_at=root.recorded_at
        )
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )

    assert _current(repository, root, as_of=NOW + timedelta(minutes=3)) == _record(successor)
    current_reader = GetCurrentPhysicalAccountRowObservation(repository)
    assert (
        current_reader.execute(
            GetCurrentPhysicalAccountRowObservationCommand.from_observation(
                root,
                as_of=NOW + timedelta(minutes=3),
            )
        )
        is None
    )
    assert (
        GetExactPhysicalAccountRowObservation(repository).execute(
            GetExactPhysicalAccountRowObservationCommand(
                observation_id=successor.observation_id,
                observation_version=successor.observation_version,
                expected_content_hash=successor.content_hash,
                as_of=NOW + timedelta(minutes=3),
            )
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_private_uow_and_exact_insert_claim_are_required() -> None:
    repository = _repository()
    record = _record()
    observation = record.observation
    with pytest.raises(DjangoPhysicalAccountRowObservationConflict, match="private unit"):
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=observation.recorded_at,
        )
    with pytest.raises(ValidationError, match="exact insert claim"):
        PhysicalAccountRowObservationModel._default_manager.create(
            **_model_values(record, recorded_at=observation.recorded_at)
        )


@pytest.mark.django_db(transaction=True)
def test_identity_source_root_and_predecessor_claims_are_first_winner_cas() -> None:
    repository = _repository()
    root = _observation()
    with repository.atomic():
        repository.append(
            _record(root), expected_predecessor_hash=None, recorded_at=root.recorded_at
        )

    identity_conflict = _observation(raw_source_content_hash="c" * 64)
    with (
        repository.atomic(),
        pytest.raises(DjangoPhysicalAccountRowObservationConflict, match="first winner"),
    ):
        repository.append(
            _record(identity_conflict),
            expected_predecessor_hash=None,
            recorded_at=identity_conflict.recorded_at,
        )

    source_conflict = _observation(
        observation_id="other-observation",
        observation_version="other-observation.v1",
    )
    with (
        repository.atomic(),
        pytest.raises(DjangoPhysicalAccountRowObservationConflict, match="first winner"),
    ):
        repository.append(
            _record(source_conflict),
            expected_predecessor_hash=None,
            recorded_at=source_conflict.recorded_at,
        )

    other_root = _observation(
        observation_id="other-root",
        observation_version="other-root.v1",
        raw_source_version="simulated-account-row.other",
        raw_source_content_hash="d" * 64,
    )
    with (
        repository.atomic(),
        pytest.raises(DjangoPhysicalAccountRowObservationConflict, match="claim"),
    ):
        repository.append(
            _record(other_root),
            expected_predecessor_hash=None,
            recorded_at=other_root.recorded_at,
        )

    successor = _successor(root)
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )
    competing = _successor(
        root,
        observation_version="physical-account-row-observation.v3",
        raw_source_version="simulated-account-row.v5",
        raw_source_content_hash="e" * 64,
    )
    with (
        repository.atomic(),
        pytest.raises(DjangoPhysicalAccountRowObservationConflict, match="claim"),
    ):
        repository.append(
            _record(competing),
            expected_predecessor_hash=root.content_hash,
            recorded_at=competing.recorded_at,
        )
    assert PhysicalAccountRowObservationModel._default_manager.count() == 2


@pytest.mark.django_db(transaction=True)
def test_update_delete_bulk_raw_and_unclaimed_write_paths_are_blocked() -> None:
    repository = _repository()
    record = _record()
    observation = record.observation
    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=observation.recorded_at,
        )
    row = PhysicalAccountRowObservationModel._default_manager.get()

    row.row_user_id = 30
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        PhysicalAccountRowObservationModel._default_manager.update(row_user_id=30)
    with pytest.raises(ValidationError, match="bulk updated"):
        PhysicalAccountRowObservationModel._default_manager.bulk_update([row], ["row_user_id"])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        PhysicalAccountRowObservationModel._default_manager.all().delete()
    values = _model_values(record, recorded_at=observation.recorded_at)
    with pytest.raises(ValidationError, match="exact repository appends"):
        PhysicalAccountRowObservationModel._default_manager.bulk_create(
            [PhysicalAccountRowObservationModel(**values)]
        )
    with pytest.raises(ValidationError, match="append-only"):
        PhysicalAccountRowObservationModel(**values).save_base(raw=True)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("column", "replacement", "message"),
    [
        ("row_user_id", 30, "headers"),
        ("raw_source_content_hash", "c" * 64, "headers"),
        ("captured_actor_id", "other-actor", "headers"),
        ("identity_hash", "d" * 64, "headers"),
        ("content_hash", "e" * 64, "headers"),
        ("raw_row_hash", "f" * 64, "raw row seal"),
        ("raw_source_binding_hash", "1" * 64, "source binding seal"),
        ("actor_binding_hash", "2" * 64, "actor binding seal"),
        ("record_header_hash", "3" * 64, "record header seal"),
        ("ledger_header_hash", "4" * 64, "ledger header seal"),
    ],
)
def test_raw_row_source_actor_identity_content_and_header_tamper_fails_closed(
    column: str,
    replacement: object,
    message: str,
) -> None:
    repository = _repository()
    record = _record()
    observation = record.observation
    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=observation.recorded_at,
        )
    row = PhysicalAccountRowObservationModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE account_physical_row_observation_ledger SET {column} = %s WHERE id = %s",  # noqa: S608
            [replacement, row.pk],
        )
    with pytest.raises(DjangoPhysicalAccountRowObservationCorruption, match=message):
        _current(repository, observation, as_of=observation.recorded_at)


@pytest.mark.django_db(transaction=True)
def test_persisted_clock_database_and_restore_seals_reject_tamper() -> None:
    repository = _repository()
    record = _record()
    observation = record.observation
    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=observation.recorded_at,
        )
    row = PhysicalAccountRowObservationModel._default_manager.get()
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE account_physical_row_observation_ledger "
                "SET persisted_at = %s WHERE id = %s",
                [observation.recorded_at + timedelta(seconds=1), row.pk],
            )


@pytest.mark.django_db(transaction=True)
def test_closed_world_selector_tamper_cannot_hide_a_successor() -> None:
    repository = _repository()
    root = _observation()
    successor = _successor(root)
    with repository.atomic():
        repository.append(
            _record(root), expected_predecessor_hash=None, recorded_at=root.recorded_at
        )
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )
    row = PhysicalAccountRowObservationModel._default_manager.get(
        observation_version=successor.observation_version
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_physical_row_observation_ledger "
            "SET account_id = %s, raw_source_id = %s, canonical_payload = %s "
            "WHERE id = %s",
            ["hidden-account", "hidden-source", json.dumps({}), row.pk],
        )
    with pytest.raises(DjangoPhysicalAccountRowObservationCorruption, match="payload"):
        _current(repository, root, as_of=successor.recorded_at)


@pytest.mark.django_db(transaction=True)
def test_closed_world_exact_anchor_tamper_and_future_cutoff_fail_closed() -> None:
    repository = _repository(_Clock(NOW + timedelta(hours=1)))
    record = _record()
    observation = record.observation
    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=observation.recorded_at,
        )
    row = PhysicalAccountRowObservationModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_physical_row_observation_ledger "
            "SET observation_id = %s, observation_version = %s, content_hash = %s "
            "WHERE id = %s",
            ["hidden", "hidden.v1", "9" * 64, row.pk],
        )
    with pytest.raises(DjangoPhysicalAccountRowObservationCorruption, match="headers"):
        repository.get_exact_by_hash(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            expected_content_hash=observation.content_hash,
            as_of=observation.recorded_at,
        )
    with pytest.raises(DjangoPhysicalAccountRowObservationUnavailable, match="future"):
        _current(repository, observation, as_of=NOW + timedelta(hours=1, microseconds=1))


def test_codec_export_and_migration_are_strict_schema_only_zero_seed() -> None:
    record = _record()
    payload = encode_physical_account_row_observation_record(record)
    assert decode_physical_account_row_observation_record(payload) == record
    with pytest.raises(PhysicalAccountRowObservationCodecError, match="shape"):
        decode_physical_account_row_observation_record({**payload, "unknown": True})

    from apps.account.infrastructure.models import PhysicalAccountRowObservationModel as Exported

    assert Exported is PhysicalAccountRowObservationModel
    migration = importlib.import_module(
        "apps.account.migrations.0040_physical_account_row_observation_ledger"
    ).Migration
    assert migration.dependencies == [("account", "0039_account_owner_assignment_evidence_ledger")]
    assert len(migration.operations) == 1
    assert migration.operations[0].__class__.__name__ == "CreateModel"
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)
