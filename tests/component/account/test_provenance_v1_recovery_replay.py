"""Characterize read-only V1 archive replay through the existing append ledger.

The envelope in this module is a test-only snapshot of rows actually written to
the isolated PostgreSQL test database. It is not a production backup format and
does not prove production backup, retention, or restore readiness.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TypedDict, cast

import pytest
from django.db import connection

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceiptCorruption,
    GetCurrentAccountOwnerAssignmentProvenanceReceipt,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand,
    GetExactAccountOwnerAssignmentProvenanceReceipt,
    GetExactAccountOwnerAssignmentProvenanceReceiptCommand,
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
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_models import (
    AccountOwnerAssignmentProvenanceReceiptModel,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="V1 recovery evidence requires PostgreSQL"
)

_NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
_TEST_ENVELOPE_FORMAT = "test-only.account-provenance-row-snapshot"


class _ArchiveRow(TypedDict):
    """One exact canonical record and its captured database projection."""

    canonical_payload: dict[str, object]
    stored_fields: dict[str, object]


class _ArchiveEnvelope(TypedDict):
    """Test-local envelope for replaying rows through the existing repository."""

    format: str
    receipt_id: str
    as_of: str
    records: list[_ArchiveRow]


class _Clock:
    """Use a fixed aware cutoff for every repository read and append."""

    def now(self) -> datetime:
        return _NOW


class _ArchiveEnvelopeError(ValueError):
    """A test archive snapshot is incomplete, reordered, or inconsistent."""


class _RollbackSeed(Exception):
    """Roll back the source rows after the test captures their envelope."""


def _utc_text(value: datetime) -> str:
    """Encode an aware timestamp without changing its instant."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise _ArchiveEnvelopeError("archive timestamps must be aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc_text(value: object) -> datetime:
    """Decode the exact UTC representation used by the test envelope."""

    if type(value) is not str or not value.endswith("Z"):
        raise _ArchiveEnvelopeError("archive cutoff must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise _ArchiveEnvelopeError("archive cutoff is malformed") from error
    if _utc_text(parsed) != value:
        raise _ArchiveEnvelopeError("archive cutoff is non-canonical")
    return parsed


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise _ArchiveEnvelopeError(f"{field_name} must be an exact mapping")
    return cast(dict[str, object], value)


def _json_value(value: object) -> object:
    """Return a detached JSON value, normalizing only database datetimes."""

    if type(value) is datetime:
        return _utc_text(value)
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True)
        detached: object = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise _ArchiveEnvelopeError("database row contains a non-JSON field") from error
    return detached


def _stored_fields(
    row: AccountOwnerAssignmentProvenanceReceiptModel,
) -> dict[str, object]:
    """Snapshot every stored column except the database-generated primary key."""

    fields: dict[str, object] = {}
    for field in row._meta.concrete_fields:
        if field.primary_key:
            continue
        fields[field.name] = _json_value(getattr(row, field.name))
    return fields


def _expected_stored_field_names() -> set[str]:
    return {
        field.name
        for field in AccountOwnerAssignmentProvenanceReceiptModel._meta.concrete_fields
        if not field.primary_key
    }


def _serialize_test_envelope(
    rows: list[AccountOwnerAssignmentProvenanceReceiptModel], *, as_of: datetime
) -> bytes:
    """Serialize exact row payloads read from the isolated PostgreSQL ledger."""

    if not rows:
        raise _ArchiveEnvelopeError("cannot capture an empty test ledger")
    receipt_id = rows[0].receipt_id
    records: list[_ArchiveRow] = []
    for row in rows:
        payload = row.canonical_payload
        if type(payload) is not dict:
            raise _ArchiveEnvelopeError("stored canonical payload is not a mapping")
        if row.receipt_id != receipt_id:
            raise _ArchiveEnvelopeError("one envelope cannot mix receipt identities")
        records.append(
            {
                "canonical_payload": cast(dict[str, object], _json_value(payload)),
                "stored_fields": _stored_fields(row),
            }
        )
    envelope: _ArchiveEnvelope = {
        "format": _TEST_ENVELOPE_FORMAT,
        "receipt_id": receipt_id,
        "as_of": _utc_text(as_of),
        "records": records,
    }
    return json.dumps(
        envelope,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _load_test_envelope(value: bytes) -> _ArchiveEnvelope:
    """Strictly decode the test-only envelope without inventing record fields."""

    try:
        decoded: object = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _ArchiveEnvelopeError("test archive is not valid UTF-8 JSON") from error
    envelope = _mapping(decoded, "envelope")
    if set(envelope) != {"format", "receipt_id", "as_of", "records"}:
        raise _ArchiveEnvelopeError("test archive has an unexpected envelope shape")
    if envelope["format"] != _TEST_ENVELOPE_FORMAT:
        raise _ArchiveEnvelopeError("test archive format marker is invalid")
    receipt_id = envelope["receipt_id"]
    if type(receipt_id) is not str or not receipt_id:
        raise _ArchiveEnvelopeError("test archive receipt_id is invalid")
    _parse_utc_text(envelope["as_of"])
    raw_records = envelope["records"]
    if type(raw_records) is not list or not raw_records:
        raise _ArchiveEnvelopeError("test archive records must be a nonempty list")
    records: list[_ArchiveRow] = []
    for raw_record in cast(list[object], raw_records):
        record = _mapping(raw_record, "archive record")
        if set(record) != {"canonical_payload", "stored_fields"}:
            raise _ArchiveEnvelopeError("archive record has an unexpected shape")
        canonical_payload = _mapping(record["canonical_payload"], "canonical_payload")
        stored_fields = _mapping(record["stored_fields"], "stored_fields")
        if set(stored_fields) != _expected_stored_field_names():
            raise _ArchiveEnvelopeError("archive stored-field set is incomplete or unexpected")
        records.append(
            {
                "canonical_payload": canonical_payload,
                "stored_fields": stored_fields,
            }
        )
    return {
        "format": _TEST_ENVELOPE_FORMAT,
        "receipt_id": receipt_id,
        "as_of": cast(str, envelope["as_of"]),
        "records": records,
    }


def _replay_test_envelope(
    repository: DjangoAccountOwnerAssignmentProvenanceReceiptRepository, value: bytes
) -> datetime:
    """Replay a captured chain via the existing codec and append-only UOW."""

    envelope = _load_test_envelope(value)
    as_of = _parse_utc_text(envelope["as_of"])
    if as_of > repository.now():
        raise _ArchiveEnvelopeError("archive as_of is later than the repository clock")
    previous_hash: str | None = None
    previous_recorded_at: datetime | None = None
    with repository.atomic():
        for archived_row in envelope["records"]:
            record = decode_account_owner_assignment_provenance_receipt_record(
                archived_row["canonical_payload"]
            )
            receipt = record.receipt
            if receipt.receipt_id != envelope["receipt_id"]:
                raise _ArchiveEnvelopeError("archive record changed receipt identity")
            if receipt.supersedes_content_hash != previous_hash:
                raise _ArchiveEnvelopeError("archive chain is reordered or missing its parent")
            if previous_recorded_at is not None and receipt.recorded_at <= previous_recorded_at:
                raise _ArchiveEnvelopeError("archive chain clocks are not strictly increasing")
            if receipt.recorded_at > as_of:
                raise _ArchiveEnvelopeError("archive record is later than the preserved as_of")
            restored = repository.append(
                record,
                expected_predecessor_hash=previous_hash,
                recorded_at=receipt.recorded_at,
            )
            if restored != record:
                raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                    "replayed archive record changed its exact payload"
                )
            previous_hash = receipt.content_hash
            previous_recorded_at = receipt.recorded_at

        restored_rows = list(
            AccountOwnerAssignmentProvenanceReceiptModel._default_manager.using("default")
            .filter(receipt_id=envelope["receipt_id"])
            .order_by("recorded_at", "pk")
        )
        if len(restored_rows) != len(envelope["records"]):
            raise _ArchiveEnvelopeError("replayed archive row count changed")
        for row, archived_row in zip(restored_rows, envelope["records"], strict=True):
            if _stored_fields(row) != archived_row["stored_fields"]:
                raise _ArchiveEnvelopeError("replayed stored row differs from its archive seal")
    return as_of


def _actor() -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(
        actor_id="ref02-provenance-claimant-19",
        user_id=19,
        role="account_owner_claimant",
    )


def _physical_row() -> PhysicalAccountRowObservation:
    return PhysicalAccountRowObservation(
        observation_id="ref02-physical-row-7",
        observation_version="physical-account-row.v1",
        account_namespace="account",
        account_id="ref02-real-account-7",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=7,
        raw_source_owner="simulated_trading",
        raw_source_artifact_type="simulated_account_row",
        raw_source_id="ref02-simulated-row-7",
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
    receipt_version: str,
    recorded_at: datetime,
    valid_until: datetime,
    supersedes_content_hash: str | None = None,
) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
    row = _physical_row()
    actor = _actor()
    receipt = AccountOwnerAssignmentProvenanceReceipt(
        receipt_id="ref02-provenance-receipt-7",
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
        valid_until=valid_until,
        supersedes_content_hash=supersedes_content_hash,
    )
    return PersistedAccountOwnerAssignmentProvenanceReceipt(receipt, actor)


def _repository() -> DjangoAccountOwnerAssignmentProvenanceReceiptRepository:
    return DjangoAccountOwnerAssignmentProvenanceReceiptRepository(using="default", clock=_Clock())


def _capture_rows_then_rollback(
    repository: DjangoAccountOwnerAssignmentProvenanceReceiptRepository,
) -> bytes:
    """Capture exact PG rows inside a savepoint, then prove the table is empty."""

    envelope: bytes | None = None
    root = _record(
        receipt_version="account-assignment-provenance.v1",
        recorded_at=_NOW - timedelta(minutes=10),
        valid_until=_NOW + timedelta(days=1),
    )
    successor = _record(
        receipt_version="account-assignment-provenance.v2",
        recorded_at=_NOW - timedelta(minutes=5),
        valid_until=_NOW - timedelta(minutes=1),
        supersedes_content_hash=root.receipt.content_hash,
    )
    if root.receipt.identity_hash == successor.receipt.identity_hash:
        raise AssertionError("different receipt versions must keep distinct identities")
    if root.receipt.content_hash == successor.receipt.content_hash:
        raise AssertionError("different receipt versions must keep distinct content hashes")
    try:
        with repository.atomic():
            repository.append(
                root,
                expected_predecessor_hash=None,
                recorded_at=root.receipt.recorded_at,
            )
            repository.append(
                successor,
                expected_predecessor_hash=root.receipt.content_hash,
                recorded_at=successor.receipt.recorded_at,
            )
            source_rows = list(
                AccountOwnerAssignmentProvenanceReceiptModel._default_manager.using("default")
                .filter(receipt_id=root.receipt.receipt_id)
                .order_by("recorded_at", "pk")
            )
            if len(source_rows) != 2:
                raise AssertionError("seed transaction did not create both real PG rows")
            envelope = _serialize_test_envelope(source_rows, as_of=_NOW)
            raise _RollbackSeed
    except _RollbackSeed:
        pass
    if AccountOwnerAssignmentProvenanceReceiptModel._default_manager.using("default").count():
        raise AssertionError("rolled-back source rows remain in the isolated ledger")
    if envelope is None:
        raise AssertionError("test archive was not captured")
    return envelope


@pytest.mark.django_db(transaction=True)
def test_v1_archive_envelope_replays_exact_chain_from_rolled_back_pg_rows() -> None:
    """Replay real isolated rows while preserving immutable V1 history and PIT."""

    assert_native_postgres_test_database()
    repository = _repository()
    model_manager = AccountOwnerAssignmentProvenanceReceiptModel._default_manager.using("default")
    assert model_manager.count() == 0

    archive = _capture_rows_then_rollback(repository)
    assert model_manager.count() == 0
    as_of = _replay_test_envelope(repository, archive)
    assert as_of == _NOW

    root = repository.get_winner(
        receipt_id="ref02-provenance-receipt-7",
        receipt_version="account-assignment-provenance.v1",
        as_of=as_of,
    )
    successor = repository.get_winner(
        receipt_id="ref02-provenance-receipt-7",
        receipt_version="account-assignment-provenance.v2",
        as_of=as_of,
    )
    assert root is not None and successor is not None
    assert root.receipt.receipt_id == successor.receipt.receipt_id
    assert root.receipt.identity_hash != successor.receipt.identity_hash
    assert root.receipt.content_hash != successor.receipt.content_hash
    assert root.receipt.permission == "evidence_only"
    assert root.receipt.status == "inactive"
    assert root.receipt.activation_available is False
    assert root.receipt.must_not_execute is True
    assert successor.receipt.permission == "evidence_only"
    assert successor.receipt.status == "inactive"
    assert successor.receipt.activation_available is False
    assert successor.receipt.must_not_execute is True

    historical_cutoff = successor.receipt.recorded_at - timedelta(microseconds=1)
    historical_head = repository.get_current_head(
        receipt_id=root.receipt.receipt_id,
        as_of=historical_cutoff,
    )
    assert historical_head == root
    assert (
        repository.get_exact_by_hash(
            receipt_id=root.receipt.receipt_id,
            receipt_version=root.receipt.receipt_version,
            expected_content_hash=root.receipt.content_hash,
            as_of=historical_cutoff,
        )
        == root
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=successor.receipt.receipt_id,
            receipt_version=successor.receipt.receipt_version,
            expected_content_hash=successor.receipt.content_hash,
            as_of=as_of,
        )
        is None
    )
    assert (
        repository.get_current_head(
            receipt_id=successor.receipt.receipt_id,
            as_of=as_of,
        )
        == successor
    )

    current_reader = GetCurrentAccountOwnerAssignmentProvenanceReceipt(repository)
    assert (
        current_reader.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt=root.receipt,
                as_of=as_of,
            )
        )
        is None
    )
    assert (
        current_reader.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt=successor.receipt,
                as_of=as_of,
            )
        )
        is None
    )
    exact_reader = GetExactAccountOwnerAssignmentProvenanceReceipt(repository)
    assert (
        exact_reader.execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt_id=root.receipt.receipt_id,
                receipt_version=root.receipt.receipt_version,
                expected_content_hash=root.receipt.content_hash,
                as_of=as_of,
            )
        )
        == root.receipt
    )
    assert (
        exact_reader.execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt_id=successor.receipt.receipt_id,
                receipt_version=successor.receipt.receipt_version,
                expected_content_hash=successor.receipt.content_hash,
                as_of=as_of,
            )
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("tampered_payload", AccountOwnerAssignmentProvenanceReceiptCodecError),
        ("reordered", _ArchiveEnvelopeError),
        ("missing_parent", _ArchiveEnvelopeError),
        ("tampered_row_seal", _ArchiveEnvelopeError),
    ],
)
def test_v1_archive_replay_rejects_bad_history_without_partial_rows(
    mutation: str, expected_error: type[Exception]
) -> None:
    """Reject malformed history and roll back every row of a failed replay."""

    assert_native_postgres_test_database()
    repository = _repository()
    manager = AccountOwnerAssignmentProvenanceReceiptModel._default_manager.using("default")
    assert manager.count() == 0
    archive = _capture_rows_then_rollback(repository)
    envelope = _mapping(json.loads(archive.decode("utf-8")), "envelope")
    records_value = envelope["records"]
    if type(records_value) is not list:
        raise AssertionError("captured archive records should be a list")
    records = cast(list[object], records_value)

    if mutation == "tampered_payload":
        last = _mapping(records[-1], "last record")
        canonical_payload = _mapping(last["canonical_payload"], "canonical payload")
        receipt = _mapping(canonical_payload["receipt"], "receipt payload")
        receipt["content_hash"] = "0" * 64
    elif mutation == "reordered":
        records.reverse()
    elif mutation == "missing_parent":
        del records[0]
    elif mutation == "tampered_row_seal":
        last = _mapping(records[-1], "last record")
        stored_fields = _mapping(last["stored_fields"], "stored fields")
        stored_fields["ledger_header_hash"] = "0" * 64
    else:
        raise AssertionError(f"unknown test mutation: {mutation}")

    changed_archive = json.dumps(
        envelope,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    with pytest.raises(expected_error):
        _replay_test_envelope(repository, changed_archive)
    assert manager.count() == 0
    assert (
        repository.get_current_head(
            receipt_id="ref02-provenance-receipt-7",
            as_of=_NOW,
        )
        is None
    )
