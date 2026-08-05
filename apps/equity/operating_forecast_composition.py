"""Composition root for internal R1 operating-forecast workflows."""

from apps.equity.application.industry_template_forecast_bridge import (
    CreateForecastFromIndustryTemplate,
)
from apps.equity.application.operating_forecast import (
    CreateOperatingForecastVersionUseCase,
    RecordQuarterlyOperatingActualUseCase,
)
from apps.equity.infrastructure.operating_forecast_repository import (
    DjangoOperatingFactEvidenceProvider,
    DjangoOperatingForecastRepository,
    RuntimeResearchPromotionDecisionChecker,
)
from apps.sector.infrastructure.industry_operating_template_repository import (
    DjangoIndustryTemplateRepository,
)


def build_create_operating_forecast_use_case() -> CreateOperatingForecastVersionUseCase:
    """Build the internal forecast writer with canonical evidence adapters."""

    return CreateOperatingForecastVersionUseCase(
        repository=DjangoOperatingForecastRepository(),
        fact_provider=DjangoOperatingFactEvidenceProvider(),
        promotion_checker=RuntimeResearchPromotionDecisionChecker(),
        template_run_evidence_provider=DjangoIndustryTemplateRepository(),
    )


def build_industry_template_forecast_bridge() -> CreateForecastFromIndustryTemplate:
    """Build the verified Sector-draft to Equity-ledger bridge."""

    fact_provider = DjangoOperatingFactEvidenceProvider()
    run_repository = DjangoIndustryTemplateRepository()
    writer = CreateOperatingForecastVersionUseCase(
        repository=DjangoOperatingForecastRepository(),
        fact_provider=fact_provider,
        promotion_checker=RuntimeResearchPromotionDecisionChecker(),
        template_run_evidence_provider=run_repository,
    )
    return CreateForecastFromIndustryTemplate(
        writer=writer,
        fact_provider=fact_provider,
        run_evidence_provider=run_repository,
    )


def build_record_quarterly_actual_use_case() -> RecordQuarterlyOperatingActualUseCase:
    """Build the internal quarterly reconciliation writer."""

    return RecordQuarterlyOperatingActualUseCase(
        repository=DjangoOperatingForecastRepository(),
        fact_provider=DjangoOperatingFactEvidenceProvider(),
    )


__all__ = [
    "build_create_operating_forecast_use_case",
    "build_industry_template_forecast_bridge",
    "build_record_quarterly_actual_use_case",
]
