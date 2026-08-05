"""Composition root for forecast-ledger commands."""

from apps.signal.application.forecast_use_cases import (
    FinalizeForecastOutcomeUseCase,
    ListScenarioForecastOutcomeEvidenceUseCase,
    RecordForecastEvaluationUseCase,
    RecordForecastLedgerEntryUseCase,
)
from apps.signal.infrastructure.forecast_repositories import ForecastEvaluationRepository
from core.integration.research_integrity_registry import (
    is_research_promotion_approved,
    is_scenario_forecast_reference_valid,
)


def make_record_forecast_entry() -> RecordForecastLedgerEntryUseCase:
    """Compose the canonical forecast publication writer."""

    return RecordForecastLedgerEntryUseCase(
        ForecastEvaluationRepository(),
        scenario_reference_checker=is_scenario_forecast_reference_valid,
        research_promotion_checker=is_research_promotion_approved,
    )


def make_record_forecast_evaluation() -> RecordForecastEvaluationUseCase:
    """Compose the append-only forecast check writer."""

    return RecordForecastEvaluationUseCase(ForecastEvaluationRepository())


def make_finalize_forecast_outcome() -> FinalizeForecastOutcomeUseCase:
    """Compose the immutable forecast outcome writer."""

    return FinalizeForecastOutcomeUseCase(ForecastEvaluationRepository())


def make_list_scenario_forecast_outcomes() -> ListScenarioForecastOutcomeEvidenceUseCase:
    """Compose the exact revision-bound scenario outcome query."""

    return ListScenarioForecastOutcomeEvidenceUseCase(ForecastEvaluationRepository())
