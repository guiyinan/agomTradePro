"""Composition root for forecast-ledger commands."""

from apps.signal.application.forecast_use_cases import (
    FinalizeForecastOutcomeUseCase,
    RecordForecastEvaluationUseCase,
    RecordForecastLedgerEntryUseCase,
)
from apps.signal.infrastructure.forecast_repositories import ForecastEvaluationRepository


def make_record_forecast_entry() -> RecordForecastLedgerEntryUseCase:
    """Compose the canonical forecast publication writer."""

    return RecordForecastLedgerEntryUseCase(ForecastEvaluationRepository())


def make_record_forecast_evaluation() -> RecordForecastEvaluationUseCase:
    """Compose the append-only forecast check writer."""

    return RecordForecastEvaluationUseCase(ForecastEvaluationRepository())


def make_finalize_forecast_outcome() -> FinalizeForecastOutcomeUseCase:
    """Compose the immutable forecast outcome writer."""

    return FinalizeForecastOutcomeUseCase(ForecastEvaluationRepository())
