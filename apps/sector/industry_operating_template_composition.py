"""Composition root for Sector-owned industry operating-template research."""

from apps.sector.application.industry_operating_template import (
    IndustryTemplateGovernanceFacade,
    RunIndustryOperatingTemplate,
)
from apps.sector.infrastructure.industry_operating_template_repository import (
    DataCenterOperatingDriverFactProvider,
    DjangoIndustryTemplateRepository,
)


def make_industry_template_governance_facade() -> IndustryTemplateGovernanceFacade:
    """Build the append-only template governance facade."""

    return IndustryTemplateGovernanceFacade(DjangoIndustryTemplateRepository())


def make_industry_template_runner() -> RunIndustryOperatingTemplate:
    """Build the fail-closed template runner with Data Center PIT facts."""

    return RunIndustryOperatingTemplate(
        repository=DjangoIndustryTemplateRepository(),
        fact_provider=DataCenterOperatingDriverFactProvider(),
    )


__all__ = [
    "make_industry_template_governance_facade",
    "make_industry_template_runner",
]
