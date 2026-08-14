"""Database flow for separately registered operator-spec approval subjects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection

from apps.risk_center.application.evidence_operator_spec_approval import (
    ApproveEvidenceOperatorSpec,
    ApproveEvidenceOperatorSpecCommand,
    EvidenceOperatorSpecApprovalCorruption,
    EvidenceOperatorSpecApprovalDefinition,
    RegisterEvidenceOperatorSpecApprovalSubject,
    RegisterEvidenceOperatorSpecApprovalSubjectCommand,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalActor,
    EvidenceOperatorSpecApprovalActorKind,
    EvidenceOperatorSpecApprovalSubject,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_models import (
    EvidenceOperatorSpecApprovalRecordModel,
    EvidenceOperatorSpecApprovalSubjectModel,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_repository import (
    DjangoEvidenceOperatorSpecApprovalRepository,
)

REGISTERED_AT = datetime(2026, 8, 13, 8, tzinfo=UTC)
APPROVED_AT = REGISTERED_AT + timedelta(minutes=5)
VALID_UNTIL = REGISTERED_AT + timedelta(days=30)
HASH_A = "a" * 64


@dataclass
class MutableClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class DefinitionProvider:
    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalDefinition | None:
        if operator_id != "sector-score" or operator_version != "1":
            return None
        return EvidenceOperatorSpecApprovalDefinition(
            operator_id=operator_id,
            operator_version=operator_version,
            definition_hash=HASH_A,
            supersedes_activation_hash=None,
            activated_at=REGISTERED_AT - timedelta(days=1),
            valid_until=VALID_UNTIL,
        )


class RegisteredSubjectProvider:
    def __init__(self, repository: DjangoEvidenceOperatorSpecApprovalRepository) -> None:
        self.repository = repository

    def get_exact(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject | None:
        return self.repository.get_subject_winner(
            subject_id=subject_id,
            subject_version=subject_version,
            as_of=as_of,
        )


def _actor(user_id: int) -> EvidenceOperatorSpecApprovalActor:
    return EvidenceOperatorSpecApprovalActor(
        actor_id=f"django-user:{user_id}",
        kind=EvidenceOperatorSpecApprovalActorKind.HUMAN,
        is_staff=True,
        user_id=user_id,
    )


def _register(
    repository: DjangoEvidenceOperatorSpecApprovalRepository,
) -> EvidenceOperatorSpecApprovalSubject:
    return RegisterEvidenceOperatorSpecApprovalSubject(
        definition_provider=DefinitionProvider(),
        repository=repository,
        actor=_actor(41),
    ).execute(
        RegisterEvidenceOperatorSpecApprovalSubjectCommand(
            subject_id="operator-subject:sector-score:v1",
            subject_version="1",
            operator_id="sector-score",
            operator_version="1",
            as_of=REGISTERED_AT,
        )
    )


@pytest.mark.django_db
def test_registered_subject_can_precede_approval_with_distinct_server_clocks() -> None:
    clock = MutableClock(REGISTERED_AT)
    repository = DjangoEvidenceOperatorSpecApprovalRepository(clock=clock)
    subject = _register(repository)

    assert EvidenceOperatorSpecApprovalSubjectModel._default_manager.count() == 1
    assert EvidenceOperatorSpecApprovalRecordModel._default_manager.count() == 0
    clock.value = APPROVED_AT
    approval = ApproveEvidenceOperatorSpec(
        subject_provider=RegisteredSubjectProvider(repository),
        repository=repository,
        actor=_actor(42),
    ).execute(
        ApproveEvidenceOperatorSpecCommand(
            subject_id=subject.subject_id,
            subject_version=subject.subject_version,
            approval_id="operator-approval:sector-score:v1",
            approval_version="1",
            as_of=APPROVED_AT,
        )
    )

    subject_row = EvidenceOperatorSpecApprovalSubjectModel._default_manager.get()
    approval_row = EvidenceOperatorSpecApprovalRecordModel._default_manager.get()
    assert subject_row.recorded_at == REGISTERED_AT
    assert approval_row.recorded_at == APPROVED_AT
    assert approval_row.subject_id == subject_row.pk
    assert approval.subject == subject
    assert approval.approved_by == _actor(42)


@pytest.mark.django_db
def test_registered_subject_replay_is_idempotent_but_self_approval_is_rejected() -> None:
    clock = MutableClock(REGISTERED_AT)
    repository = DjangoEvidenceOperatorSpecApprovalRepository(clock=clock)
    first = _register(repository)
    assert _register(repository) == first
    assert EvidenceOperatorSpecApprovalSubjectModel._default_manager.count() == 1

    clock.value = APPROVED_AT
    with pytest.raises(ValueError, match="self approval"):
        ApproveEvidenceOperatorSpec(
            subject_provider=RegisteredSubjectProvider(repository),
            repository=repository,
            actor=_actor(41),
        ).execute(
            ApproveEvidenceOperatorSpecCommand(
                subject_id=first.subject_id,
                subject_version=first.subject_version,
                approval_id="operator-approval:self",
                approval_version="1",
                as_of=APPROVED_AT,
            )
        )
    assert EvidenceOperatorSpecApprovalRecordModel._default_manager.count() == 0


@pytest.mark.django_db
def test_approval_restore_rejects_subject_knowledge_clock_after_approval() -> None:
    clock = MutableClock(REGISTERED_AT)
    repository = DjangoEvidenceOperatorSpecApprovalRepository(clock=clock)
    subject = _register(repository)
    clock.value = APPROVED_AT
    approval = ApproveEvidenceOperatorSpec(
        subject_provider=RegisteredSubjectProvider(repository),
        repository=repository,
        actor=_actor(42),
    ).execute(
        ApproveEvidenceOperatorSpecCommand(
            subject_id=subject.subject_id,
            subject_version=subject.subject_version,
            approval_id="operator-approval:sector-score:v1",
            approval_version="1",
            as_of=APPROVED_AT,
        )
    )
    subject_row = EvidenceOperatorSpecApprovalSubjectModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE risk_center_evidence_operator_spec_subject "
            "SET recorded_at = %s WHERE id = %s",
            [APPROVED_AT + timedelta(seconds=1), subject_row.pk],
        )
    clock.value = APPROVED_AT + timedelta(seconds=2)

    # The raw timestamp edit invalidates the subject ledger seal first.  A
    # tampered subject must never reach the later approval-ordering check.
    with pytest.raises(
        EvidenceOperatorSpecApprovalCorruption,
        match="approval subject ledger seal is invalid",
    ):
        repository.get_approval_winner(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
            as_of=clock.value,
        )
