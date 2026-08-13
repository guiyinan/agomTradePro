"""Component contract skeleton for Portfolio inactive approval persistence."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db.migrations import RunPython

from apps.portfolio.application.transition_plan_inactive_approval import (
    TransitionPlanInactiveApprovalConflict,
    TransitionPlanInactiveApprovalSubject,
)
from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalActor,
    TransitionPlanApprovalReceipt,
)
from apps.portfolio.infrastructure.transition_plan_inactive_approval_codec import (
    decode_transition_plan_inactive_approval_receipt,
    decode_transition_plan_inactive_approval_subject,
    encode_transition_plan_inactive_approval_receipt,
    encode_transition_plan_inactive_approval_subject,
)
from apps.portfolio.infrastructure.transition_plan_inactive_approval_models import (
    TransitionPlanInactiveApprovalReceiptModel,
    TransitionPlanInactiveApprovalSubjectModel,
)
from apps.portfolio.infrastructure.transition_plan_inactive_approval_repository import (
    DjangoTransitionPlanInactiveApprovalRepository,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)
VALID_UNTIL = NOW + timedelta(hours=1)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _actor(actor_id: str, user_id: int) -> TransitionPlanApprovalActor:
    return TransitionPlanApprovalActor(
        actor_id=actor_id,
        user_id=user_id,
        role="portfolio_owner",
    )


def _subject() -> TransitionPlanInactiveApprovalSubject:
    return TransitionPlanInactiveApprovalSubject(
        subject_id="plan-subject:plan-1:v1",
        subject_version="v1",
        plan_id="plan-1",
        plan_version=1,
        plan_content_hash="a" * 64,
        account_id="7",
        decision_snapshot_id="decision-1",
        requested_by=_actor("user:requester", 19),
        requested_at=NOW,
        valid_until=VALID_UNTIL,
    )


def _receipt(subject: TransitionPlanInactiveApprovalSubject) -> TransitionPlanApprovalReceipt:
    return TransitionPlanApprovalReceipt(
        receipt_id="plan-receipt:plan-1:v1",
        receipt_version="v1",
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        subject_content_hash=subject.content_hash,
        plan_id=subject.plan_id,
        plan_version=subject.plan_version,
        plan_content_hash=subject.plan_content_hash,
        account_id=subject.account_id,
        decision_snapshot_id=subject.decision_snapshot_id,
        requested_by=subject.requested_by,
        approved_by=_actor("user:approver", 20),
        issued_at=NOW,
        valid_until=VALID_UNTIL,
    )


@pytest.mark.django_db(transaction=True)
def test_append_codec_and_exact_pit_round_trip() -> None:
    repository = DjangoTransitionPlanInactiveApprovalRepository(clock=FixedClock(NOW))
    subject = _subject()
    receipt = _receipt(subject)
    with repository.atomic():
        assert repository.append_subject(subject, recorded_at=NOW) == subject
        assert repository.append_subject(subject, recorded_at=NOW) == subject
        assert repository.append(receipt, subject=subject, recorded_at=NOW) == receipt
        assert repository.append(receipt, subject=subject, recorded_at=NOW) == receipt

    assert TransitionPlanInactiveApprovalSubjectModel._default_manager.count() == 1
    assert TransitionPlanInactiveApprovalReceiptModel._default_manager.count() == 1
    assert (
        decode_transition_plan_inactive_approval_subject(
            encode_transition_plan_inactive_approval_subject(subject)
        )
        == subject
    )
    assert (
        decode_transition_plan_inactive_approval_receipt(
            encode_transition_plan_inactive_approval_receipt(receipt)
        )
        == receipt
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_content_hash=receipt.content_hash,
            as_of=NOW,
        )
        == receipt
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_content_hash=receipt.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_private_uow_append_only_and_subject_binding_fail_closed() -> None:
    repository = DjangoTransitionPlanInactiveApprovalRepository(clock=FixedClock(NOW))
    subject = _subject()
    receipt = _receipt(subject)
    with pytest.raises(TransitionPlanInactiveApprovalConflict, match="private unit"):
        repository.append_subject(subject, recorded_at=NOW)
    with pytest.raises(ValidationError, match="exact insert claim"):
        TransitionPlanInactiveApprovalSubjectModel._default_manager.create(
            subject_id=subject.subject_id
        )
    with repository.atomic():
        repository.append_subject(subject, recorded_at=NOW)
        with pytest.raises(TransitionPlanInactiveApprovalConflict, match="exact subject"):
            repository.append(
                _receipt(replace(subject, subject_id="plan-subject:other:v1", content_hash="")),
                subject=subject,
                recorded_at=NOW,
            )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "model_type",
    [TransitionPlanInactiveApprovalSubjectModel, TransitionPlanInactiveApprovalReceiptModel],
)
def test_all_orm_mutation_shortcuts_are_rejected(model_type: type) -> None:
    repository = DjangoTransitionPlanInactiveApprovalRepository(clock=FixedClock(NOW))
    subject = _subject()
    with repository.atomic():
        repository.append_subject(subject, recorded_at=NOW)
        repository.append(_receipt(subject), subject=subject, recorded_at=NOW)
    row = model_type._default_manager.get()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base(raw=True)
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        model_type._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError):
        model_type._default_manager.bulk_create([row])


def test_inactive_approval_migration_is_schema_only_zero_seed() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0017_transition_plan_inactive_approvals"
    ).Migration
    assert migration.operations
    assert not any(isinstance(operation, RunPython) for operation in migration.operations)
