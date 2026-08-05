"""Component coverage for append-only Sector industry-template persistence."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.sector.application.industry_operating_template import (
    IndustryTemplateGovernanceFacade,
    RunIndustryOperatingTemplate,
)
from apps.sector.domain.industry_operating_template import (
    DriverDefinition,
    PITDriverFact,
    TemplateLifecycle,
    TemplateRunStatus,
)
from apps.sector.infrastructure.industry_operating_template_models import (
    IndustryOperatingTemplateVersionModel,
    IndustryTemplateRunEvidenceModel,
)
from apps.sector.infrastructure.industry_operating_template_repository import (
    DjangoIndustryTemplateRepository,
)
from tests.unit.sector.test_industry_operating_template import (
    _FactProvider,
    _request,
    _template,
)


class _MissingFactProvider:
    def get_fact(
        self,
        driver: DriverDefinition,
        *,
        subject_code: str,
        as_of_time: datetime,
    ) -> PITDriverFact | None:
        return None


@pytest.mark.django_db
def test_repository_round_trip_and_run_evidence_are_hash_verified_and_immutable() -> None:
    repository = DjangoIndustryTemplateRepository()
    template = _template()
    saved = IndustryTemplateGovernanceFacade(repository).register_template(template)

    restored = repository.get_template(
        template_code=template.template_code,
        template_version=template.template_version,
    )
    result = RunIndustryOperatingTemplate(
        repository=repository,
        fact_provider=_FactProvider(template),
    ).execute(_request())

    assert saved == template
    assert restored == template
    assert result.status is TemplateRunStatus.AVAILABLE
    assert IndustryOperatingTemplateVersionModel._default_manager.count() == 1
    assert IndustryTemplateRunEvidenceModel._default_manager.count() == 1
    evidence = repository.get_run_evidence(run_key="TEST_RUN", run_version=1)
    assert evidence is not None
    assert evidence.content_hash == result.content_hash

    model = IndustryTemplateRunEvidenceModel._default_manager.get()
    model.status = TemplateRunStatus.BLOCKED.value
    with pytest.raises(ValidationError, match="immutable"):
        model.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        model.delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        IndustryTemplateRunEvidenceModel.objects.filter(pk=model.pk).update(
            status=TemplateRunStatus.BLOCKED.value
        )
    with pytest.raises(ValidationError, match="bulk updated"):
        IndustryTemplateRunEvidenceModel.objects.filter(pk=model.pk).bulk_update(
            [model], ["status"]
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        IndustryTemplateRunEvidenceModel.objects.filter(pk=model.pk).delete()


@pytest.mark.django_db
def test_repository_rejects_conflict_and_preserves_lifecycle_versions() -> None:
    repository = DjangoIndustryTemplateRepository()
    template = repository.append_template(_template())

    with pytest.raises(ValueError, match="conflicting content"):
        repository.append_template(replace(template, name="Conflicting name"))
    retired = replace(
        template,
        template_version=2,
        supersedes_version=1,
        lifecycle=TemplateLifecycle.RETIRED,
        lifecycle_reason="owner retired methodology",
    )
    repository.append_template(retired)

    assert IndustryOperatingTemplateVersionModel._default_manager.count() == 2
    assert repository.get_template(template_code="TEST_TEMPLATE", template_version=2) == retired


@pytest.mark.django_db
def test_missing_real_facts_persists_blocked_research_only_evidence() -> None:
    repository = DjangoIndustryTemplateRepository()
    repository.append_template(_template())

    result = RunIndustryOperatingTemplate(
        repository=repository,
        fact_provider=_MissingFactProvider(),
    ).execute(replace(_request(), run_key="NO_DATA_RUN"))

    assert result.status is TemplateRunStatus.BLOCKED
    assert result.forecast_draft is None
    assert any(reason.startswith("pit_fact_missing:") for reason in result.blocked_reasons)
    evidence = IndustryTemplateRunEvidenceModel._default_manager.get(run_key="NO_DATA_RUN")
    assert evidence.research_only is True
    assert evidence.must_not_use_for_decision is True
    assert evidence.must_not_execute is True
