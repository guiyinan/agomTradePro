"""Component coverage for Account owner-assignment append-only persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations import CreateModel, RunPython, RunSQL

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentRepository,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentSubject,
    ExactAccountAssignmentProvenanceReceipt,
    ExactAccountRowObservation,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
    AccountOwnerAssignmentEvidence,
)
from apps.account.infrastructure.account_owner_assignment_evidence_codec import (
    AccountOwnerAssignmentEvidenceCodecError,
    decode_account_owner_assignment_evidence,
    decode_account_owner_assignment_subject,
    encode_account_owner_assignment_evidence,
    encode_account_owner_assignment_subject,
)
from apps.account.infrastructure.account_owner_assignment_evidence_models import (
    AccountOwnerAssignmentEvidenceModel,
    AccountOwnerAssignmentSubjectModel,
)
from apps.account.infrastructure.account_owner_assignment_evidence_repository import (
    DjangoAccountOwnerAssignmentConflict,
    DjangoAccountOwnerAssignmentCorruption,
    DjangoAccountOwnerAssignmentRepository,
    DjangoAccountOwnerAssignmentUnavailable,
    _evidence_model_values,
    _subject_model_values,
)

NOW = datetime(2026, 8, 13, 9, tzinfo=UTC)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _server_actor(
    actor_id: str,
    user_id: int,
    *,
    role: str,
    is_staff: bool,
) -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(
        actor_id=actor_id,
        user_id=user_id,
        role=role,
        is_staff=is_staff,
    )


def _domain_actor(
    actor_id: str,
    user_id: int,
    *,
    role: str,
    is_staff: bool,
) -> AccountOwnerAssignmentActor:
    return AccountOwnerAssignmentActor(
        actor_id=actor_id,
        user_id=user_id,
        role=role,
        is_staff=is_staff,
    )


def _subject(
    *,
    evidence_version: str = "1",
    requested_at: datetime = NOW,
    valid_until: datetime | None = None,
    row_hash_digit: str = "1",
    receipt_hash_digit: str = "2",
) -> AccountOwnerAssignmentSubject:
    end = valid_until or requested_at + timedelta(hours=5)
    claimant = _server_actor(
        "user:41",
        41,
        role="account_owner_claimant",
        is_staff=False,
    )
    row = ExactAccountRowObservation(
        observation_id="unified-account-row:7",
        observation_version=f"row.v{evidence_version}",
        content_hash=row_hash_digit * 64,
        account_namespace="account",
        account_id="account:7",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=7,
        observed_at=requested_at - timedelta(minutes=3),
        recorded_at=requested_at - timedelta(minutes=2),
        valid_until=end,
    )
    receipt = ExactAccountAssignmentProvenanceReceipt(
        receipt_id=f"account-creation:7:{evidence_version}",
        receipt_version=f"receipt.v{evidence_version}",
        content_hash=receipt_hash_digit * 64,
        provenance_kind="creation",
        assignment_state="authoritative",
        assigned_owner_user_id=41,
        account_namespace=row.account_namespace,
        account_id=row.account_id,
        underlying_unified_account_namespace=row.underlying_unified_account_namespace,
        underlying_unified_account_id=row.underlying_unified_account_id,
        row_observation_id=row.observation_id,
        row_observation_version=row.observation_version,
        row_observation_content_hash=row.content_hash,
        claimant_actor_id=claimant.actor_id,
        claimant_user_id=claimant.user_id,
        claimant_role=claimant.role,
        claimant_kind=claimant.kind,
        claimant_is_staff=claimant.is_staff,
        issued_at=requested_at - timedelta(minutes=2),
        recorded_at=requested_at - timedelta(minutes=1),
        valid_until=end,
    )
    return AccountOwnerAssignmentSubject(
        evidence_id="account-owner-assignment:7",
        evidence_version=evidence_version,
        row=row,
        receipt=receipt,
        claimant=claimant,
        requested_at=requested_at,
        valid_until=end,
    )


def _evidence(
    subject: AccountOwnerAssignmentSubject,
    *,
    approved_at: datetime | None = None,
    valid_until: datetime | None = None,
    supersedes: str | None = None,
) -> AccountOwnerAssignmentEvidence:
    at = approved_at or subject.requested_at
    row = subject.row
    receipt = subject.receipt
    return AccountOwnerAssignmentEvidence(
        evidence_id=subject.evidence_id,
        evidence_version=subject.evidence_version,
        account_namespace=row.account_namespace,
        account_id=row.account_id,
        underlying_unified_account_namespace=row.underlying_unified_account_namespace,
        underlying_unified_account_id=row.underlying_unified_account_id,
        assignment_state=receipt.assignment_state,
        assigned_owner_user_id=receipt.assigned_owner_user_id,
        row_observation_owner=row.owner,
        row_observation_artifact_type=row.artifact_type,
        row_observation_id=row.observation_id,
        row_observation_version=row.observation_version,
        row_observation_content_hash=row.content_hash,
        provenance_kind=receipt.provenance_kind,
        provenance_ref_owner=receipt.owner,
        provenance_ref_artifact_type=receipt.artifact_type,
        provenance_ref_id=receipt.receipt_id,
        provenance_ref_version=receipt.receipt_version,
        provenance_ref_content_hash=receipt.content_hash,
        subject_content_hash=subject.content_hash,
        claimant=subject.claimant.to_domain(),
        approved_by=_domain_actor(
            "user:99",
            99,
            role="account_owner_approver",
            is_staff=True,
        ),
        issued_at=subject.requested_at,
        approved_at=at,
        recorded_at=at,
        valid_until=valid_until or subject.valid_until,
        supersedes_content_hash=supersedes,
    )


def _repository(
    clock: FixedClock | None = None,
) -> DjangoAccountOwnerAssignmentRepository:
    return DjangoAccountOwnerAssignmentRepository(
        clock=clock or FixedClock(NOW + timedelta(hours=6))
    )


def _accepts_protocol(
    repository: AccountOwnerAssignmentRepository,
) -> AccountOwnerAssignmentRepository:
    return repository


def _append_pair(
    repository: DjangoAccountOwnerAssignmentRepository,
    subject: AccountOwnerAssignmentSubject,
    evidence: AccountOwnerAssignmentEvidence,
    *,
    predecessor: str | None,
) -> None:
    with repository.atomic():
        assert repository.append_subject(subject, recorded_at=subject.requested_at) == subject
        assert (
            repository.append(
                evidence,
                expected_predecessor_hash=predecessor,
                recorded_at=evidence.recorded_at,
            )
            == evidence
        )


@pytest.mark.django_db
def test_two_table_round_trip_protocol_exact_pit_and_complete_subject_seals() -> None:
    repository = _repository()
    assert _accepts_protocol(repository) is repository
    subject = _subject()
    evidence = _evidence(subject)

    _append_pair(repository, subject, evidence, predecessor=None)

    assert AccountOwnerAssignmentSubjectModel._default_manager.count() == 1
    assert AccountOwnerAssignmentEvidenceModel._default_manager.count() == 1
    subject_row = AccountOwnerAssignmentSubjectModel._default_manager.get()
    evidence_row = AccountOwnerAssignmentEvidenceModel._default_manager.get()
    assert subject_row.row_content_hash == subject.row.content_hash
    assert subject_row.receipt_content_hash == subject.receipt.content_hash
    assert subject_row.claimant_user_id == subject.claimant.user_id
    assert evidence_row.subject_id == subject_row.pk
    assert evidence_row.subject_content_hash == subject.content_hash
    assert (
        decode_account_owner_assignment_subject(encode_account_owner_assignment_subject(subject))
        == subject
    )
    assert (
        decode_account_owner_assignment_evidence(encode_account_owner_assignment_evidence(evidence))
        == evidence
    )
    assert (
        repository.get_subject_winner(
            evidence_id=subject.evidence_id,
            evidence_version=subject.evidence_version,
            as_of=NOW,
        )
        == subject
    )
    assert (
        repository.get_exact_by_hash(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            expected_content_hash=evidence.content_hash,
            as_of=NOW,
        )
        == evidence
    )
    assert (
        repository.get_exact_by_hash(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            expected_content_hash=evidence.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db
def test_private_uow_exact_insert_claim_and_all_mutation_shortcuts_are_blocked() -> None:
    repository = _repository()
    subject = _subject()
    evidence = _evidence(subject)
    with pytest.raises(DjangoAccountOwnerAssignmentConflict, match="private unit"):
        repository.append_subject(subject, recorded_at=NOW)

    subject_values = _subject_model_values(subject, recorded_at=NOW)
    with pytest.raises(ValidationError, match="exact insert claim"):
        AccountOwnerAssignmentSubjectModel._default_manager.create(**subject_values)
    private_queryset = AccountOwnerAssignmentSubjectModel._default_manager.all()
    with pytest.raises(ValidationError, match="private insert"):
        private_queryset._insert([], [])
    with pytest.raises(ValidationError, match="private bulk insert"):
        private_queryset._batched_insert([], [], 1)

    _append_pair(repository, subject, evidence, predecessor=None)
    evidence_row = AccountOwnerAssignmentEvidenceModel._default_manager.get()
    evidence_row.account_id = "substituted"
    with pytest.raises(ValidationError, match="append-only"):
        evidence_row.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        AccountOwnerAssignmentEvidenceModel._default_manager.update(account_id="substituted")
    with pytest.raises(ValidationError, match="bulk updated"):
        AccountOwnerAssignmentEvidenceModel._default_manager.bulk_update(
            [evidence_row], ["account_id"]
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        evidence_row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        AccountOwnerAssignmentEvidenceModel._default_manager.all().delete()
    evidence_values = _evidence_model_values(
        evidence,
        subject_id=AccountOwnerAssignmentSubjectModel._default_manager.get().pk,
        recorded_at=NOW,
    )
    with pytest.raises(ValidationError, match="exact repository appends"):
        AccountOwnerAssignmentEvidenceModel._default_manager.bulk_create(
            [AccountOwnerAssignmentEvidenceModel(**evidence_values)]
        )
    raw = AccountOwnerAssignmentEvidenceModel(**evidence_values)
    with pytest.raises(ValidationError, match="append-only"):
        raw.save_base(raw=True)


@pytest.mark.django_db
def test_subject_identity_and_definition_anchors_are_first_winner() -> None:
    repository = _repository()
    subject = _subject()
    with repository.atomic():
        assert repository.append_subject(subject, recorded_at=NOW) == subject
        assert repository.append_subject(subject, recorded_at=NOW) == subject

    conflicting_identity = _subject(row_hash_digit="3")
    with (
        repository.atomic(),
        pytest.raises(DjangoAccountOwnerAssignmentConflict, match="first winner"),
    ):
        repository.append_subject(conflicting_identity, recorded_at=NOW)

    conflicting_row = _subject(
        evidence_version="different",
        row_hash_digit="1",
        receipt_hash_digit="4",
    )
    conflicting_row = AccountOwnerAssignmentSubject(
        evidence_id=conflicting_row.evidence_id,
        evidence_version=conflicting_row.evidence_version,
        row=subject.row,
        receipt=conflicting_row.receipt,
        claimant=conflicting_row.claimant,
        requested_at=conflicting_row.requested_at,
        valid_until=conflicting_row.valid_until,
    )
    with (
        repository.atomic(),
        pytest.raises(DjangoAccountOwnerAssignmentConflict, match="definition"),
    ):
        repository.append_subject(conflicting_row, recorded_at=NOW)


@pytest.mark.django_db
def test_identity_root_and_predecessor_cas_and_full_historical_chain() -> None:
    repository = _repository()
    root_subject = _subject()
    root = _evidence(root_subject)
    _append_pair(repository, root_subject, root, predecessor=None)

    second_at = NOW + timedelta(hours=1)
    successor_subject = _subject(
        evidence_version="2",
        requested_at=second_at,
        row_hash_digit="3",
        receipt_hash_digit="4",
    )
    successor = _evidence(
        successor_subject,
        approved_at=second_at,
        supersedes=root.content_hash,
    )
    _append_pair(repository, successor_subject, successor, predecessor=root.content_hash)

    assert (
        repository.get_current_head(
            account_namespace=root.account_namespace,
            account_id=root.account_id,
            underlying_unified_account_namespace=root.underlying_unified_account_namespace,
            underlying_unified_account_id=root.underlying_unified_account_id,
            row_observation_id=root.row_observation_id,
            as_of=NOW,
        )
        == root
    )
    assert (
        repository.get_current_head(
            account_namespace=root.account_namespace,
            account_id=root.account_id,
            underlying_unified_account_namespace=root.underlying_unified_account_namespace,
            underlying_unified_account_id=root.underlying_unified_account_id,
            row_observation_id=root.row_observation_id,
            as_of=second_at,
        )
        == successor
    )

    third_at = NOW + timedelta(hours=2)
    stale_subject = _subject(
        evidence_version="3",
        requested_at=third_at,
        row_hash_digit="5",
        receipt_hash_digit="6",
    )
    stale = _evidence(
        stale_subject,
        approved_at=third_at,
        supersedes=root.content_hash,
    )
    with repository.atomic():
        repository.append_subject(stale_subject, recorded_at=third_at)
        with pytest.raises(
            DjangoAccountOwnerAssignmentConflict,
            match="first winner|head changed",
        ):
            repository.append(
                stale,
                expected_predecessor_hash=root.content_hash,
                recorded_at=third_at,
            )


@pytest.mark.django_db
def test_expired_final_successor_never_falls_back_to_still_valid_root() -> None:
    repository = _repository(FixedClock(NOW + timedelta(hours=4)))
    root_subject = _subject(valid_until=NOW + timedelta(hours=5))
    root = _evidence(root_subject)
    _append_pair(repository, root_subject, root, predecessor=None)
    second_at = NOW + timedelta(hours=1)
    successor_subject = _subject(
        evidence_version="2",
        requested_at=second_at,
        valid_until=NOW + timedelta(hours=2),
        row_hash_digit="3",
        receipt_hash_digit="4",
    )
    successor = _evidence(
        successor_subject,
        approved_at=second_at,
        valid_until=NOW + timedelta(hours=2),
        supersedes=root.content_hash,
    )
    _append_pair(repository, successor_subject, successor, predecessor=root.content_hash)

    cutoff = successor.valid_until
    assert (
        repository.get_current_head(
            account_namespace=root.account_namespace,
            account_id=root.account_id,
            underlying_unified_account_namespace=root.underlying_unified_account_namespace,
            underlying_unified_account_id=root.underlying_unified_account_id,
            row_observation_id=root.row_observation_id,
            as_of=cutoff,
        )
        == successor
    )
    assert (
        repository.get_exact_by_hash(
            evidence_id=successor.evidence_id,
            evidence_version=successor.evidence_version,
            expected_content_hash=successor.content_hash,
            as_of=cutoff,
        )
        is None
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("table", "column", "replacement", "message"),
    [
        (
            "account_owner_assignment_evidence",
            "approved_role",
            "substituted-role",
            "evidence headers",
        ),
        (
            "account_owner_assignment_subject",
            "row_binding_hash",
            "0" * 64,
            "row binding",
        ),
        (
            "account_owner_assignment_evidence",
            "subject_content_hash",
            "1" * 64,
            "evidence headers",
        ),
        (
            "account_owner_assignment_evidence",
            "ledger_header_hash",
            "2" * 64,
            "ledger header",
        ),
    ],
)
def test_subject_evidence_actor_provenance_and_hash_tamper_fail_closed(
    table: str,
    column: str,
    replacement: str,
    message: str,
) -> None:
    repository = _repository()
    subject = _subject()
    evidence = _evidence(subject)
    _append_pair(repository, subject, evidence, predecessor=None)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET {column} = %s", [replacement])

    with pytest.raises(DjangoAccountOwnerAssignmentCorruption, match=message):
        repository.get_current_head(
            account_namespace=evidence.account_namespace,
            account_id=evidence.account_id,
            underlying_unified_account_namespace=(evidence.underlying_unified_account_namespace),
            underlying_unified_account_id=evidence.underlying_unified_account_id,
            row_observation_id=evidence.row_observation_id,
            as_of=NOW,
        )


@pytest.mark.django_db
def test_double_selector_tamper_cannot_hide_successor_or_revive_root() -> None:
    repository = _repository()
    root_subject = _subject()
    root = _evidence(root_subject)
    _append_pair(repository, root_subject, root, predecessor=None)
    second_at = NOW + timedelta(hours=1)
    successor_subject = _subject(
        evidence_version="2",
        requested_at=second_at,
        row_hash_digit="3",
        receipt_hash_digit="4",
    )
    successor = _evidence(
        successor_subject,
        approved_at=second_at,
        supersedes=root.content_hash,
    )
    _append_pair(repository, successor_subject, successor, predecessor=root.content_hash)
    row = AccountOwnerAssignmentEvidenceModel._default_manager.get(evidence_version="2")
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_owner_assignment_evidence "
            "SET account_id = %s, row_observation_id = %s WHERE id = %s",
            ["hidden-account", "hidden-row", row.pk],
        )

    with pytest.raises(DjangoAccountOwnerAssignmentCorruption, match="headers"):
        repository.get_current_head(
            account_namespace=root.account_namespace,
            account_id=root.account_id,
            underlying_unified_account_namespace=(root.underlying_unified_account_namespace),
            underlying_unified_account_id=root.underlying_unified_account_id,
            row_observation_id=root.row_observation_id,
            as_of=second_at,
        )


@pytest.mark.django_db
def test_noncanonical_payload_clock_and_future_cutoff_fail_closed() -> None:
    repository = _repository(FixedClock(NOW))
    subject = _subject()
    evidence = _evidence(subject)
    _append_pair(repository, subject, evidence, predecessor=None)
    row = AccountOwnerAssignmentEvidenceModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_owner_assignment_evidence SET canonical_payload = %s " "WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(DjangoAccountOwnerAssignmentCorruption, match="payload"):
        repository.get_winner(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            as_of=NOW,
        )
    with pytest.raises(DjangoAccountOwnerAssignmentUnavailable, match="future"):
        repository.get_current_head(
            account_namespace=evidence.account_namespace,
            account_id=evidence.account_id,
            underlying_unified_account_namespace=(evidence.underlying_unified_account_namespace),
            underlying_unified_account_id=evidence.underlying_unified_account_id,
            row_observation_id=evidence.row_observation_id,
            as_of=NOW + timedelta(microseconds=1),
        )


def test_codec_model_exports_and_migration_are_strict_schema_only_zero_seed() -> None:
    subject = _subject()
    payload = encode_account_owner_assignment_subject(subject)
    with pytest.raises(AccountOwnerAssignmentEvidenceCodecError, match="shape"):
        decode_account_owner_assignment_subject({**payload, "unknown": True})

    evidence = _evidence(subject)
    evidence_payload = encode_account_owner_assignment_evidence(evidence)
    with pytest.raises(AccountOwnerAssignmentEvidenceCodecError, match="invalid"):
        decode_account_owner_assignment_evidence({**evidence_payload, "activation_available": True})

    from apps.account.infrastructure.models import (
        AccountOwnerAssignmentEvidenceModel as ExportedEvidence,
    )
    from apps.account.infrastructure.models import (
        AccountOwnerAssignmentSubjectModel as ExportedSubject,
    )

    assert ExportedSubject is AccountOwnerAssignmentSubjectModel
    assert ExportedEvidence is AccountOwnerAssignmentEvidenceModel
    migration = importlib.import_module(
        "apps.account.migrations.0039_account_owner_assignment_evidence_ledger"
    ).Migration
    assert migration.dependencies == [("account", "0038_account_identity_raw_source_ledger")]
    assert len(migration.operations) == 2
    assert all(isinstance(operation, CreateModel) for operation in migration.operations)
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)
