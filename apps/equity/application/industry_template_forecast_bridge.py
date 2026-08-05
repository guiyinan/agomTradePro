"""Typed bridge from an available Sector template run to the Equity ledger."""

from __future__ import annotations

from dataclasses import dataclass

from apps.equity.application.operating_forecast import (
    CreateOperatingForecastCommand,
    CreateOperatingForecastVersionUseCase,
    IndustryTemplateRunEvidenceProvider,
    OperatingFactEvidenceProvider,
    OperatingForecastEvidenceError,
    OperatingForecastTemplateEvidenceError,
)
from apps.equity.domain.operating_forecast import (
    ForecastInputKind,
    ForecastScenario,
    OperatingFactEvidence,
    OperatingForecastAssumption,
    OperatingForecastProjection,
    OperatingForecastStage,
    OperatingForecastStageValue,
    OperatingForecastVersion,
    ValuationSensitivityPoint,
)
from apps.sector.domain.industry_operating_template import (
    DriverInputKind,
    ForecastAssumptionDraft,
    TemplateRunStatus,
    restore_template_run_result,
)


@dataclass(frozen=True)
class ScenarioValuationSensitivities:
    """Valuation-owned sensitivity points added after the Sector calculation."""

    scenario: ForecastScenario
    points: tuple[ValuationSensitivityPoint, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, ForecastScenario):
            raise ValueError("ScenarioValuationSensitivities.scenario is invalid")
        if not self.points:
            raise ValueError("ScenarioValuationSensitivities.points cannot be empty")


@dataclass(frozen=True)
class CreateForecastFromIndustryTemplateCommand:
    """Persisted Sector run identity plus Equity-owned sensitivity evidence."""

    run_key: str
    run_version: int
    sensitivities: tuple[ScenarioValuationSensitivities, ...]

    def __post_init__(self) -> None:
        if (
            not self.run_key.strip()
            or len(self.run_key) > 128
            or any(character.isspace() for character in self.run_key)
        ):
            raise ValueError("run_key must be a non-blank token")
        if isinstance(self.run_version, bool) or self.run_version <= 0:
            raise ValueError("run_version must be positive")
        scenarios = [item.scenario for item in self.sensitivities]
        if set(scenarios) != set(ForecastScenario) or len(scenarios) != len(ForecastScenario):
            raise ValueError("bridge sensitivities must contain exactly base, bull and bear")


class CreateForecastFromIndustryTemplate:
    """Verify a persisted available Sector run and append its full Equity projection."""

    def __init__(
        self,
        *,
        writer: CreateOperatingForecastVersionUseCase,
        fact_provider: OperatingFactEvidenceProvider,
        run_evidence_provider: IndustryTemplateRunEvidenceProvider,
    ) -> None:
        self._writer = writer
        self._fact_provider = fact_provider
        self._run_evidence_provider = run_evidence_provider

    def execute(
        self,
        command: CreateForecastFromIndustryTemplateCommand,
    ) -> OperatingForecastVersion:
        """Map every draft field without writing or mutating Sector history."""

        evidence = self._run_evidence_provider.get_run_evidence(
            run_key=command.run_key,
            run_version=command.run_version,
        )
        if evidence is None:
            raise OperatingForecastTemplateEvidenceError(
                "industry template run evidence is missing"
            )
        try:
            result = restore_template_run_result(evidence)
        except ValueError as exc:
            raise OperatingForecastTemplateEvidenceError(
                "industry template run evidence is invalid"
            ) from exc
        if result.status is not TemplateRunStatus.AVAILABLE or result.forecast_draft is None:
            raise OperatingForecastTemplateEvidenceError(
                "only an available industry template run can enter the Equity ledger"
            )
        draft = result.forecast_draft
        facts = self._fact_provider.get_operating_facts(
            draft.fact_version_ids,
            as_of_time=draft.as_of_time,
        )
        facts_by_id = {fact.version_id: fact for fact in facts}
        if set(facts_by_id) != set(draft.fact_version_ids) or len(facts) != len(
            draft.fact_version_ids
        ):
            raise OperatingForecastEvidenceError(
                "industry forecast PIT facts must resolve exactly without substitution"
            )
        assumptions = tuple(
            self._map_assumption(item, facts_by_id=facts_by_id) for item in draft.assumptions
        )
        sensitivity_by_scenario = {item.scenario: item.points for item in command.sensitivities}
        projections = tuple(
            OperatingForecastProjection(
                scenario=ForecastScenario(item.scenario.value),
                revenue=item.revenue,
                net_profit=item.net_profit,
                cash_flow=item.cash_flow,
                currency_unit=item.currency_unit,
                stage_values=tuple(
                    OperatingForecastStageValue(
                        stage=OperatingForecastStage(stage.stage.value),
                        node_key=stage.node_key,
                        value=stage.value,
                        unit=stage.unit,
                    )
                    for stage in item.stage_values
                ),
                sensitivities=sensitivity_by_scenario[ForecastScenario(item.scenario.value)],
            )
            for item in draft.projections
        )
        create_command = CreateOperatingForecastCommand(
            forecast_id=draft.forecast_id,
            forecast_key=draft.forecast_key,
            forecast_version=draft.forecast_version,
            subject_code=draft.subject_code,
            industry_code=draft.industry_code,
            as_of_time=draft.as_of_time,
            target_period_end=draft.target_period_end,
            horizon_quarters=draft.horizon_quarters,
            methodology_ref=draft.methodology_ref,
            created_by_ref=draft.created_by_ref,
            template_code=draft.template_code,
            template_version=draft.template_version,
            template_content_hash=draft.template_content_hash,
            template_run_key=result.run_key,
            template_run_version=result.run_version,
            template_run_content_hash=result.content_hash,
            fact_version_ids=draft.fact_version_ids,
            assumptions=assumptions,
            projections=projections,
            valuation_consumable=False,
            promotion_decision_id="",
        )
        return self._writer.execute(create_command)

    @staticmethod
    def _map_assumption(
        item: ForecastAssumptionDraft,
        *,
        facts_by_id: dict[int, OperatingFactEvidence],
    ) -> OperatingForecastAssumption:
        """Narrow one Sector draft assumption and bind observed facts exactly."""
        scenario = ForecastScenario(item.scenario.value)
        input_kind = ForecastInputKind(item.input_kind.value)
        if item.input_kind is DriverInputKind.OBSERVED_FACT:
            fact = facts_by_id.get(item.observed_fact_version_id or 0)
            if fact is None:
                raise OperatingForecastEvidenceError(
                    "industry forecast assumption references an unknown PIT fact"
                )
            return OperatingForecastAssumption(
                scenario=scenario,
                assumption_key=item.assumption_key,
                value=item.value,
                unit=item.unit,
                input_kind=input_kind,
                rationale=item.rationale,
                observed_fact_version_id=fact.version_id,
                observed_metric_code=fact.metric_code,
                observed_fact_content_hash=fact.content_hash,
                observed_subject_type=fact.subject_type,
                observed_subject_code=fact.subject_code,
            )
        return OperatingForecastAssumption(
            scenario=scenario,
            assumption_key=item.assumption_key,
            value=item.value,
            unit=item.unit,
            input_kind=input_kind,
            rationale=item.rationale,
            human_assumption_ref=item.human_assumption_ref,
            model_version=item.model_version,
        )


__all__ = [
    "CreateForecastFromIndustryTemplate",
    "CreateForecastFromIndustryTemplateCommand",
    "ScenarioValuationSensitivities",
]
