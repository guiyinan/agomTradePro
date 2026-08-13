"""Component coverage for the closed Account owner-assignment v2 repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from django.db import connection

from apps.account.application.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2Conflict,
    AccountOwnerAssignmentEvidenceV2Corruption,
)
from apps.account.domain.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2,
    AccountOwnerAssignmentSubjectV2,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v2_models import (
    AccountOwnerAssignmentEvidenceV2Model,
    AccountOwnerAssignmentSubjectV2Model,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v2_repository import (
    DjangoAccountOwnerAssignmentEvidenceV2Repository,
)
from tests.unit.account.test_account_owner_assignment_evidence_v2 import _at, _evidence


class _Clock:
    def now(self) -> datetime:
        return _at(10)


def _successor(root: AccountOwnerAssignmentEvidenceV2) -> AccountOwnerAssignmentEvidenceV2:
    subject = replace(
        root.subject,
        subject_version="v2",
        identity_hash="",
        content_hash="",
    )
    return replace(
        root,
        evidence_version="v2",
        subject=subject,
        recorded_at=root.recorded_at + timedelta(minutes=1),
        supersedes_content_hash=root.content_hash,
        identity_hash="",
        content_hash="",
    )


def _append_subject(
    repository: DjangoAccountOwnerAssignmentEvidenceV2Repository,
    subject: AccountOwnerAssignmentSubjectV2,
) -> None:
    repository.append_subject(subject, recorded_at=subject.requested_at)


@pytest.mark.django_db(transaction=True)
def test_roundtrip_first_winner_dual_heads_and_exact_pit() -> None:
    repository = DjangoAccountOwnerAssignmentEvidenceV2Repository(clock=_Clock())
    root = _evidence()
    with repository.atomic():
        _append_subject(repository, root.subject)
        assert (
            repository.append(root, expected_predecessor_hash=None, recorded_at=root.recorded_at)
            == root
        )
        assert (
            repository.append(root, expected_predecessor_hash=None, recorded_at=root.recorded_at)
            == root
        )
    assert (
        repository.get_subject_winner(
            evidence_id=root.subject.subject_id,
            evidence_version=root.subject.subject_version,
            as_of=root.recorded_at,
        )
        == root.subject
    )
    assert (
        repository.get_account_head(
            account_namespace=root.subject.physical.account_namespace,
            account_id=root.subject.physical.account_id,
            as_of=root.recorded_at,
        )
        == root
    )
    assert (
        repository.get_underlying_head(
            underlying_unified_account_namespace=(
                root.subject.physical.underlying_unified_account_namespace
            ),
            underlying_unified_account_id=(root.subject.physical.underlying_unified_account_id),
            as_of=root.recorded_at,
        )
        == root
    )
    assert (
        repository.get_exact_by_hash(
            evidence_id=root.evidence_id,
            evidence_version=root.evidence_version,
            expected_content_hash=root.content_hash,
            as_of=root.recorded_at,
        )
        == root
    )
    row = AccountOwnerAssignmentEvidenceV2Model._base_manager.get()
    assert row.account_root_claim_hash == root.account_claim_hash
    assert row.underlying_root_claim_hash == root.underlying_claim_hash


@pytest.mark.django_db(transaction=True)
def test_successor_requires_both_heads_and_expired_head_never_falls_back() -> None:
    repository = DjangoAccountOwnerAssignmentEvidenceV2Repository(clock=_Clock())
    root = _evidence()
    successor = _successor(root)
    with repository.atomic():
        _append_subject(repository, root.subject)
        repository.append(root, expected_predecessor_hash=None, recorded_at=root.recorded_at)
        _append_subject(repository, successor.subject)
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )
    row = AccountOwnerAssignmentEvidenceV2Model._base_manager.get(
        content_hash=successor.content_hash
    )
    assert row.account_root_claim_hash is None and row.underlying_root_claim_hash is None
    assert (
        repository.get_account_head(
            account_namespace=root.subject.physical.account_namespace,
            account_id=root.subject.physical.account_id,
            as_of=_at(9),
        )
        == successor
    )
    assert (
        repository.get_exact_by_hash(
            evidence_id=root.evidence_id,
            evidence_version=root.evidence_version,
            expected_content_hash=root.content_hash,
            as_of=_at(9),
        )
        == root
    )


@pytest.mark.django_db(transaction=True)
def test_competing_root_and_wrong_predecessor_fail_closed() -> None:
    repository = DjangoAccountOwnerAssignmentEvidenceV2Repository(clock=_Clock())
    root = _evidence()
    with repository.atomic():
        _append_subject(repository, root.subject)
        repository.append(root, expected_predecessor_hash=None, recorded_at=root.recorded_at)
    competing = replace(
        root,
        evidence_id="competing",
        evidence_version="v9",
        subject=replace(
            root.subject,
            subject_id="competing",
            subject_version="v9",
            identity_hash="",
            content_hash="",
        ),
        identity_hash="",
        content_hash="",
    )
    with pytest.raises(AccountOwnerAssignmentEvidenceV2Conflict):
        with repository.atomic():
            _append_subject(repository, competing.subject)
            repository.append(
                competing, expected_predecessor_hash=None, recorded_at=competing.recorded_at
            )
    successor = _successor(root)
    with pytest.raises(AccountOwnerAssignmentEvidenceV2Conflict):
        with repository.atomic():
            _append_subject(repository, successor.subject)
            repository.append(
                successor,
                expected_predecessor_hash="0" * 64,
                recorded_at=successor.recorded_at,
            )


@pytest.mark.django_db(transaction=True)
def test_full_table_restore_detects_subject_and_evidence_header_tamper() -> None:
    repository = DjangoAccountOwnerAssignmentEvidenceV2Repository(clock=_Clock())
    root = _evidence()
    with repository.atomic():
        _append_subject(repository, root.subject)
        repository.append(root, expected_predecessor_hash=None, recorded_at=root.recorded_at)
    subject_table = connection.ops.quote_name(AccountOwnerAssignmentSubjectV2Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {subject_table} SET subject_id = %s", ["hidden"])
    with pytest.raises(AccountOwnerAssignmentEvidenceV2Corruption, match="subject"):
        repository.get_winner(
            evidence_id=root.evidence_id,
            evidence_version=root.evidence_version,
            as_of=root.recorded_at,
        )
