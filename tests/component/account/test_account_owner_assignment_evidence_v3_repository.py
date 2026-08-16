"""Minimal component proof for the independent Evidence-v3 ledgers."""

from __future__ import annotations

from datetime import datetime
from importlib import import_module

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v3_models import (
    AccountOwnerAssignmentEvidenceV3Model,
    AccountOwnerAssignmentSubjectV3Model,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v3_repository import (
    DjangoAccountOwnerAssignmentEvidenceV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationConsumptionClaimModel,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v3_repository import (
    _record,
)
from tests.unit.account.test_account_owner_assignment_evidence_v3 import _evidence, _subject
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import _at


class _Clock:
    def now(self) -> datetime:
        return _at(16)


@pytest.mark.django_db(transaction=True)
def test_subject_evidence_roundtrip_and_permanent_exact_history() -> None:
    receipt_record = _record()
    receipts = DjangoAccountOwnerAssignmentEvidenceV3Repository(clock=_Clock())._receipts
    with receipts.atomic():
        receipts.append(
            receipt_record,
            expected_predecessor_hash=None,
            recorded_at=receipt_record.receipt.recorded_at,
        )
    subject = _subject(receipt_record.receipt)
    evidence = _evidence(subject)
    repository = DjangoAccountOwnerAssignmentEvidenceV3Repository(clock=_Clock())
    with repository.atomic():
        assert repository.append_subject(subject, recorded_at=subject.requested_at) == subject
    with repository.atomic():
        assert (
            repository.append_root(
                evidence,
                expected_account_head_hash=None,
                expected_underlying_head_hash=None,
                recorded_at=evidence.recorded_at,
            )
            == evidence
        )
    with repository.atomic():
        assert (
            repository.append_root(
                evidence,
                expected_account_head_hash=None,
                expected_underlying_head_hash=None,
                recorded_at=evidence.recorded_at,
            )
            == evidence
        )
    assert AccountOwnerAssignmentSubjectV3Model.objects.count() == 1
    assert AccountOwnerAssignmentEvidenceV3Model.objects.count() == 1
    assert (
        repository.get_exact_by_hash(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            expected_content_hash=evidence.content_hash,
            as_of=evidence.valid_until,
        )
        == evidence
    )


@pytest.mark.django_db(transaction=True)
def test_failed_evidence_append_rolls_back_without_orphan_and_can_retry() -> None:
    """A caller-visible append failure must not consume the subject or root."""

    receipt_record = _record()
    repository = DjangoAccountOwnerAssignmentEvidenceV3Repository(clock=_Clock())
    with repository._receipts.atomic():
        repository._receipts.append(
            receipt_record,
            expected_predecessor_hash=None,
            recorded_at=receipt_record.receipt.recorded_at,
        )
    subject = _subject(receipt_record.receipt)
    evidence = _evidence(subject)
    with repository.atomic():
        repository.append_subject(subject, recorded_at=subject.requested_at)

    with pytest.raises(RuntimeError, match="caller rollback"):
        with repository.atomic():
            repository.append_root(
                evidence,
                expected_account_head_hash=None,
                expected_underlying_head_hash=None,
                recorded_at=evidence.recorded_at,
            )
            raise RuntimeError("caller rollback")

    assert AccountOwnerAssignmentEvidenceV3Model.objects.count() == 0
    assert (
        repository.get_winner(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            as_of=evidence.recorded_at,
        )
        is None
    )

    with repository.atomic():
        assert (
            repository.append_root(
                evidence,
                expected_account_head_hash=None,
                expected_underlying_head_hash=None,
                recorded_at=evidence.recorded_at,
            )
            == evidence
        )
    assert AccountOwnerAssignmentEvidenceV3Model.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_private_guards_future_cutoff_and_unrelated_tamper_fail_closed() -> None:
    receipt_record = _record()
    repository = DjangoAccountOwnerAssignmentEvidenceV3Repository(clock=_Clock())
    with repository._receipts.atomic():
        repository._receipts.append(
            receipt_record,
            expected_predecessor_hash=None,
            recorded_at=receipt_record.receipt.recorded_at,
        )
    subject = _subject(receipt_record.receipt)
    with repository.atomic():
        repository.append_subject(subject, recorded_at=subject.requested_at)
    with pytest.raises(ValidationError):
        AccountOwnerAssignmentSubjectV3Model().save()
    with pytest.raises(AccountOwnerAssignmentUnavailable):
        repository.get_subject_winner(
            subject_id=subject.subject_id,
            subject_version=subject.subject_version,
            as_of=_at(17),
        )
    table = connection.ops.quote_name(AccountOwnerAssignmentSubjectV3Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET header_seal = %s", ["0" * 64])  # noqa: S608
    with pytest.raises(AccountOwnerAssignmentCorruption):
        repository.get_subject_winner(subject_id="other", subject_version="v0", as_of=_at(16))


@pytest.mark.django_db(transaction=True)
def test_null_claim_knowledge_invalidates_all_subject_and_evidence_reads() -> None:
    receipt_record = _record()
    repository = DjangoAccountOwnerAssignmentEvidenceV3Repository(clock=_Clock())
    with repository._receipts.atomic():
        repository._receipts.append(
            receipt_record,
            expected_predecessor_hash=None,
            recorded_at=receipt_record.receipt.recorded_at,
        )
    subject = _subject(receipt_record.receipt)
    with repository.atomic():
        repository.append_subject(subject, recorded_at=subject.requested_at)
    table = connection.ops.quote_name(CanonicalAccountCreationConsumptionClaimModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET knowledge_at = NULL")  # noqa: S608
    with pytest.raises(AccountOwnerAssignmentCorruption):
        repository.get_subject_winner(
            subject_id=subject.subject_id,
            subject_version=subject.subject_version,
            as_of=_at(16),
        )


def test_0050_is_schema_only_zero_seed() -> None:
    migration = import_module(
        "apps.account.migrations.0050_account_owner_assignment_evidence_v3_ledgers"
    ).Migration
    assert migration.dependencies == [
        ("account", "0049_account_owner_assignment_provenance_receipt_v3_ledger")
    ]
    assert migration.operations
    assert all(
        type(operation).__name__ not in {"RunPython", "RunSQL"}
        for operation in migration.operations
    )
