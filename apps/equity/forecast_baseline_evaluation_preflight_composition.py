"""Production read-only composition for the R1 evaluation preflight."""

from __future__ import annotations

from dataclasses import dataclass

from apps.data_center.evaluation_actual_manifest_composition import (
    build_django_evaluation_actual_runtime,
)
from apps.research.r1_forecast_trial_evidence_composition import (
    build_r1_forecast_trial_evidence_runtime,
)

from .application.forecast_baseline_evaluation_preflight import (
    EvaluateForecastBaselineTrialPreflight,
)
from .application.forecast_baseline_materialize import ForecastBaselineEvidenceError
from .infrastructure.forecast_baseline_repository import (
    DjangoForecastBaselineEvaluationReadRepository,
)


@dataclass(frozen=True, slots=True)
class DjangoForecastBaselineEvaluationPreflightRuntime:
    """One read-only preflight with no mutation, current, decision, or execution port."""

    preflight: EvaluateForecastBaselineTrialPreflight


def build_django_forecast_baseline_evaluation_preflight_runtime(
    *,
    using: str = "default",
) -> DjangoForecastBaselineEvaluationPreflightRuntime:
    """Compose existing exact owner readers on one database alias."""

    if type(using) is not str or not using.strip() or len(using) > 192:
        raise ValueError("R1 evaluation preflight database alias is invalid")
    read_repository = DjangoForecastBaselineEvaluationReadRepository(using=using)
    actual_provider = build_django_evaluation_actual_runtime(using=using).actual_provider
    research_trial_provider = build_r1_forecast_trial_evidence_runtime(using=using).equity_provider
    keys = {
        read_repository.unit_of_work_key,
        actual_provider.unit_of_work_key,
        research_trial_provider.unit_of_work_key,
    }
    if keys != {f"django:{using}"}:
        raise ForecastBaselineEvidenceError(
            "R1 evaluation preflight owners require one shared database"
        )
    return DjangoForecastBaselineEvaluationPreflightRuntime(
        preflight=EvaluateForecastBaselineTrialPreflight(
            read_repository=read_repository,
            actual_provider=actual_provider,
            research_trial_provider=research_trial_provider,
        )
    )


__all__ = [
    "DjangoForecastBaselineEvaluationPreflightRuntime",
    "build_django_forecast_baseline_evaluation_preflight_runtime",
]
