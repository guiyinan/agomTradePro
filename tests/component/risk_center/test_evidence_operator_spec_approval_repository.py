"""Component coverage for the Risk Center operator spec approval provider."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.risk_center.application.evidence_operator_spec_approval import (
    ApproveEvidenceOperatorSpec,
    ApproveEvidenceOperatorSpecCommand,
    EvidenceOperatorSpecApprovalConflict,
    EvidenceOperatorSpecApprovalCorruption,
    EvidenceOperatorSpecApprovalUnavailable,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalActor,
    EvidenceOperatorSpecApprovalActorKind,
    EvidenceOperatorSpecApprovalRecord,
    EvidenceOperatorSpecApprovalSubject,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_models import (
    EvidenceOperatorSpecApprovalRecordModel,
    EvidenceOperatorSpecApprovalSubjectModel,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_repository import (
    DjangoEvidenceOperatorSpecApprovalRepository,
    _approval_values,
)

REQUESTED_AT = datetime(2026, 8, 12, 8, tzinfo=UTC)
AS_OF = datetime(2026, 8, 12, 9, tzinfo=UTC)
RECORDED_AT = datetime(2026, 8, 12, 10, tzinfo=UTC)
VALID_UNTIL = datetime(2026, 9, 12, 8, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class SubjectProvider:
    def __init__(self, subject: EvidenceOperatorSpecApprovalSubject) -> None:
        self.subject = subject

    def get_exact(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject | None:
        if (
            self.subject.subject_id != subject_id
            or self.subject.subject_version != subject_version
            or not self.subject.is_valid_at(as_of)
        ):
            return None
        return self.subject


def _actor(
    *,
    actor_id: str = "user:risk-owner",
    user_id: int = 41,
) -> EvidenceOperatorSpecApprovalActor:
    return EvidenceOperatorSpecApprovalActor(
        actor_id=actor_id,
        kind=EvidenceOperatorSpecApprovalActorKind.HUMAN,
        is_staff=True,
        user_id=user_id,
    )


def _subject(
    *,
    subject_id: str = "operator-subject:sector-score:v1",
    subject_version: str = "1",
    definition_hash: str = HASH_A,
) -> EvidenceOperatorSpecApprovalSubject:
    return EvidenceOperatorSpecApprovalSubject.create(
        subject_id=subject_id,
        subject_version=subject_version,
        operator_id="sector-score",
        operator_version="1",
        definition_hash=definition_hash,
        supersedes_activation_hash=None,
        requested_by=EvidenceOperatorSpecApprovalActor(
            actor_id="research.operator-registry",
            kind=EvidenceOperatorSpecApprovalActorKind.SERVICE,
            is_staff=False,
        ),
        requested_at=REQUESTED_AT,
        valid_until=VALID_UNTIL,
    )


def _command(
    *,
    approval_id: str = "operator-approval:sector-score:v1",
) -> ApproveEvidenceOperatorSpecCommand:
    return ApproveEvidenceOperatorSpecCommand(
        subject_id="operator-subject:sector-score:v1",
        subject_version="1",
        approval_id=approval_id,
        approval_version="1",
        as_of=AS_OF,
    )


def _runtime(
    *,
    subject: EvidenceOperatorSpecApprovalSubject | None = None,
) -> tuple[
    ApproveEvidenceOperatorSpec,
    DjangoEvidenceOperatorSpecApprovalRepository,
    FixedClock,
]:
    value = subject or _subject()
    clock = FixedClock(RECORDED_AT)
    repository = DjangoEvidenceOperatorSpecApprovalRepository(clock=clock)
    use_case = ApproveEvidenceOperatorSpec(
        subject_provider=SubjectProvider(value),
        repository=repository,
        actor=_actor(),
    )
    return use_case, repository, clock


@pytest.mark.django_db
def test_id_only_approval_exact_pit_and_definition_reads_are_strict() -> None:
    use_case, repository, clock = _runtime()
    approval = use_case.execute(_command())

    assert EvidenceOperatorSpecApprovalSubjectModel._default_manager.count() == 1
    assert EvidenceOperatorSpecApprovalRecordModel._default_manager.count() == 1
    assert approval.issued_at == RECORDED_AT
    assert approval.approved_by == _actor()
    assert use_case.execute(_command()) == approval
    assert EvidenceOperatorSpecApprovalSubjectModel._default_manager.count() == 1
    assert EvidenceOperatorSpecApprovalRecordModel._default_manager.count() == 1

    clock.value = RECORDED_AT + timedelta(hours=1)
    assert (
        repository.get_exact_by_hash(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
            expected_content_hash=approval.content_hash,
            as_of=RECORDED_AT,
        )
        == approval
    )
    assert (
        repository.get_for_definition(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
            operator_id=approval.subject.operator_id,
            operator_version=approval.subject.operator_version,
            definition_hash=approval.subject.definition_hash,
            supersedes_activation_hash=approval.subject.supersedes_activation_hash,
            as_of=RECORDED_AT,
        )
        == approval
    )
    assert (
        repository.get_for_definition(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
            operator_id=approval.subject.operator_id,
            operator_version=approval.subject.operator_version,
            definition_hash=HASH_B,
            supersedes_activation_hash=None,
            as_of=RECORDED_AT,
        )
        is None
    )


@pytest.mark.django_db
def test_future_and_preknowledge_pit_reads_fail_closed() -> None:
    use_case, repository, clock = _runtime()
    approval = use_case.execute(_command())
    clock.value = RECORDED_AT

    assert (
        repository.get_exact_by_hash(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
            expected_content_hash=approval.content_hash,
            as_of=RECORDED_AT - timedelta(microseconds=1),
        )
        is None
    )
    with pytest.raises(EvidenceOperatorSpecApprovalUnavailable, match="future"):
        repository.get_exact_by_hash(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
            expected_content_hash=approval.content_hash,
            as_of=RECORDED_AT + timedelta(microseconds=1),
        )


@pytest.mark.django_db
def test_direct_bulk_base_update_and_delete_shortcuts_are_rejected() -> None:
    use_case, _, _ = _runtime()
    approval = use_case.execute(_command())
    row = EvidenceOperatorSpecApprovalRecordModel._default_manager.get()

    row.approved_actor_id = "tampered"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(force_update=True)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        EvidenceOperatorSpecApprovalRecordModel._default_manager.update(
            approved_actor_id="tampered"
        )
    values = _approval_values(approval, recorded_at=approval.issued_at)
    with pytest.raises(ValidationError, match="exact insert claim"):
        EvidenceOperatorSpecApprovalRecordModel._default_manager.create(
            subject=row.subject,
            **values,
        )
    with pytest.raises(ValidationError, match="exact repository appends"):
        EvidenceOperatorSpecApprovalRecordModel._default_manager.bulk_create(
            [EvidenceOperatorSpecApprovalRecordModel(subject=row.subject, **values)]
        )


@pytest.mark.django_db
def test_identity_header_and_payload_tamper_are_detected() -> None:
    use_case, repository, clock = _runtime()
    approval = use_case.execute(_command())
    row = EvidenceOperatorSpecApprovalRecordModel._default_manager.get()
    clock.value = RECORDED_AT + timedelta(hours=1)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE risk_center_evidence_operator_spec_approval "
            "SET approval_id = %s WHERE id = %s",
            ["operator-approval:tampered", row.pk],
        )
    with pytest.raises(EvidenceOperatorSpecApprovalCorruption, match="headers"):
        repository.get_exact_by_hash(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
            expected_content_hash=approval.content_hash,
            as_of=RECORDED_AT,
        )


@pytest.mark.django_db
def test_canonical_payload_tamper_is_detected() -> None:
    use_case, repository, clock = _runtime()
    approval = use_case.execute(_command())
    row = EvidenceOperatorSpecApprovalRecordModel._default_manager.get()
    clock.value = RECORDED_AT + timedelta(hours=1)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE risk_center_evidence_operator_spec_approval "
            "SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(EvidenceOperatorSpecApprovalCorruption, match="payload"):
        repository.get_exact_by_hash(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
            expected_content_hash=approval.content_hash,
            as_of=RECORDED_AT,
        )


@pytest.mark.django_db(transaction=True)
def test_database_identity_first_winner_rejects_conflicting_subject() -> None:
    use_case, repository, _ = _runtime()
    use_case.execute(_command())
    conflicting_subject = _subject(definition_hash=HASH_B)
    conflicting = EvidenceOperatorSpecApprovalRecord.create(
        approval_id="operator-approval:conflict",
        approval_version="1",
        subject=conflicting_subject,
        approved_by=_actor(),
        issued_at=RECORDED_AT,
    )

    with (
        repository.atomic(),
        pytest.raises(
            EvidenceOperatorSpecApprovalConflict,
            match="without a visible first winner",
        ),
    ):
        repository.append(conflicting, recorded_at=RECORDED_AT)

    assert EvidenceOperatorSpecApprovalSubjectModel._default_manager.count() == 1
    assert EvidenceOperatorSpecApprovalRecordModel._default_manager.count() == 1
