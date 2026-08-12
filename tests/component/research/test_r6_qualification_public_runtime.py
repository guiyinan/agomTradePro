"""Database proof that the public R6 qualification runtime is read-only."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.research.application.state_model_qualification_lifecycle import (
    ApplyR6QualificationLifecycleCommand,
    R6QualificationAuthorizationRef,
)
from apps.research.application.state_model_qualification_persistence import (
    GetExactR6QualificationAssessmentCommand,
    R6QualificationUnavailable,
    RegisterR6QualificationAssessmentCommand,
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
from apps.research.state_model_qualification_composition import (
    build_django_r6_qualification_runtime,
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
