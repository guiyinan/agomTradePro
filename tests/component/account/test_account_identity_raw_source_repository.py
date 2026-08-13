"""Component tests for the Account raw identity source append-only ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.account.application.account_identity_raw_source import (
    AccountIdentityRawSourceActor,
    AccountIdentityRawSourceRepository,
    GetExactAccountIdentityRawSource,
    GetExactAccountIdentityRawSourceCommand,
    PersistedAccountIdentityRawSource,
)
from apps.account.domain.account_identity_raw_source import AccountIdentityRawSource
from apps.account.infrastructure.account_identity_raw_source_codec import (
    AccountIdentityRawSourceCodecError,
    decode_account_identity_raw_source_record,
    encode_account_identity_raw_source_record,
)
from apps.account.infrastructure.account_identity_raw_source_models import (
    AccountIdentityRawSourceModel,
)
from apps.account.infrastructure.account_identity_raw_source_repository import (
    DjangoAccountIdentityRawSourceConflict,
    DjangoAccountIdentityRawSourceCorruption,
    DjangoAccountIdentityRawSourceRepository,
)

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, value: datetime = NOW + timedelta(hours=1)) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _actor(**changes: object) -> AccountIdentityRawSourceActor:
    values: dict[str, object] = {
        "actor_id": "account-staff-11",
        "user_id": 11,
        "role": "account_identity_issuer",
    }
    values.update(changes)
    return AccountIdentityRawSourceActor(**values)  # type: ignore[arg-type]


def _source(**changes: object) -> AccountIdentityRawSource:
    values: dict[str, object] = {
        "source_id": "account-identity-source-7",
        "source_version": "account-identity-source.v1",
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "owner_user_id": 19,
        "assignment_state": "authoritative",
        "assignment_evidence_owner": "account",
        "assignment_evidence_artifact_type": "account_owner_assignment_evidence",
        "assignment_evidence_id": "owner-assignment-7",
        "assignment_evidence_version": "owner-assignment.v1",
        "assignment_evidence_content_hash": "a" * 64,
        "row_source_owner": "simulated_trading",
        "row_source_artifact_type": "unified_account_row_observation",
        "row_source_id": "simulated-account-row-7",
        "row_source_version": "row-observation.v3",
        "row_source_content_hash": "b" * 64,
        "observed_at": NOW,
        "recorded_at": NOW + timedelta(seconds=1),
        "row_source_valid_until": NOW + timedelta(minutes=10),
        "ttl_valid_until": NOW + timedelta(minutes=5),
        "valid_until": NOW + timedelta(minutes=5),
        "is_active": True,
    }
    values.update(changes)
    return AccountIdentityRawSource(**values)  # type: ignore[arg-type]


def _successor(
    previous: AccountIdentityRawSource,
    **changes: object,
) -> AccountIdentityRawSource:
    values: dict[str, object] = {
        **{
            field: getattr(previous, field)
            for field in (
                "source_id",
                "account_namespace",
                "account_id",
                "underlying_unified_account_namespace",
                "underlying_unified_account_id",
                "owner_user_id",
                "assignment_state",
                "assignment_evidence_owner",
                "assignment_evidence_artifact_type",
                "assignment_evidence_id",
                "assignment_evidence_version",
                "assignment_evidence_content_hash",
                "row_source_owner",
                "row_source_artifact_type",
                "row_source_id",
                "account_type",
                "is_active",
            )
        },
        "source_version": "account-identity-source.v2",
        "row_source_version": "row-observation.v4",
        "row_source_content_hash": "c" * 64,
        "observed_at": NOW + timedelta(minutes=1),
        "recorded_at": NOW + timedelta(minutes=1, seconds=1),
        "row_source_valid_until": NOW + timedelta(minutes=11),
        "ttl_valid_until": NOW + timedelta(minutes=6),
        "valid_until": NOW + timedelta(minutes=6),
        "supersedes_content_hash": previous.content_hash,
    }
    values.update(changes)
    return AccountIdentityRawSource(**values)  # type: ignore[arg-type]


def _record(
    source: AccountIdentityRawSource | None = None,
    actor: AccountIdentityRawSourceActor | None = None,
) -> PersistedAccountIdentityRawSource:
    return PersistedAccountIdentityRawSource(
        source=source or _source(),
        captured_by=actor or _actor(),
    )


def _repository() -> DjangoAccountIdentityRawSourceRepository:
    return DjangoAccountIdentityRawSourceRepository(clock=_Clock())


def _protocol(repository: AccountIdentityRawSourceRepository) -> AccountIdentityRawSourceRepository:
    return repository


@pytest.mark.django_db(transaction=True)
def test_append_roundtrip_protocol_exact_and_pit() -> None:
    repository = _repository()
    source = _source()
    record = _record(source)

    with repository.atomic():
        persisted = repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=source.recorded_at,
        )

    assert _protocol(repository) is repository
    assert persisted == record
    assert AccountIdentityRawSourceModel._default_manager.count() == 1
    assert (
        repository.get_winner(
            source_id=source.source_id,
            source_version=source.source_version,
            as_of=source.recorded_at,
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            source_id=source.source_id,
            source_version=source.source_version,
            expected_content_hash=source.content_hash,
            as_of=source.recorded_at,
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            source_id=source.source_id,
            source_version=source.source_version,
            expected_content_hash=source.content_hash,
            as_of=source.recorded_at - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_assignment_evidence_actor_and_persisted_seals_are_stored() -> None:
    repository = _repository()
    source = _source()
    with repository.atomic():
        repository.append(
            _record(source), expected_predecessor_hash=None, recorded_at=source.recorded_at
        )

    row = AccountIdentityRawSourceModel._default_manager.get()
    assert row.assignment_evidence_id == "owner-assignment-7"
    assert row.assignment_evidence_content_hash == "a" * 64
    assert row.captured_actor_id == "account-staff-11"
    assert row.persisted_at == row.recorded_at == source.recorded_at
    assert len(row.actor_binding_hash) == len(row.ledger_header_hash) == 64


@pytest.mark.django_db(transaction=True)
def test_chain_current_head_preserves_inactive_and_expired_successor() -> None:
    repository = _repository()
    first = _source(
        row_source_valid_until=NOW + timedelta(minutes=20),
        ttl_valid_until=NOW + timedelta(minutes=20),
        valid_until=NOW + timedelta(minutes=20),
    )
    successor = _successor(
        first,
        is_active=False,
        row_source_valid_until=NOW + timedelta(minutes=2),
        ttl_valid_until=NOW + timedelta(minutes=2),
        valid_until=NOW + timedelta(minutes=2),
    )
    with repository.atomic():
        repository.append(
            _record(first), expected_predecessor_hash=None, recorded_at=first.recorded_at
        )
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=first.content_hash,
            recorded_at=successor.recorded_at,
        )

    head = repository.get_current_head(
        account_namespace=first.account_namespace,
        account_id=first.account_id,
        as_of=NOW + timedelta(minutes=3),
    )
    assert head is not None
    assert head.source == successor
    assert head.source.is_active is False
    assert (
        GetExactAccountIdentityRawSource(repository).execute(
            GetExactAccountIdentityRawSourceCommand(
                source_id=successor.source_id,
                source_version=successor.source_version,
                expected_content_hash=successor.content_hash,
                as_of=NOW + timedelta(minutes=3),
            )
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_private_uow_claim_and_cas_conflicts() -> None:
    repository = _repository()
    source = _source()
    with pytest.raises(DjangoAccountIdentityRawSourceConflict, match="private unit"):
        repository.append(
            _record(source), expected_predecessor_hash=None, recorded_at=source.recorded_at
        )
    with pytest.raises(ValidationError, match="exact insert claim"):
        AccountIdentityRawSourceModel(**_unsafe_values(_record(source))).save(force_insert=True)

    with repository.atomic():
        repository.append(
            _record(source), expected_predecessor_hash=None, recorded_at=source.recorded_at
        )
    successor = _successor(source)
    with repository.atomic(), pytest.raises(DjangoAccountIdentityRawSourceConflict, match="CAS"):
        repository.append(
            _record(successor), expected_predecessor_hash=None, recorded_at=successor.recorded_at
        )


@pytest.mark.django_db(transaction=True)
def test_all_mutation_delete_bulk_and_raw_paths_are_rejected() -> None:
    repository = _repository()
    source = _source()
    with repository.atomic():
        repository.append(
            _record(source), expected_predecessor_hash=None, recorded_at=source.recorded_at
        )
    row = AccountIdentityRawSourceModel._default_manager.get()
    row.owner_user_id = 20
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        AccountIdentityRawSourceModel._default_manager.update(owner_user_id=20)
    with pytest.raises(ValidationError):
        AccountIdentityRawSourceModel._default_manager.bulk_update([row], ["owner_user_id"])
    with pytest.raises(ValidationError):
        AccountIdentityRawSourceModel._default_manager.all().delete()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        AccountIdentityRawSourceModel._default_manager.bulk_create([row])
    with pytest.raises(ValidationError):
        row.save_base(raw=True)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("assignment_evidence_content_hash", "d" * 64, "headers"),
        ("captured_actor_id", "other-staff", "headers"),
        ("actor_binding_hash", "e" * 64, "actor binding"),
        ("ledger_header_hash", "f" * 64, "ledger header"),
    ],
)
def test_assignment_actor_and_header_tamper_fails_closed(
    column: str,
    value: str,
    message: str,
) -> None:
    repository = _repository()
    source = _source()
    with repository.atomic():
        repository.append(
            _record(source), expected_predecessor_hash=None, recorded_at=source.recorded_at
        )
    row = AccountIdentityRawSourceModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE account_identity_raw_source_ledger SET {column} = %s WHERE id = %s",  # noqa: S608
            [value, row.pk],
        )
    with pytest.raises(DjangoAccountIdentityRawSourceCorruption, match=message):
        repository.get_current_head(
            account_namespace=source.account_namespace,
            account_id=source.account_id,
            as_of=source.recorded_at,
        )


@pytest.mark.django_db(transaction=True)
def test_closed_world_double_selector_tamper_cannot_hide_successor() -> None:
    repository = _repository()
    first = _source()
    successor = _successor(first)
    with repository.atomic():
        repository.append(
            _record(first), expected_predecessor_hash=None, recorded_at=first.recorded_at
        )
    with repository.atomic():
        repository.append(
            _record(successor),
            expected_predecessor_hash=first.content_hash,
            recorded_at=successor.recorded_at,
        )
    row = AccountIdentityRawSourceModel._default_manager.get(
        source_version=successor.source_version
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_identity_raw_source_ledger SET account_id = %s, canonical_payload = %s WHERE id = %s",
            ["hidden-account", json.dumps({}), row.pk],
        )
    with pytest.raises(DjangoAccountIdentityRawSourceCorruption, match="canonical payload"):
        repository.get_current_head(
            account_namespace=first.account_namespace,
            account_id=first.account_id,
            as_of=successor.recorded_at,
        )


def test_codec_strict_shape_export_and_migration_are_schema_only() -> None:
    record = _record()
    assert (
        decode_account_identity_raw_source_record(encode_account_identity_raw_source_record(record))
        == record
    )
    with pytest.raises(AccountIdentityRawSourceCodecError, match="shape"):
        decode_account_identity_raw_source_record({"source": {}, "captured_by": {}, "extra": 1})
    from apps.account.infrastructure.models import AccountIdentityRawSourceModel as Exported

    assert Exported is AccountIdentityRawSourceModel
    migration = __import__(
        "apps.account.migrations.0038_account_identity_raw_source_ledger",
        fromlist=["Migration"],
    ).Migration
    assert migration.dependencies == [("account", "0037_account_identity_snapshot_ledger")]
    assert len(migration.operations) == 1
    assert migration.operations[0].__class__.__name__ == "CreateModel"


def _unsafe_values(record: PersistedAccountIdentityRawSource) -> dict[str, object]:
    """Return repository values only for verifying unclaimed inserts are blocked."""

    from apps.account.infrastructure.account_identity_raw_source_repository import _model_values

    return _model_values(record, recorded_at=record.source.recorded_at)
