"""Pure Application tests for inactive transition-plan approval workflow."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.application.transition_plan_inactive_approval import (
    ApproveTransitionPlanInactive,
    ApproveTransitionPlanInactiveCommand,
    GetExactTransitionPlanInactiveApproval,
    GetExactTransitionPlanInactiveApprovalCommand,
    RegisterTransitionPlanInactiveApprovalSubject,
    RegisterTransitionPlanInactiveApprovalSubjectCommand,
    TransitionPlanDefinition,
    TransitionPlanInactiveApprovalConflict,
    TransitionPlanInactiveApprovalCorruption,
    TransitionPlanInactiveApprovalSubject,
    TransitionPlanInactiveApprovalUnavailable,
)
from apps.portfolio.domain.entities import ConstraintDecision, OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalActor,
    TransitionPlanApprovalReceipt,
    transition_plan_content_hash_v1,
)

PLAN_AT = datetime(2026, 8, 13, 8, tzinfo=UTC)
FIRST_CLOCK = PLAN_AT + timedelta(minutes=1)
SECOND_CLOCK = PLAN_AT + timedelta(minutes=2)
EXPIRES_AT = PLAN_AT + timedelta(hours=1)


def _plan(*, plan_id: str = "plan-1", version: int = 1) -> TransitionPlan:
    constraint = ConstraintDecision("cash", "600000.SH", True, 100, 80, "cash cap")
    return TransitionPlan(
        plan_id=plan_id,
        idempotency_key="idem-1",
        account_id="7",
        decision_snapshot_id="decision-1",
        portfolio_snapshot_id="portfolio-1",
        target_portfolio_id="target-1",
        as_of_time=PLAN_AT,
        expires_at=EXPIRES_AT,
        orders=(
            OrderDraft(
                asset_code="600000.SH",
                side="buy",
                quantity=80,
                reference_price=Decimal("10.00"),
                estimated_fee=Decimal("2.00"),
                status="partial",
                remaining_quantity=20,
                constraints=(constraint,),
            ),
        ),
        constraints=(constraint,),
        cash_before=Decimal("1000.00"),
        cash_after=Decimal("198.00"),
        status="APPROVED",
        version=version,
        metadata={"planning_policy_version": "policy-v1"},
    )


def _definition(plan: TransitionPlan | None = None) -> TransitionPlanDefinition:
    value = plan or _plan()
    return TransitionPlanDefinition(
        plan=value,
        content_hash=transition_plan_content_hash_v1(value),
        recorded_at=PLAN_AT,
    )


def _actor(user_id: int) -> TransitionPlanApprovalActor:
    return TransitionPlanApprovalActor(
        actor_id=f"user:{user_id}", user_id=user_id, role="portfolio_owner"
    )


class PlanProvider:
    def __init__(self, values: list[TransitionPlanDefinition | None]) -> None:
        self.values = values
        self.calls: list[tuple[str, int, datetime]] = []

    def get_exact(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> TransitionPlanDefinition | None:
        self.calls.append((plan_id, plan_version, as_of))
        index = min(len(self.calls) - 1, len(self.values) - 1)
        return self.values[index]


@dataclass
class MemoryRepository:
    clock: datetime

    def __post_init__(self) -> None:
        self.subjects: dict[
            tuple[str, str], tuple[TransitionPlanInactiveApprovalSubject, datetime]
        ] = {}
        self.receipts: dict[tuple[str, str], tuple[TransitionPlanApprovalReceipt, datetime]] = {}
        self.atomic_depth = 0
        self.subject_appends = 0
        self.receipt_appends = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_depth += 1
        try:
            yield
        finally:
            self.atomic_depth -= 1

    def now(self) -> datetime:
        return self.clock

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> TransitionPlanInactiveApprovalSubject | None:
        stored = self.subjects.get((subject_id, subject_version))
        return stored[0] if stored is not None and stored[1] <= as_of else None

    def get_receipt_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> TransitionPlanApprovalReceipt | None:
        stored = self.receipts.get((receipt_id, receipt_version))
        return stored[0] if stored is not None and stored[1] <= as_of else None

    def append_subject(
        self, subject: TransitionPlanInactiveApprovalSubject, *, recorded_at: datetime
    ) -> TransitionPlanInactiveApprovalSubject:
        assert self.atomic_depth == 1
        self.subject_appends += 1
        key = (subject.subject_id, subject.subject_version)
        winner = self.subjects.setdefault(key, (subject, recorded_at))[0]
        return winner

    def append(
        self,
        receipt: TransitionPlanApprovalReceipt,
        *,
        subject: TransitionPlanInactiveApprovalSubject,
        recorded_at: datetime,
    ) -> TransitionPlanApprovalReceipt:
        assert self.atomic_depth == 1
        assert self.subjects[(subject.subject_id, subject.subject_version)][0] == subject
        self.receipt_appends += 1
        key = (receipt.receipt_id, receipt.receipt_version)
        winner = self.receipts.setdefault(key, (receipt, recorded_at))[0]
        return winner

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> TransitionPlanApprovalReceipt | None:
        winner = self.get_receipt_winner(
            receipt_id=receipt_id, receipt_version=receipt_version, as_of=as_of
        )
        if winner is None or winner.content_hash != expected_content_hash:
            return None
        return winner


def _register_command() -> RegisterTransitionPlanInactiveApprovalSubjectCommand:
    return RegisterTransitionPlanInactiveApprovalSubjectCommand(
        subject_id="plan-approval-subject:plan-1:v1",
        subject_version="v1",
        plan_id="plan-1",
        plan_version=1,
    )


def _approve_command() -> ApproveTransitionPlanInactiveCommand:
    return ApproveTransitionPlanInactiveCommand(
        subject_id="plan-approval-subject:plan-1:v1",
        subject_version="v1",
        receipt_id="plan-approval:plan-1:v1",
        receipt_version="v1",
    )


def _exact_command(
    receipt: TransitionPlanApprovalReceipt,
    subject: TransitionPlanInactiveApprovalSubject,
    *,
    as_of: datetime,
) -> GetExactTransitionPlanInactiveApprovalCommand:
    return GetExactTransitionPlanInactiveApprovalCommand(
        receipt_id=receipt.receipt_id,
        receipt_version=receipt.receipt_version,
        expected_content_hash=receipt.content_hash,
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        subject_content_hash=subject.content_hash,
        plan_id=subject.plan_id,
        plan_version=subject.plan_version,
        plan_content_hash=subject.plan_content_hash,
        as_of=as_of,
    )


def _register(
    repository: MemoryRepository, provider: PlanProvider
) -> TransitionPlanInactiveApprovalSubject:
    return RegisterTransitionPlanInactiveApprovalSubject(
        plan_provider=provider, repository=repository, actor=_actor(19)
    ).execute(_register_command())


def test_id_only_register_and_approve_use_persisted_subject_and_double_reads() -> None:
    repository = MemoryRepository(FIRST_CLOCK)
    provider = PlanProvider([_definition()])

    subject = _register(repository, provider)
    receipt = ApproveTransitionPlanInactive(
        plan_provider=provider, repository=repository, actor=_actor(20)
    ).execute(_approve_command())

    assert len(provider.calls) == 4
    assert repository.subjects[(subject.subject_id, subject.subject_version)][0] == subject
    assert receipt.plan_content_hash == subject.plan_content_hash
    assert receipt.subject_content_hash == subject.content_hash
    assert receipt.requested_by == subject.requested_by
    assert receipt.plan_status_at_issue == "APPROVED"
    assert receipt.issued_at == FIRST_CLOCK
    assert receipt.execution_permission == "inactive"
    assert receipt.must_not_execute is True
    assert repository.subject_appends == 1
    assert repository.receipt_appends == 1


def test_retries_across_server_clocks_return_persisted_first_winners() -> None:
    repository = MemoryRepository(FIRST_CLOCK)
    provider = PlanProvider([_definition()])
    first_subject = _register(repository, provider)
    first_receipt = ApproveTransitionPlanInactive(
        plan_provider=provider, repository=repository, actor=_actor(20)
    ).execute(_approve_command())

    repository.clock = SECOND_CLOCK
    retried_subject = RegisterTransitionPlanInactiveApprovalSubject(
        plan_provider=provider, repository=repository, actor=_actor(19)
    ).execute(_register_command())
    retried_receipt = ApproveTransitionPlanInactive(
        plan_provider=provider, repository=repository, actor=_actor(20)
    ).execute(_approve_command())

    assert retried_subject == first_subject
    assert retried_receipt == first_receipt
    assert retried_subject.requested_at == FIRST_CLOCK
    assert retried_receipt.issued_at == FIRST_CLOCK
    assert retried_receipt.approved_by == _actor(20)
    assert repository.subject_appends == 1
    assert repository.receipt_appends == 1

    with pytest.raises(TransitionPlanInactiveApprovalConflict, match="requester"):
        RegisterTransitionPlanInactiveApprovalSubject(
            plan_provider=provider, repository=repository, actor=_actor(29)
        ).execute(_register_command())
    with pytest.raises(TransitionPlanInactiveApprovalConflict, match="approver"):
        ApproveTransitionPlanInactive(
            plan_provider=provider, repository=repository, actor=_actor(30)
        ).execute(_approve_command())


def test_register_fails_closed_when_trusted_plan_changes_during_double_read() -> None:
    original = _definition()
    changed_plan = replace(_plan(), cash_after=Decimal("197.00"))
    provider = PlanProvider([original, _definition(changed_plan)])
    repository = MemoryRepository(FIRST_CLOCK)

    with pytest.raises(TransitionPlanInactiveApprovalCorruption, match="changed"):
        _register(repository, provider)

    assert repository.subject_appends == 0


def test_approve_requires_persisted_subject_and_distinct_server_actor() -> None:
    repository = MemoryRepository(FIRST_CLOCK)
    provider = PlanProvider([_definition()])
    use_case = ApproveTransitionPlanInactive(
        plan_provider=provider, repository=repository, actor=_actor(20)
    )
    with pytest.raises(TransitionPlanInactiveApprovalUnavailable, match="subject"):
        use_case.execute(_approve_command())

    _register(repository, provider)
    with pytest.raises(TransitionPlanInactiveApprovalUnavailable, match="self approval"):
        ApproveTransitionPlanInactive(
            plan_provider=provider, repository=repository, actor=_actor(19)
        ).execute(_approve_command())
    same_actor_id = TransitionPlanApprovalActor(
        actor_id=_actor(19).actor_id,
        user_id=29,
        role="portfolio_owner",
    )
    with pytest.raises(TransitionPlanInactiveApprovalUnavailable, match="self approval"):
        ApproveTransitionPlanInactive(
            plan_provider=provider,
            repository=repository,
            actor=same_actor_id,
        ).execute(_approve_command())
    assert repository.receipt_appends == 0


def test_conflicting_persisted_subject_winner_is_not_rebuilt_at_retry_clock() -> None:
    repository = MemoryRepository(FIRST_CLOCK)
    provider = PlanProvider([_definition()])
    winner = TransitionPlanInactiveApprovalSubject.create(
        subject_id=_register_command().subject_id,
        subject_version=_register_command().subject_version,
        definition=_definition(_plan(plan_id="plan-other")),
        requested_by=_actor(19),
        requested_at=FIRST_CLOCK,
    )
    repository.subjects[(winner.subject_id, winner.subject_version)] = (winner, FIRST_CLOCK)
    repository.clock = SECOND_CLOCK

    with pytest.raises(TransitionPlanInactiveApprovalConflict, match="another first winner"):
        _register(repository, provider)


def test_exact_read_enforces_identity_hash_pit_and_inactive_state() -> None:
    repository = MemoryRepository(FIRST_CLOCK)
    provider = PlanProvider([_definition()])
    subject = _register(repository, provider)
    receipt = ApproveTransitionPlanInactive(
        plan_provider=provider, repository=repository, actor=_actor(20)
    ).execute(_approve_command())
    query = GetExactTransitionPlanInactiveApproval(repository)

    assert query.execute(_exact_command(receipt, subject, as_of=FIRST_CLOCK)) == receipt
    assert (
        query.execute(
            _exact_command(
                receipt,
                subject,
                as_of=FIRST_CLOCK - timedelta(microseconds=1),
            )
        )
        is None
    )


def test_commands_reject_caller_controlled_payload_shapes() -> None:
    with pytest.raises(ValueError):
        RegisterTransitionPlanInactiveApprovalSubjectCommand(
            subject_id="bad subject",
            subject_version="v1",
            plan_id="plan-1",
            plan_version=1,
        )
    with pytest.raises(ValueError):
        GetExactTransitionPlanInactiveApprovalCommand(
            receipt_id="receipt-1",
            receipt_version="v1",
            expected_content_hash="not-a-hash",
            subject_id="subject-1",
            subject_version="v1",
            subject_content_hash="a" * 64,
            plan_id="plan-1",
            plan_version=1,
            plan_content_hash="b" * 64,
            as_of=FIRST_CLOCK,
        )
