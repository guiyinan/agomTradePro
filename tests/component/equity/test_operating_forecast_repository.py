"""Component coverage for the R1 Sector-to-Equity forecast boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.data_center.domain.research_data_foundation import (
    OPERATING_OBSERVATION_DATASET,
)
from apps.data_center.infrastructure.pit_models import PITFactVersionModel
from apps.equity.application.industry_template_forecast_bridge import (
    CreateForecastFromIndustryTemplate,
    CreateForecastFromIndustryTemplateCommand,
    ScenarioValuationSensitivities,
)
from apps.equity.application.operating_forecast import (
    CreateOperatingForecastVersionUseCase,
    OperatingForecastConflictError,
    OperatingForecastEvidenceError,
    OperatingForecastTemplateEvidenceError,
    RecordQuarterlyActualCommand,
    RecordQuarterlyOperatingActualUseCase,
)
from apps.equity.domain.operating_forecast import (
    ForecastScenario,
    OperatingFactEvidence,
    OperatingForecastStage,
    OperatingForecastVersion,
    ValuationSensitivityPoint,
)
from apps.equity.infrastructure.operating_forecast_models import (
    OperatingForecastAssumptionModel,
    OperatingForecastEvaluationModel,
    OperatingForecastFactReferenceModel,
    OperatingForecastProjectionModel,
    OperatingForecastSensitivityModel,
    OperatingForecastStageValueModel,
    OperatingForecastVersionModel,
)
from apps.equity.infrastructure.operating_forecast_repository import (
    DjangoOperatingFactEvidenceProvider,
    DjangoOperatingForecastRepository,
)
from apps.sector.application.industry_operating_template import (
    RunIndustryOperatingTemplate,
)
from apps.sector.domain.industry_operating_template import (
    IndustryTemplateRunResult,
    TemplateRunStatus,
)
from apps.sector.infrastructure.industry_operating_template_models import (
    IndustryTemplateRunEvidenceModel,
)
from apps.sector.infrastructure.industry_operating_template_repository import (
    DjangoIndustryTemplateRepository,
)
from tests.unit.sector.test_industry_operating_template import _FactProvider as SectorFactProvider
from tests.unit.sector.test_industry_operating_template import (
    _request,
    _template,
)


class _PromotionChecker:
    def is_approved(self, decision_id: str) -> bool:
        del decision_id
        return True


class _ExactFactProvider:
    def __init__(self, facts: tuple[OperatingFactEvidence, ...]) -> None:
        self._facts = {fact.version_id: fact for fact in facts}

    def get_operating_facts(
        self,
        version_ids: tuple[int, ...],
        *,
        as_of_time: datetime,
    ) -> tuple[OperatingFactEvidence, ...]:
        del as_of_time
        return tuple(self._facts[version_id] for version_id in version_ids)


def _equity_facts(result: IndustryTemplateRunResult) -> tuple[OperatingFactEvidence, ...]:
    return tuple(
        OperatingFactEvidence(
            version_id=fact.version_id,
            dataset=fact.dataset,
            business_key=fact.business_key,
            metric_code=fact.metric_code,
            subject_type="company",
            subject_code=result.subject_code,
            effective_at=fact.effective_at,
            available_at=fact.available_at,
            source_record_id=fact.source_record_id,
            content_hash=fact.content_hash,
            value=fact.value,
            unit=fact.unit,
        )
        for fact in result.facts
    )


def _sensitivities(
    *,
    output_delta: Decimal = Decimal("0"),
) -> tuple[ScenarioValuationSensitivities, ...]:
    outputs = {
        ForecastScenario.BASE: Decimal("1200"),
        ForecastScenario.BULL: Decimal("1500"),
        ForecastScenario.BEAR: Decimal("700"),
    }
    return tuple(
        ScenarioValuationSensitivities(
            scenario=scenario,
            points=(
                ValuationSensitivityPoint(
                    sensitivity_key="pe_multiple",
                    input_value=Decimal("10"),
                    input_unit="multiple",
                    output_value=output + output_delta,
                    output_unit="CNY",
                    method_version="valuation-sensitivity-v1",
                    source_artifact_ref=(f"valuation://worksheet/TEST_RUN/{scenario.value}/v1"),
                    source_artifact_hash=(
                        {
                            ForecastScenario.BASE: "a",
                            ForecastScenario.BULL: "b",
                            ForecastScenario.BEAR: "c",
                        }[scenario]
                        * 64
                    ),
                ),
            ),
        )
        for scenario, output in outputs.items()
    )


def _persist_sector_run(
    *,
    as_of_time: datetime,
) -> tuple[
    DjangoIndustryTemplateRepository,
    IndustryTemplateRunResult,
    tuple[OperatingFactEvidence, ...],
]:
    sector_repository = DjangoIndustryTemplateRepository()
    template = sector_repository.append_template(_template())
    request = replace(_request(), as_of_time=as_of_time)
    result = RunIndustryOperatingTemplate(
        repository=sector_repository,
        fact_provider=SectorFactProvider(template),
    ).execute(request)
    assert result.status is TemplateRunStatus.AVAILABLE
    return sector_repository, result, _equity_facts(result)


def _build_bridge(
    *,
    sector_repository: DjangoIndustryTemplateRepository,
    facts: tuple[OperatingFactEvidence, ...],
) -> tuple[CreateForecastFromIndustryTemplate, DjangoOperatingForecastRepository]:
    equity_repository = DjangoOperatingForecastRepository()
    fact_provider = _ExactFactProvider(facts)
    writer = CreateOperatingForecastVersionUseCase(
        repository=equity_repository,
        fact_provider=fact_provider,
        promotion_checker=_PromotionChecker(),
        template_run_evidence_provider=sector_repository,
    )
    return (
        CreateForecastFromIndustryTemplate(
            writer=writer,
            fact_provider=fact_provider,
            run_evidence_provider=sector_repository,
        ),
        equity_repository,
    )


def _append_operating_fact(
    *,
    business_key: str,
    effective_at: datetime,
    available_at: datetime,
    revision_number: int = 0,
    value_kind: str = "observed_fact",
    pit_quality: str = "verified",
    value: str = "100",
) -> PITFactVersionModel:
    payload = {
        "metric_code": "store_count",
        "definition_version": 1,
        "subject_type": "company",
        "subject_code": "000001.SZ",
        "effective_at": effective_at.isoformat(),
        "effective_to": None,
        "available_at": available_at.isoformat(),
        "revision_number": revision_number,
        "value": value,
        "unit": "count",
        "frequency": "quarterly",
        "source": "licensed-report",
        "value_kind": value_kind,
        "source_record_id": f"source-{business_key}-{revision_number}",
        "assumption_set_id": "" if value_kind == "observed_fact" else "assumption-v1",
        "model_version": "",
    }
    return PITFactVersionModel._default_manager.create(
        dataset=OPERATING_OBSERVATION_DATASET,
        business_key=business_key,
        effective_at=effective_at,
        effective_to=None,
        available_at=available_at,
        ingested_at=available_at,
        superseded_at=None,
        revision_number=revision_number,
        source_record_id=f"source-{business_key}-{revision_number}",
        content_hash=f"{business_key}-{revision_number}".encode().hex().ljust(64, "0")[:64],
        pit_quality=pit_quality,
        payload=payload,
    )


def _actual_fact(
    *,
    version_id: int,
    metric_code: str,
    value: str,
    content_hash_character: str,
) -> OperatingFactEvidence:
    return OperatingFactEvidence(
        version_id=version_id,
        dataset="research.operating_observation.v1",
        business_key=f"{metric_code}|TEST.ASSET|2025Q2",
        metric_code=metric_code,
        subject_type="company",
        subject_code="TEST.ASSET",
        effective_at=datetime(2025, 6, 30, tzinfo=UTC),
        available_at=datetime(2025, 8, 15, tzinfo=UTC),
        source_record_id=f"quarterly-report-{version_id}",
        content_hash=content_hash_character * 64,
        value=Decimal(value),
        unit="CNY",
    )


@pytest.mark.django_db
def test_operating_fact_provider_rejects_inference_and_superseded_versions() -> None:
    as_of = datetime(2026, 4, 30, 8, tzinfo=UTC)
    inferred = _append_operating_fact(
        business_key="inferred-kpi",
        effective_at=datetime(2026, 3, 31, tzinfo=UTC),
        available_at=datetime(2026, 4, 20, tzinfo=UTC),
        value_kind="human_assumption",
        pit_quality="estimated",
    )
    provider = DjangoOperatingFactEvidenceProvider()
    with pytest.raises(OperatingForecastEvidenceError, match="verified PIT quality"):
        provider.get_operating_facts((inferred.pk,), as_of_time=as_of)

    old = _append_operating_fact(
        business_key="revised-kpi",
        effective_at=datetime(2026, 3, 31, tzinfo=UTC),
        available_at=datetime(2026, 4, 10, tzinfo=UTC),
    )
    latest = _append_operating_fact(
        business_key="revised-kpi",
        effective_at=datetime(2026, 3, 31, tzinfo=UTC),
        available_at=datetime(2026, 4, 20, tzinfo=UTC),
        revision_number=1,
        value="101",
    )
    with pytest.raises(OperatingForecastEvidenceError, match="latest public"):
        provider.get_operating_facts((old.pk,), as_of_time=as_of)
    assert provider.get_operating_facts((latest.pk,), as_of_time=as_of)[0].value == Decimal("101")


@pytest.mark.django_db
def test_persisted_sector_run_bridges_with_utc_canonical_round_trip_and_idempotency() -> None:
    plus_eight = timezone(timedelta(hours=8))
    sector_repository, result, facts = _persist_sector_run(
        as_of_time=datetime(2025, 3, 31, 8, tzinfo=plus_eight)
    )
    bridge, equity_repository = _build_bridge(
        sector_repository=sector_repository,
        facts=facts,
    )
    command = CreateForecastFromIndustryTemplateCommand(
        run_key=result.run_key,
        run_version=result.run_version,
        sensitivities=_sensitivities(),
    )

    stored = bridge.execute(command)
    replay = bridge.execute(command)

    assert isinstance(stored, OperatingForecastVersion)
    assert replay.content_hash == stored.content_hash
    assert stored.as_of_time.astimezone(UTC) == datetime(2025, 3, 31, tzinfo=UTC)
    assert stored.valuation_consumable is False
    assert stored.promotion_decision_id == ""
    assert {projection.cash_flow for projection in stored.projections}
    assert all(
        {stage.stage for stage in projection.stage_values} == set(OperatingForecastStage)
        for projection in stored.projections
    )
    assert OperatingForecastVersionModel._default_manager.count() == 1
    assert OperatingForecastFactReferenceModel._default_manager.count() == 3
    assert OperatingForecastAssumptionModel._default_manager.count() == 15
    assert OperatingForecastProjectionModel._default_manager.count() == 3
    assert OperatingForecastStageValueModel._default_manager.count() == 18
    assert OperatingForecastSensitivityModel._default_manager.count() == 3
    assert IndustryTemplateRunEvidenceModel._default_manager.count() == 1

    loaded = equity_repository.get_version(stored.forecast_id)
    assert isinstance(loaded, OperatingForecastVersion)
    assert loaded.content_hash == stored.content_hash
    assert loaded.template_run_content_hash == result.content_hash

    with pytest.raises(OperatingForecastConflictError, match="conflicting immutable"):
        bridge.execute(
            replace(
                command,
                sensitivities=_sensitivities(output_delta=Decimal("1")),
            )
        )


@pytest.mark.django_db
def test_bridge_blocks_missing_and_blocked_persisted_runs() -> None:
    repository = DjangoIndustryTemplateRepository()
    empty_bridge, _ = _build_bridge(sector_repository=repository, facts=())
    command = CreateForecastFromIndustryTemplateCommand(
        run_key="MISSING_RUN",
        run_version=1,
        sensitivities=_sensitivities(),
    )
    with pytest.raises(OperatingForecastTemplateEvidenceError, match="missing"):
        empty_bridge.execute(command)

    template = repository.append_template(_template())

    class _MissingSectorFactProvider:
        def get_fact(
            self,
            driver: object,
            *,
            subject_code: str,
            as_of_time: datetime,
        ) -> None:
            del driver, subject_code, as_of_time
            return None

    blocked = RunIndustryOperatingTemplate(
        repository=repository,
        fact_provider=_MissingSectorFactProvider(),
    ).execute(replace(_request(), run_key="BLOCKED_RUN"))
    assert blocked.status is TemplateRunStatus.BLOCKED
    blocked_bridge, _ = _build_bridge(sector_repository=repository, facts=())
    with pytest.raises(OperatingForecastTemplateEvidenceError, match="only an available"):
        blocked_bridge.execute(replace(command, run_key="BLOCKED_RUN"))
    assert template.template_code == "TEST_TEMPLATE"


@pytest.mark.django_db
def test_child_write_failure_rolls_back_all_equity_rows_but_preserves_sector_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sector_repository, result, facts = _persist_sector_run(
        as_of_time=datetime(2025, 3, 31, tzinfo=UTC)
    )
    bridge, _ = _build_bridge(sector_repository=sector_repository, facts=facts)

    def fail_bulk_create(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("injected sensitivity child failure")

    monkeypatch.setattr(
        OperatingForecastSensitivityModel._default_manager,
        "bulk_create",
        fail_bulk_create,
    )
    with pytest.raises(RuntimeError, match="injected sensitivity"):
        bridge.execute(
            CreateForecastFromIndustryTemplateCommand(
                run_key=result.run_key,
                run_version=result.run_version,
                sensitivities=_sensitivities(),
            )
        )

    for model in (
        OperatingForecastVersionModel,
        OperatingForecastFactReferenceModel,
        OperatingForecastAssumptionModel,
        OperatingForecastProjectionModel,
        OperatingForecastStageValueModel,
        OperatingForecastSensitivityModel,
    ):
        assert model._default_manager.count() == 0
    assert IndustryTemplateRunEvidenceModel._default_manager.count() == 1


@pytest.mark.django_db
def test_base_manager_cannot_bypass_equity_or_sector_append_only_guards() -> None:
    sector_repository, result, facts = _persist_sector_run(
        as_of_time=datetime(2025, 3, 31, tzinfo=UTC)
    )
    bridge, _ = _build_bridge(sector_repository=sector_repository, facts=facts)
    stored = bridge.execute(
        CreateForecastFromIndustryTemplateCommand(
            run_key=result.run_key,
            run_version=result.run_version,
            sensitivities=_sensitivities(),
        )
    )
    header = OperatingForecastVersionModel._default_manager.get(pk=stored.forecast_id)
    stage = OperatingForecastStageValueModel._default_manager.first()
    sector_evidence = IndustryTemplateRunEvidenceModel._default_manager.get()
    assert stage is not None

    for model, instance, field, value in (
        (OperatingForecastVersionModel, header, "subject_code", "MUTATED"),
        (OperatingForecastStageValueModel, stage, "node_key", "MUTATED"),
        (IndustryTemplateRunEvidenceModel, sector_evidence, "status", "blocked"),
    ):
        with pytest.raises(ValidationError, match="cannot be updated"):
            model._base_manager.filter(pk=instance.pk).update(**{field: value})
        setattr(instance, field, value)
        with pytest.raises(ValidationError, match="bulk updated"):
            model._base_manager.bulk_update([instance], [field])
        with pytest.raises(ValidationError, match="cannot be deleted"):
            model._base_manager.filter(pk=instance.pk).delete()


@pytest.mark.django_db
def test_forecast_get_version_has_constant_prefetch_query_count(
    django_assert_num_queries: object,
) -> None:
    sector_repository, result, facts = _persist_sector_run(
        as_of_time=datetime(2025, 3, 31, tzinfo=UTC)
    )
    bridge, repository = _build_bridge(sector_repository=sector_repository, facts=facts)
    stored = bridge.execute(
        CreateForecastFromIndustryTemplateCommand(
            run_key=result.run_key,
            run_version=result.run_version,
            sensitivities=_sensitivities(),
        )
    )

    with django_assert_num_queries(6):  # type: ignore[operator]
        loaded = repository.get_version(stored.forecast_id)
    assert isinstance(loaded, OperatingForecastVersion)


@pytest.mark.django_db
def test_quarterly_evaluations_round_trip_idempotency_conflict_and_append_only() -> None:
    sector_repository, result, facts = _persist_sector_run(
        as_of_time=datetime(2025, 3, 31, tzinfo=UTC)
    )
    bridge, repository = _build_bridge(sector_repository=sector_repository, facts=facts)
    stored = bridge.execute(
        CreateForecastFromIndustryTemplateCommand(
            run_key=result.run_key,
            run_version=result.run_version,
            sensitivities=_sensitivities(),
        )
    )
    actual_facts = (
        _actual_fact(
            version_id=901,
            metric_code="revenue",
            value="900",
            content_hash_character="d",
        ),
        _actual_fact(
            version_id=902,
            metric_code="net_profit",
            value="200",
            content_hash_character="e",
        ),
    )
    recorded_at = datetime(2025, 8, 20, tzinfo=UTC)
    command = RecordQuarterlyActualCommand(
        forecast_id=stored.forecast_id,
        actual_period_end=stored.target_period_end,
        recorded_at=recorded_at,
        actual_fact_version_ids=(901, 902),
        actual_revenue=Decimal("900"),
        actual_net_profit=Decimal("200"),
        currency_unit="CNY",
    )
    use_case = RecordQuarterlyOperatingActualUseCase(
        repository,
        _ExactFactProvider(actual_facts),
    )

    evaluations = use_case.execute(command)
    replay = use_case.execute(command)

    assert len(evaluations) == 3
    assert replay == evaluations
    assert OperatingForecastEvaluationModel._default_manager.count() == 3
    base = OperatingForecastEvaluationModel._default_manager.get(scenario="base")
    assert base.revenue_error == Decimal("100")
    assert base.net_profit_error == Decimal("100")
    assert {item["version_id"] for item in base.actual_fact_evidence} == {901, 902}

    conflicting_facts = (
        actual_facts[0],
        _actual_fact(
            version_id=902,
            metric_code="net_profit",
            value="201",
            content_hash_character="f",
        ),
    )
    conflicting_use_case = RecordQuarterlyOperatingActualUseCase(
        repository,
        _ExactFactProvider(conflicting_facts),
    )
    with pytest.raises(OperatingForecastConflictError, match="conflicting immutable"):
        conflicting_use_case.execute(replace(command, actual_net_profit=Decimal("201")))
    assert OperatingForecastEvaluationModel._default_manager.count() == 3

    base.revenue_error = Decimal("999")
    with pytest.raises(ValidationError, match="immutable"):
        base.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        OperatingForecastEvaluationModel._base_manager.filter(pk=base.pk).update(
            revenue_error=Decimal("999")
        )
    with pytest.raises(ValidationError, match="bulk updated"):
        OperatingForecastEvaluationModel._base_manager.bulk_update(
            [base],
            ["revenue_error"],
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        OperatingForecastEvaluationModel._base_manager.filter(pk=base.pk).delete()
