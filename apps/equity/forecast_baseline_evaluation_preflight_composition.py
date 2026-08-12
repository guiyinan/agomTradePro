"""Production read-only composition for the R1 evaluation preflight."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from core.integration.r1_forecast_trial_evidence import (
    build_r1_forecast_trial_evidence_provider,
)

from .application.forecast_baseline_evaluation import ResearchTrialEvidenceProvider
from .application.forecast_baseline_evaluation_preflight import (
    EvaluateForecastBaselineTrialPreflight,
)
from .application.forecast_baseline_materialize import ForecastBaselineEvidenceError
from .infrastructure.evaluation_actual_evidence_provider import (
    DjangoEvaluationActualEvidenceProvider,
)
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
    actual_provider = DjangoEvaluationActualEvidenceProvider(using=using)
    research_trial_provider = cast(
        ResearchTrialEvidenceProvider,
        build_r1_forecast_trial_evidence_provider(using=using),
    )
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
