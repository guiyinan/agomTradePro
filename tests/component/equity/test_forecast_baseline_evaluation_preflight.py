"""SQLite component boundary for the production R1 evaluation preflight."""

from __future__ import annotations

from datetime import timedelta
from inspect import signature

import pytest
from django.utils import timezone

from apps.equity.application.forecast_baseline_evaluation import (
    EvaluateForecastBaselineTrialCommand,
)
from apps.equity.application.forecast_baseline_evaluation_preflight import (
    ForecastBaselinePreflightBlockerCode,
    ForecastBaselinePreflightStatus,
)
from apps.equity.application.forecast_baseline_materialize import VersionRef
from apps.equity.forecast_baseline_evaluation_preflight_composition import (
    build_django_forecast_baseline_evaluation_preflight_runtime,
)
from apps.equity.infrastructure.forecast_baseline_models import (
    ForecastBaselineTrialResultModel,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _command() -> EvaluateForecastBaselineTrialCommand:
    return EvaluateForecastBaselineTrialCommand(
        output_trial_ref=VersionRef("r1-production-preflight", "v1"),
        spec_ref=VersionRef("missing-r1-spec", "v1"),
        artifact_ref=VersionRef("missing-r1-artifact", "v1"),
        actual_manifest_ref=VersionRef("missing-r1-actual", "v1"),
        research_trial_ref=VersionRef("missing-r1-research-trial", "v1"),
        as_of=timezone.now() - timedelta(days=1),
    )


def test_public_runtime_is_read_only_and_empty_owner_ledgers_stay_blocked() -> None:
    assert tuple(
        signature(build_django_forecast_baseline_evaluation_preflight_runtime).parameters
    ) == ("using",)
    runtime = build_django_forecast_baseline_evaluation_preflight_runtime()

    result = runtime.preflight.execute(_command())

    assert result.status is ForecastBaselinePreflightStatus.BLOCKED
    assert result.blocker_codes == (
        ForecastBaselinePreflightBlockerCode.ACTUAL_MANIFEST_UNAVAILABLE,
        ForecastBaselinePreflightBlockerCode.BASELINE_ARTIFACT_UNAVAILABLE,
        ForecastBaselinePreflightBlockerCode.BASELINE_SPEC_UNAVAILABLE,
        ForecastBaselinePreflightBlockerCode.RESEARCH_TRIAL_UNAVAILABLE,
    )
    assert not hasattr(runtime, "register")
    assert not hasattr(runtime, "materialize")
    assert not hasattr(runtime.preflight._read_repository, "append_trial")
    assert not hasattr(runtime.preflight._actual_provider, "append")
    assert not hasattr(runtime.preflight._research_trial_provider, "append")
    assert ForecastBaselineTrialResultModel._default_manager.count() == 0
