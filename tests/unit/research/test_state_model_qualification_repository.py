"""Component contracts for the append-only R6 qualification repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.research.application.state_model_qualification_lifecycle import (
    ApplyR6QualificationLifecycle,
    ApplyR6QualificationLifecycleCommand,
    GetActiveR6Qualification,
    R6QualificationAuthorizationRef,
)
from apps.research.application.state_model_qualification_persistence import (
    MonitorR6Qualification,
    R6QualificationUnavailable,
    r6_qualification_assessment_id,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationLifecycleAction,
    R6QualificationPromotionAuthorization,
    R6QualificationRef,
)
from apps.research.infrastructure.state_model_qualification_models import (
    R6QualificationAssessmentModel,
)
from apps.research.infrastructure.state_model_qualification_repository import (
    DjangoR6QualificationReadRepository,
    _DjangoR6QualificationStore,
)
from tests.unit.research.advanced_state_model_factories import NOW
from tests.unit.research.test_state_model_qualification_persistence import _assessment


@dataclass
class MutableClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class StaticAuthorizationProvider:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.authorization: R6QualificationPromotionAuthorization | None = None

    @property
    def unit_of_work_key(self) -> str:
        return "django:default"

    def get_exact(self, *, authorization_ref, qualification_ref, action):
        authorization = self.authorization
        if authorization is None:
            return None
        if (
            authorization.authorization_id != authorization_ref.authorization_id
            or authorization.authorization_version != authorization_ref.authorization_version
            or authorization.qualification_ref != qualification_ref
            or authorization.action is not action
        ):
            return None
        return authorization


def _authorization(
    *,
    ref: R6QualificationRef,
    action: R6QualificationLifecycleAction,
    sequence: int,
    recorded_at: datetime,
) -> R6QualificationPromotionAuthorization:
    return R6QualificationPromotionAuthorization(
        authorization_id=f"component-auth-{sequence}",
        authorization_version="v1",
        qualification_ref=ref,
        event_id=f"component-event-{sequence}",
        event_version="v1",
        action=action,
        expected_sequence=sequence,
        owner="research",
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(days=1),
        reason_codes=("manual-review",),
        evidence_ref=f"research://r6/component/{sequence}",
    )


@pytest.mark.django_db(transaction=True)
def test_exact_pit_and_append_only_guards() -> None:
    clock = MutableClock(NOW + timedelta(days=1))
    store = _DjangoR6QualificationStore(clock=clock)
    assessment = _assessment()
    with store.atomic():
        persisted = store.append_assessment(assessment)
    ref = R6QualificationRef(
        r6_qualification_assessment_id(
            study_id=assessment.study_id,
            assessed_at=assessment.assessed_at,
            content_hash=assessment.content_hash,
        ),
        assessment.content_hash,
    )
    repository = DjangoR6QualificationReadRepository()
    assert repository.get_exact(assessment_ref=ref, as_of=clock.now()) == persisted
    assert (
        repository.get_exact(
            assessment_ref=ref,
            as_of=clock.now() - timedelta(seconds=1),
        )
        is None
    )
    with pytest.raises(R6QualificationUnavailable):
        repository.get_exact(
            assessment_ref=ref,
            as_of=timezone.now() + timedelta(days=1),
        )

    model = R6QualificationAssessmentModel._default_manager.get(assessment_id=ref.assessment_id)
    with pytest.raises(ValidationError):
        model.save()
    with pytest.raises(ValidationError):
        model.delete()
    with pytest.raises(ValidationError):
        R6QualificationAssessmentModel._default_manager.filter(pk=model.pk).update(status="blocked")


@pytest.mark.django_db(transaction=True)
def test_audit_cursor_is_stable_and_pit_bounded() -> None:
    clock = MutableClock(NOW + timedelta(days=1))
    store = _DjangoR6QualificationStore(clock=clock)
    first = _assessment()
    second = _assessment(NOW + timedelta(minutes=1))
    with store.atomic():
        store.append_assessment(first)
        store.append_assessment(second)
    monitor = MonitorR6Qualification(store)
    page = monitor.execute(as_of=clock.now(), limit=1)
    assert len(page.entries) == 1
    assert page.next_cursor is not None
    next_page = monitor.execute(as_of=clock.now(), cursor=page.next_cursor, limit=1)
    assert len(next_page.entries) == 1
    assert next_page.next_cursor is None
    assert page.entries[0].active is False
    assert next_page.entries[0].active is False

    with pytest.raises(ValueError):
        monitor.execute(as_of=clock.now(), cursor="not-a-cursor", limit=1)


@pytest.mark.django_db(transaction=True)
def test_owner_authorized_promotion_and_retirement_are_append_only() -> None:
    clock = MutableClock(NOW + timedelta(days=1))
    store = _DjangoR6QualificationStore(clock=clock)
    assessment = _assessment()
    with store.atomic():
        store.append_assessment(assessment)
    ref = R6QualificationRef(
        r6_qualification_assessment_id(
            study_id=assessment.study_id,
            assessed_at=assessment.assessed_at,
            content_hash=assessment.content_hash,
        ),
        assessment.content_hash,
    )
    source = StaticAuthorizationProvider(clock)
    apply = ApplyR6QualificationLifecycle(
        authorization_provider=source,
        repository=store,
    )
    clock.value += timedelta(minutes=1)
    promotion = _authorization(
        ref=ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=clock.now(),
    )
    source.authorization = promotion
    command = ApplyR6QualificationLifecycleCommand(
        qualification_ref=ref,
        action=promotion.action,
        authorization_ref=R6QualificationAuthorizationRef(
            promotion.authorization_id,
            promotion.authorization_version,
        ),
    )
    first_event = apply.execute(command)
    assert first_event.action is R6QualificationLifecycleAction.PROMOTE
    assert apply.execute(command) == first_event

    active_reader = GetActiveR6Qualification(repository=store, clock=clock)
    assert active_reader.get_active(qualification_ref=ref, as_of=clock.now()) == assessment

    clock.value += timedelta(minutes=1)
    retirement = _authorization(
        ref=ref,
        action=R6QualificationLifecycleAction.RETIRE,
        sequence=2,
        recorded_at=clock.now(),
    )
    source.authorization = retirement
    retirement_command = ApplyR6QualificationLifecycleCommand(
        qualification_ref=ref,
        action=retirement.action,
        authorization_ref=R6QualificationAuthorizationRef(
            retirement.authorization_id,
            retirement.authorization_version,
        ),
    )
    second_event = apply.execute(retirement_command)
    assert second_event.action is R6QualificationLifecycleAction.RETIRE
    assert active_reader.get_active(qualification_ref=ref, as_of=clock.now()) is None


def test_r6_migration_has_expected_dependency_and_no_data_backfill() -> None:
    migration = __import__(
        "apps.research.migrations.0008_r6_qualification_ledgers",
        fromlist=["Migration"],
    ).Migration
    assert migration.dependencies == [("research", "0007_r7_research_result_ledger")]
    assert not any(
        operation.__class__.__name__ in {"RunPython", "RunSQL"}
        for operation in migration.operations
    )
