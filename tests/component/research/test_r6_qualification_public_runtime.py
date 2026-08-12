"""Database proof that the public R6 qualification runtime is read-only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection

from apps.research.application.state_model_qualification_lifecycle import (
    ApplyR6QualificationLifecycle,
    ApplyR6QualificationLifecycleCommand,
    R6QualificationAuthorizationRef,
)
from apps.research.application.state_model_qualification_persistence import (
    GetExactR6QualificationAssessmentCommand,
    R6QualificationCorruption,
    R6QualificationUnavailable,
    RegisterR6QualificationAssessmentCommand,
    r6_qualification_assessment_id,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationLifecycleAction,
    R6QualificationRef,
)
from apps.research.infrastructure.state_model_qualification_models import (
    R6QualificationAssessmentModel,
    R6QualificationLifecycleAuthorizationModel,
    R6QualificationLifecycleEventModel,
)
from apps.research.infrastructure.state_model_qualification_repository import (
    DjangoR6QualificationReadRepository,
    _DjangoR6QualificationStore,
)
from apps.research.state_model_qualification_composition import (
    build_django_r6_qualification_runtime,
)
from tests.unit.research.advanced_state_model_factories import NOW as QUALIFICATION_NOW
from tests.unit.research.test_state_model_qualification_persistence import _assessment
from tests.unit.research.test_state_model_qualification_repository import (
    MutableClock,
    StaticAuthorizationProvider,
    _authorization,
)

NOW = datetime(2026, 8, 12, tzinfo=UTC)


@pytest.mark.django_db(transaction=True)
def test_public_runtime_is_empty_exact_and_all_mutations_are_zero_write() -> None:
    runtime = build_django_r6_qualification_runtime()
    ref = R6QualificationRef("qualification:r6:missing", "a" * 64)

    assert (
        runtime.get_exact.execute(
            GetExactR6QualificationAssessmentCommand(assessment_ref=ref, as_of=NOW)
        )
        is None
    )
    assert runtime.get_active.get_active(qualification_ref=ref, as_of=NOW) is None

    registration = RegisterR6QualificationAssessmentCommand(
        study_id="study:r6",
        assessed_at=NOW,
    )
    with pytest.raises(R6QualificationUnavailable):
        runtime.register.execute(registration)
    object.__setattr__(registration, "study_id", "")
    with pytest.raises(R6QualificationUnavailable):
        runtime.register.execute(registration)

    lifecycle = ApplyR6QualificationLifecycleCommand(
        qualification_ref=ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        authorization_ref=R6QualificationAuthorizationRef("authorization:r6", "v1"),
    )
    with pytest.raises(R6QualificationUnavailable):
        runtime.apply_lifecycle.execute(lifecycle)
    object.__setattr__(lifecycle, "qualification_ref", object())
    with pytest.raises(R6QualificationUnavailable):
        runtime.apply_lifecycle.execute(lifecycle)

    with pytest.raises(R6QualificationUnavailable):
        runtime.monitor.execute(as_of=NOW, cursor=None, limit=1)
    assert R6QualificationAssessmentModel._default_manager.count() == 0
    assert R6QualificationLifecycleAuthorizationModel._default_manager.count() == 0
    assert R6QualificationLifecycleEventModel._default_manager.count() == 0


@pytest.mark.django_db(transaction=True)
def test_future_damaged_lifecycle_event_cannot_pollute_an_earlier_pit() -> None:
    clock = MutableClock(QUALIFICATION_NOW + timedelta(days=1))
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
    apply.execute(
        ApplyR6QualificationLifecycleCommand(
            qualification_ref=ref,
            action=promotion.action,
            authorization_ref=R6QualificationAuthorizationRef(
                promotion.authorization_id,
                promotion.authorization_version,
            ),
        )
    )
    earlier_cutoff = clock.now()

    clock.value += timedelta(minutes=1)
    retirement = _authorization(
        ref=ref,
        action=R6QualificationLifecycleAction.RETIRE,
        sequence=2,
        recorded_at=clock.now(),
    )
    source.authorization = retirement
    retirement_event = apply.execute(
        ApplyR6QualificationLifecycleCommand(
            qualification_ref=ref,
            action=retirement.action,
            authorization_ref=R6QualificationAuthorizationRef(
                retirement.authorization_id,
                retirement.authorization_version,
            ),
        )
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r6_qualification_lifecycle_event "
            "SET canonical_payload = %s WHERE content_hash = %s",
            ["{}", retirement_event.content_hash],
        )

    repository = DjangoR6QualificationReadRepository()
    assert repository.get_active(qualification_ref=ref, as_of=earlier_cutoff) == assessment
    with pytest.raises(R6QualificationCorruption):
        repository.get_active(qualification_ref=ref, as_of=clock.now())
