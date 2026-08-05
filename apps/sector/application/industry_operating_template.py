"""Fail-closed orchestration for Sector-owned R1 industry templates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from apps.sector.domain.industry_operating_template import (
    DriverDefinition,
    DriverInputKind,
    FinancialStage,
    ForecastAssumptionDraft,
    ForecastProjectionDraft,
    ForecastScenario,
    ImmutableTemplateRunEvidence,
    IndustryOperatingTemplate,
    IndustryTemplateRunResult,
    OperatingForecastDraft,
    PITDriverFact,
    ScenarioDriverOverride,
    TemplateEvaluationError,
    TemplateRunStatus,
    build_template_run_evidence,
    evaluate_template,
)


class IndustryTemplateRepository(Protocol):
    """Append-only persistence boundary for templates and run evidence."""

    def append_template(
        self,
        template: IndustryOperatingTemplate,
    ) -> IndustryOperatingTemplate:
        """Append one immutable template version."""

    def get_template(
        self,
        *,
        template_code: str,
        template_version: int,
    ) -> IndustryOperatingTemplate | None:
        """Return one exact immutable template version."""

    def append_run_evidence(
        self,
        evidence: ImmutableTemplateRunEvidence,
    ) -> ImmutableTemplateRunEvidence:
        """Append one exact research-only run evidence version."""

    def get_run_evidence(
        self,
        *,
        run_key: str,
        run_version: int,
    ) -> ImmutableTemplateRunEvidence | None:
        """Return one exact immutable run evidence version."""


class OperatingDriverFactProvider(Protocol):
    """Resolve one Data Center operating fact under an explicit PIT clock."""

    def get_fact(
        self,
        driver: DriverDefinition,
        *,
        subject_code: str,
        as_of_time: datetime,
    ) -> PITDriverFact | None:
        """Return the latest eligible fact known at ``as_of_time``."""


@dataclass(frozen=True)
class IndustryTemplateRunRequest:
    """Versioned forecast-draft request with explicit three-scenario overrides."""

    run_key: str
    run_version: int
    template_code: str
    template_version: int
    forecast_id: str
    forecast_key: str
    forecast_version: int
    subject_code: str
    industry_code: str
    as_of_time: datetime
    target_period_end: date
    horizon_quarters: int
    created_by_ref: str
    overrides: tuple[ScenarioDriverOverride, ...]

    def __post_init__(self) -> None:
        for value, field_name, maximum in (
            (self.run_key, "run_key", 128),
            (self.template_code, "template_code", 80),
            (self.forecast_id, "forecast_id", 64),
            (self.forecast_key, "forecast_key", 128),
            (self.subject_code, "subject_code", 80),
            (self.industry_code, "industry_code", 80),
            (self.created_by_ref, "created_by_ref", 128),
        ):
            if (
                not value.strip()
                or len(value) > maximum
                or any(character.isspace() for character in value)
            ):
                raise ValueError(f"IndustryTemplateRunRequest.{field_name} is invalid")
        for version_value, field_name in (
            (self.run_version, "run_version"),
            (self.template_version, "template_version"),
            (self.forecast_version, "forecast_version"),
            (self.horizon_quarters, "horizon_quarters"),
        ):
            if isinstance(version_value, bool) or version_value <= 0:
                raise ValueError(f"IndustryTemplateRunRequest.{field_name} must be positive")
        if self.as_of_time.tzinfo is None or self.as_of_time.utcoffset() is None:
            raise ValueError("IndustryTemplateRunRequest.as_of_time must be timezone-aware")
        if self.target_period_end < self.as_of_time.date():
            raise ValueError("target_period_end cannot precede as_of_time")
        identities = {(item.scenario, item.driver_key) for item in self.overrides}
        if len(identities) != len(self.overrides):
            raise ValueError("scenario driver overrides must be unique")


class IndustryTemplateGovernanceFacade:
    """Application entry point for caller-supplied template versions."""

    def __init__(self, repository: IndustryTemplateRepository) -> None:
        self._repository = repository

    def register_template(
        self,
        template: IndustryOperatingTemplate,
    ) -> IndustryOperatingTemplate:
        """Append an immutable template without adding business seed data."""

        return self._repository.append_template(template)


class RunIndustryOperatingTemplate:
    """Resolve PIT facts and calculate all scenarios or fail closed."""

    def __init__(
        self,
        *,
        repository: IndustryTemplateRepository,
        fact_provider: OperatingDriverFactProvider,
    ) -> None:
        self._repository = repository
        self._fact_provider = fact_provider

    def execute(self, request: IndustryTemplateRunRequest) -> IndustryTemplateRunResult:
        """Return and persist one research-only forecast draft or blocked result."""

        template = self._repository.get_template(
            template_code=request.template_code,
            template_version=request.template_version,
        )
        if template is None:
            return self._persist_blocked(
                request=request,
                template=None,
                facts=(),
                blockers={"template_version_missing"},
            )
        blockers: set[str] = set()
        if template.industry_code != request.industry_code:
            blockers.add("template_industry_mismatch")
        if not template.is_effective_at(request.as_of_time):
            blockers.add(f"template_{template.lifecycle.value}")

        drivers = {driver.driver_key: driver for driver in template.drivers}
        overrides = {
            (override.scenario, override.driver_key): override for override in request.overrides
        }
        for override in request.overrides:
            driver = drivers.get(override.driver_key)
            if driver is None:
                blockers.add(f"override_driver_unknown:{override.driver_key}")
            elif override.unit != driver.unit:
                blockers.add(f"override_unit_mismatch:{override.driver_key}")
            elif override.input_kind not in driver.allowed_input_kinds:
                blockers.add(f"override_input_kind_forbidden:{override.driver_key}")

        facts_by_driver: dict[str, PITDriverFact] = {}
        for driver in template.drivers:
            requires_fact = any(
                (scenario, driver.driver_key) not in overrides for scenario in ForecastScenario
            )
            if not requires_fact:
                continue
            if DriverInputKind.OBSERVED_FACT not in driver.allowed_input_kinds:
                continue
            try:
                fact = self._fact_provider.get_fact(
                    driver,
                    subject_code=request.subject_code,
                    as_of_time=request.as_of_time,
                )
            except ValueError:
                blockers.add(f"pit_fact_invalid:{driver.driver_key}")
                continue
            if fact is None:
                blockers.add(f"pit_fact_missing:{driver.driver_key}")
                continue
            if not self._fact_matches_driver(
                fact,
                driver=driver,
                subject_code=request.subject_code,
                as_of_time=request.as_of_time,
            ):
                blockers.add(f"pit_fact_mismatch:{driver.driver_key}")
                continue
            facts_by_driver[driver.driver_key] = fact

        assumptions: list[ForecastAssumptionDraft] = []
        projections: list[ForecastProjectionDraft] = []
        for scenario in ForecastScenario:
            driver_values: dict[str, Decimal] = {}
            scenario_assumptions: list[ForecastAssumptionDraft] = []
            for driver in template.drivers:
                scenario_override = overrides.get((scenario, driver.driver_key))
                if scenario_override is not None:
                    if (
                        scenario_override.unit != driver.unit
                        or scenario_override.input_kind not in driver.allowed_input_kinds
                    ):
                        continue
                    driver_values[driver.driver_key] = scenario_override.value
                    scenario_assumptions.append(
                        ForecastAssumptionDraft(
                            scenario=scenario,
                            assumption_key=driver.driver_key,
                            value=scenario_override.value,
                            unit=scenario_override.unit,
                            input_kind=scenario_override.input_kind,
                            rationale=scenario_override.rationale,
                            human_assumption_ref=(
                                scenario_override.lineage_ref
                                if scenario_override.input_kind is DriverInputKind.HUMAN_ASSUMPTION
                                else ""
                            ),
                            model_version=(
                                scenario_override.lineage_ref
                                if scenario_override.input_kind is DriverInputKind.MODEL_INFERENCE
                                else ""
                            ),
                        )
                    )
                    continue
                fact = facts_by_driver.get(driver.driver_key)
                if fact is None:
                    blockers.add(f"driver_missing:{scenario.value}:{driver.driver_key}")
                    continue
                driver_values[driver.driver_key] = fact.value
                scenario_assumptions.append(
                    ForecastAssumptionDraft(
                        scenario=scenario,
                        assumption_key=driver.driver_key,
                        value=fact.value,
                        unit=fact.unit,
                        input_kind=DriverInputKind.OBSERVED_FACT,
                        rationale=f"Verified PIT operating fact {fact.version_id}",
                        observed_fact_version_id=fact.version_id,
                    )
                )
            if len(driver_values) != len(template.drivers):
                continue
            try:
                stage_values = evaluate_template(template, driver_values)
            except TemplateEvaluationError as exc:
                blockers.add(f"calculation_blocked:{scenario.value}:{exc}")
                continue
            values_by_stage = {value.stage: value for value in stage_values}
            revenue = values_by_stage[FinancialStage.REVENUE]
            net_profit = values_by_stage[FinancialStage.NET_PROFIT]
            cash_flow = values_by_stage[FinancialStage.CASH_FLOW]
            if revenue.value <= 0:
                blockers.add(f"revenue_non_positive:{scenario.value}")
                continue
            assumptions.extend(scenario_assumptions)
            projections.append(
                ForecastProjectionDraft(
                    scenario=scenario,
                    revenue=revenue.value,
                    net_profit=net_profit.value,
                    cash_flow=cash_flow.value,
                    currency_unit=revenue.unit,
                    stage_values=stage_values,
                )
            )

        facts = tuple(
            sorted(
                {fact.version_id: fact for fact in facts_by_driver.values()}.values(),
                key=lambda item: item.version_id,
            )
        )
        if blockers or len(projections) != len(ForecastScenario):
            return self._persist_blocked(
                request=request,
                template=template,
                facts=facts,
                blockers=blockers or {"scenario_projection_incomplete"},
            )
        draft = OperatingForecastDraft(
            forecast_id=request.forecast_id,
            forecast_key=request.forecast_key,
            forecast_version=request.forecast_version,
            subject_code=request.subject_code,
            industry_code=request.industry_code,
            as_of_time=request.as_of_time,
            target_period_end=request.target_period_end,
            horizon_quarters=request.horizon_quarters,
            methodology_ref=template.methodology_ref,
            created_by_ref=request.created_by_ref,
            template_code=template.template_code,
            template_version=template.template_version,
            template_content_hash=template.content_hash,
            fact_version_ids=tuple(fact.version_id for fact in facts),
            assumptions=tuple(assumptions),
            projections=tuple(projections),
        )
        result = IndustryTemplateRunResult(
            run_key=request.run_key,
            run_version=request.run_version,
            template_code=template.template_code,
            template_version=template.template_version,
            template_content_hash=template.content_hash,
            subject_code=request.subject_code,
            industry_code=request.industry_code,
            as_of_time=request.as_of_time,
            status=TemplateRunStatus.AVAILABLE,
            facts=facts,
            forecast_draft=draft,
            blocked_reasons=(),
        )
        self._repository.append_run_evidence(build_template_run_evidence(result))
        return result

    @staticmethod
    def _fact_matches_driver(
        fact: PITDriverFact,
        *,
        driver: DriverDefinition,
        subject_code: str,
        as_of_time: datetime,
    ) -> bool:
        """Check PIT clocks, source, revision and measurement semantics exactly."""

        return (
            fact.is_verified
            and fact.metric_code == driver.metric_code
            and fact.metric_definition_version == driver.metric_definition_version
            and fact.subject_code == subject_code
            and fact.unit == driver.unit
            and fact.frequency == driver.frequency
            and fact.source == driver.source
            and fact.effective_at <= as_of_time
            and fact.available_at <= as_of_time
        )

    def _persist_blocked(
        self,
        *,
        request: IndustryTemplateRunRequest,
        template: IndustryOperatingTemplate | None,
        facts: tuple[PITDriverFact, ...],
        blockers: set[str],
    ) -> IndustryTemplateRunResult:
        """Persist a blocked run without leaking partial projections."""

        result = IndustryTemplateRunResult(
            run_key=request.run_key,
            run_version=request.run_version,
            template_code=request.template_code,
            template_version=request.template_version,
            template_content_hash=template.content_hash if template is not None else "",
            subject_code=request.subject_code,
            industry_code=request.industry_code,
            as_of_time=request.as_of_time,
            status=TemplateRunStatus.BLOCKED,
            facts=facts,
            forecast_draft=None,
            blocked_reasons=tuple(sorted(blockers)),
        )
        self._repository.append_run_evidence(build_template_run_evidence(result))
        return result


__all__ = [
    "IndustryTemplateGovernanceFacade",
    "IndustryTemplateRepository",
    "IndustryTemplateRunRequest",
    "OperatingDriverFactProvider",
    "RunIndustryOperatingTemplate",
]
