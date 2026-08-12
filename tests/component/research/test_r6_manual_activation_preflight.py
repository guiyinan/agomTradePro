"""Production composition contracts for the R6 manual-activation preflight."""

from __future__ import annotations

from dataclasses import fields
from inspect import signature

import pytest
from django.utils import timezone

from apps.research.application.r6_manual_activation_preflight import (
    EvaluateR6ManualActivationPreflightCommand,
    R6ManualActivationBlockerCode,
    R6ManualActivationPreflightStatus,
)
from apps.research.infrastructure.r6_scope_qualification_models import (
    R6ScopeQualificationRegistryModel,
)
from apps.research.infrastructure.state_model_activation_models import (
    R6ActivationAuditSnapshotModel,
    R6ActivationAuthorizationModel,
    R6ActivationEventModel,
    R6ActivationStreamCommitModel,
)
from apps.research.infrastructure.state_model_monitoring_models import (
    R6MonitoringAssessmentModel,
    R6MonitoringObservationModel,
)
from apps.research.infrastructure.state_model_qualification_models import (
    R6QualificationAssessmentModel,
    R6QualificationLifecycleAuthorizationModel,
    R6QualificationLifecycleEventModel,
)
from apps.research.r6_manual_activation_composition import (
    DjangoR6ManualActivationRuntime,
    build_django_r6_manual_activation_runtime,
)


def _ledger_counts() -> tuple[int, ...]:
    model_types = (
        R6QualificationAssessmentModel,
        R6QualificationLifecycleAuthorizationModel,
        R6QualificationLifecycleEventModel,
        R6MonitoringObservationModel,
        R6MonitoringAssessmentModel,
        R6ActivationAuthorizationModel,
        R6ActivationEventModel,
        R6ActivationStreamCommitModel,
        R6ActivationAuditSnapshotModel,
        R6ScopeQualificationRegistryModel,
    )
    return tuple(model._default_manager.count() for model in model_types)


@pytest.mark.django_db(transaction=True)
def test_public_using_only_runtime_is_empty_blocked_and_zero_write() -> None:
    """A missing scope owner cannot be replaced by fixtures or persisted snapshots."""

    assert tuple(signature(build_django_r6_manual_activation_runtime).parameters) == ("using",)
    runtime = build_django_r6_manual_activation_runtime()
    assert type(runtime) is DjangoR6ManualActivationRuntime
    assert tuple(item.name for item in fields(runtime)) == ("preflight",)
    assert not hasattr(runtime, "apply")
    assert not hasattr(runtime, "current")
    assert not hasattr(runtime, "consumer")
    before = _ledger_counts()

    result = runtime.preflight.execute(
        EvaluateR6ManualActivationPreflightCommand(
            scope_id="r6-state-model-advisory",
            as_of=timezone.now(),
        )
    )

    assert result.status is R6ManualActivationPreflightStatus.BLOCKED
    assert result.blocker_codes == (R6ManualActivationBlockerCode.SCOPE_OWNER_UNAVAILABLE,)
    assert result.must_not_publish_current is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_replace_regime is True
    assert result.must_not_execute is True
    assert _ledger_counts() == before
