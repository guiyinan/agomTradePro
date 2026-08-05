"""Composition root for internal R1 operating-forecast workflows."""

from apps.equity.application.operating_forecast import (
    CreateOperatingForecastVersionUseCase,
    RecordQuarterlyOperatingActualUseCase,
)
from apps.equity.infrastructure.operating_forecast_repository import (
    DjangoOperatingFactEvidenceProvider,
    DjangoOperatingForecastRepository,
    RuntimeResearchPromotionDecisionChecker,
)


def build_create_operating_forecast_use_case() -> CreateOperatingForecastVersionUseCase:
    """Build the internal forecast writer with canonical evidence adapters."""

    return CreateOperatingForecastVersionUseCase(
        repository=DjangoOperatingForecastRepository(),
        fact_provider=DjangoOperatingFactEvidenceProvider(),
        promotion_checker=RuntimeResearchPromotionDecisionChecker(),
    )


def build_record_quarterly_actual_use_case() -> RecordQuarterlyOperatingActualUseCase:
    """Build the internal quarterly reconciliation writer."""

    return RecordQuarterlyOperatingActualUseCase(
        repository=DjangoOperatingForecastRepository(),
        fact_provider=DjangoOperatingFactEvidenceProvider(),
    )


__all__ = [
    "build_create_operating_forecast_use_case",
    "build_record_quarterly_actual_use_case",
]
