"""Django adapters for the Equity operating-forecast ledger."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.db.models import Prefetch

from apps.data_center.application.research_data_foundation import (
    get_research_data_foundation_facade,
)
from apps.data_center.domain.pit import PITFactVersion, PITQuality
from apps.equity.application.operating_forecast import (
    OperatingForecastConflictError,
    OperatingForecastEvidenceError,
)
from apps.equity.domain.operating_forecast import (
    ForecastInputKind,
    ForecastScenario,
    OperatingFactEvidence,
    OperatingForecastAssumption,
    OperatingForecastEvaluation,
    OperatingForecastProjection,
    OperatingForecastVersion,
    OperatingMetricRole,
    ValuationSensitivityPoint,
)
from core.integration.research_integrity_registry import (
    is_research_promotion_approved,
)

from .operating_forecast_models import (
    OperatingForecastAssumptionModel,
    OperatingForecastEvaluationModel,
    OperatingForecastFactReferenceModel,
    OperatingForecastProjectionModel,
    OperatingForecastSensitivityModel,
    OperatingForecastVersionModel,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _payload_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperatingForecastEvidenceError(f"operating fact payload.{key} is missing")
    return value


def _payload_decimal(payload: dict[str, Any], key: str) -> Decimal:
    value = payload.get(key)
    if isinstance(value, bool) or value is None:
        raise OperatingForecastEvidenceError(f"operating fact payload.{key} is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OperatingForecastEvidenceError(f"operating fact payload.{key} is invalid") from exc
    if not result.is_finite():
        raise OperatingForecastEvidenceError(f"operating fact payload.{key} is invalid")
    return result


class DjangoOperatingFactEvidenceProvider:
    """Resolve exact, latest public operating fact versions at an as-of time."""

    def get_operating_facts(
        self,
        version_ids: tuple[int, ...],
        *,
        as_of_time: datetime,
    ) -> tuple[OperatingFactEvidence, ...]:
        """Fail closed on missing, stale, non-public or inferred observations."""

        _require_aware(as_of_time, "as_of_time")
        if not version_ids or len(set(version_ids)) != len(version_ids):
            raise OperatingForecastEvidenceError(
                "operating fact version ids must be non-empty and unique"
            )
        if any(isinstance(version_id, bool) or version_id <= 0 for version_id in version_ids):
            raise OperatingForecastEvidenceError("operating fact version ids must be positive")

        facts = get_research_data_foundation_facade().get_operating_fact_versions(
            version_ids,
            as_of_time=as_of_time,
        )
        by_id = {fact.version_id: fact for fact in facts}
        if set(by_id) != set(version_ids):
            raise OperatingForecastEvidenceError(
                "requested operating facts are not the latest public PIT versions at as_of_time"
            )
        return tuple(self._to_evidence(by_id[version_id]) for version_id in version_ids)

    @staticmethod
    def _to_evidence(fact: PITFactVersion) -> OperatingFactEvidence:
        payload = dict(fact.payload)
        if fact.pit_quality is not PITQuality.VERIFIED:
            raise OperatingForecastEvidenceError("operating fact must have verified PIT quality")
        if payload.get("value_kind") != ForecastInputKind.OBSERVED_FACT.value:
            raise OperatingForecastEvidenceError(
                "forecast fact inputs must be observed facts, not assumptions or inference"
            )
        if fact.available_at is None:
            raise OperatingForecastEvidenceError("operating fact must have public available_at")
        return OperatingFactEvidence(
            version_id=fact.version_id,
            dataset=fact.dataset,
            business_key=fact.business_key,
            metric_code=_payload_text(payload, "metric_code"),
            subject_type=_payload_text(payload, "subject_type"),
            subject_code=_payload_text(payload, "subject_code"),
            effective_at=fact.effective_at,
            available_at=fact.available_at,
            source_record_id=fact.source_record_id,
            content_hash=fact.content_hash,
            value=_payload_decimal(payload, "value"),
            unit=_payload_text(payload, "unit"),
        )


class RuntimeResearchPromotionDecisionChecker:
    """Use the Research-owned runtime registry without importing its ORM."""

    def is_approved(self, decision_id: str) -> bool:
        """Return true only for an immutable approved PromotionDecision."""

        return is_research_promotion_approved(decision_id)


class DjangoOperatingForecastRepository:
    """Append and reconstruct immutable forecast and evaluation evidence."""

    @transaction.atomic
    def append_version(
        self,
        forecast: OperatingForecastVersion,
    ) -> OperatingForecastVersion:
        """Append idempotently while rejecting identity/content conflicts."""

        existing = (
            OperatingForecastVersionModel._default_manager.select_for_update()
            .filter(forecast_id=forecast.forecast_id)
            .first()
        )
        identity = (
            OperatingForecastVersionModel._default_manager.select_for_update()
            .filter(
                forecast_key=forecast.forecast_key,
                forecast_version=forecast.forecast_version,
            )
            .first()
        )
        for candidate in (existing, identity):
            if candidate is not None:
                if candidate.content_hash != forecast.content_hash:
                    raise OperatingForecastConflictError(
                        "forecast identity already has conflicting immutable content"
                    )
                stored = self.get_version(candidate.forecast_id)
                if stored is None:
                    raise RuntimeError("stored forecast could not be reconstructed")
                return stored

        model = OperatingForecastVersionModel._default_manager.create(
            forecast_id=forecast.forecast_id,
            forecast_key=forecast.forecast_key,
            forecast_version=forecast.forecast_version,
            subject_code=forecast.subject_code,
            industry_code=forecast.industry_code,
            as_of_time=forecast.as_of_time,
            target_period_end=forecast.target_period_end,
            horizon_quarters=forecast.horizon_quarters,
            methodology_ref=forecast.methodology_ref,
            created_by_ref=forecast.created_by_ref,
            valuation_consumable=forecast.valuation_consumable,
            promotion_decision_id=forecast.promotion_decision_id,
            content_hash=forecast.content_hash,
        )
        OperatingForecastFactReferenceModel._default_manager.bulk_create(
            [
                OperatingForecastFactReferenceModel(
                    forecast=model,
                    pit_fact_version_id=fact.version_id,
                    dataset=fact.dataset,
                    business_key=fact.business_key,
                    metric_code=fact.metric_code,
                    subject_type=fact.subject_type,
                    subject_code=fact.subject_code,
                    effective_at=fact.effective_at,
                    available_at=fact.available_at,
                    source_record_id=fact.source_record_id,
                    pit_content_hash=fact.content_hash,
                    value=fact.value,
                    unit=fact.unit,
                )
                for fact in forecast.facts
            ]
        )
        OperatingForecastAssumptionModel._default_manager.bulk_create(
            [
                OperatingForecastAssumptionModel(
                    forecast=model,
                    scenario=assumption.scenario.value,
                    assumption_key=assumption.assumption_key,
                    value=assumption.value,
                    unit=assumption.unit,
                    input_kind=assumption.input_kind.value,
                    rationale=assumption.rationale,
                    observed_fact_version_id=assumption.observed_fact_version_id,
                    human_assumption_ref=assumption.human_assumption_ref,
                    model_version=assumption.model_version,
                    observed_metric_role=(
                        assumption.observed_metric_role.value
                        if assumption.observed_metric_role is not None
                        else ""
                    ),
                )
                for assumption in forecast.assumptions
            ]
        )
        for projection in forecast.projections:
            projection_model = OperatingForecastProjectionModel._default_manager.create(
                forecast=model,
                scenario=projection.scenario.value,
                revenue=projection.revenue,
                net_profit=projection.net_profit,
                profit_margin_percent=projection.profit_margin_percent,
                currency_unit=projection.currency_unit,
            )
            OperatingForecastSensitivityModel._default_manager.bulk_create(
                [
                    OperatingForecastSensitivityModel(
                        projection=projection_model,
                        sensitivity_key=point.sensitivity_key,
                        input_value=point.input_value,
                        input_unit=point.input_unit,
                        output_value=point.output_value,
                        output_unit=point.output_unit,
                        method_version=point.method_version,
                    )
                    for point in projection.sensitivities
                ]
            )
        stored = self.get_version(model.forecast_id)
        if stored is None:
            raise RuntimeError("new forecast could not be reconstructed")
        return stored

    def get_version(self, forecast_id: str) -> OperatingForecastVersion | None:
        """Load one full version with facts, assumptions, projections and sensitivities."""

        sensitivity_queryset = OperatingForecastSensitivityModel._default_manager.order_by(
            "sensitivity_key"
        )
        projection_queryset = OperatingForecastProjectionModel._default_manager.prefetch_related(
            Prefetch("sensitivities", queryset=sensitivity_queryset)
        ).order_by("scenario")
        model = (
            OperatingForecastVersionModel._default_manager.prefetch_related(
                Prefetch(
                    "fact_references",
                    queryset=OperatingForecastFactReferenceModel._default_manager.order_by(
                        "pit_fact_version_id"
                    ),
                ),
                Prefetch(
                    "assumptions",
                    queryset=OperatingForecastAssumptionModel._default_manager.order_by(
                        "scenario", "assumption_key"
                    ),
                ),
                Prefetch("projections", queryset=projection_queryset),
            )
            .filter(forecast_id=forecast_id)
            .first()
        )
        if model is None:
            return None
        forecast = self._to_domain(model)
        if forecast.content_hash != model.content_hash:
            raise OperatingForecastConflictError("stored forecast content hash is invalid")
        return forecast

    @transaction.atomic
    def append_evaluations(
        self,
        evaluations: tuple[OperatingForecastEvaluation, ...],
    ) -> tuple[OperatingForecastEvaluation, ...]:
        """Append a complete three-scenario quarterly evaluation atomically."""

        if not evaluations:
            raise ValueError("evaluations cannot be empty")
        forecast_ids = {evaluation.forecast_id for evaluation in evaluations}
        periods = {evaluation.actual_period_end for evaluation in evaluations}
        scenarios = {evaluation.scenario for evaluation in evaluations}
        if (
            len(forecast_ids) != 1
            or len(periods) != 1
            or scenarios != set(ForecastScenario)
            or len(evaluations) != len(ForecastScenario)
        ):
            raise ValueError("quarterly evaluation must contain one row per required scenario")
        forecast_id = next(iter(forecast_ids))
        if (
            not OperatingForecastVersionModel._default_manager.select_for_update()
            .filter(forecast_id=forecast_id)
            .exists()
        ):
            raise OperatingForecastEvidenceError("forecast does not exist")

        for evaluation in evaluations:
            existing = (
                OperatingForecastEvaluationModel._default_manager.select_for_update()
                .filter(
                    forecast_id=evaluation.forecast_id,
                    actual_period_end=evaluation.actual_period_end,
                    scenario=evaluation.scenario.value,
                )
                .first()
            )
            if existing is not None:
                if existing.content_hash != evaluation.content_hash:
                    raise OperatingForecastConflictError(
                        "quarterly evaluation already has conflicting immutable content"
                    )
                continue
            OperatingForecastEvaluationModel._default_manager.create(
                forecast_id=evaluation.forecast_id,
                subject_code=evaluation.subject_code,
                scenario=evaluation.scenario.value,
                actual_period_end=evaluation.actual_period_end,
                recorded_at=evaluation.recorded_at,
                actual_fact_evidence=self._serialize_facts(evaluation.actual_facts),
                forecast_revenue=evaluation.forecast_revenue,
                forecast_net_profit=evaluation.forecast_net_profit,
                forecast_profit_margin_percent=evaluation.forecast_profit_margin_percent,
                actual_revenue=evaluation.actual_revenue,
                actual_net_profit=evaluation.actual_net_profit,
                actual_profit_margin_percent=evaluation.actual_profit_margin_percent,
                currency_unit=evaluation.currency_unit,
                revenue_error=evaluation.revenue_error,
                revenue_absolute_error=evaluation.revenue_absolute_error,
                revenue_absolute_percentage_error=(evaluation.revenue_absolute_percentage_error),
                net_profit_error=evaluation.net_profit_error,
                net_profit_absolute_error=evaluation.net_profit_absolute_error,
                net_profit_absolute_percentage_error=(
                    evaluation.net_profit_absolute_percentage_error
                ),
                profit_margin_error=evaluation.profit_margin_error,
                profit_margin_absolute_error=evaluation.profit_margin_absolute_error,
                content_hash=evaluation.content_hash,
            )
        return evaluations

    @staticmethod
    def _serialize_facts(
        facts: tuple[OperatingFactEvidence, ...],
    ) -> list[dict[str, str | int]]:
        return [
            {
                "version_id": fact.version_id,
                "dataset": fact.dataset,
                "business_key": fact.business_key,
                "metric_code": fact.metric_code,
                "subject_type": fact.subject_type,
                "subject_code": fact.subject_code,
                "effective_at": fact.effective_at.isoformat(),
                "available_at": fact.available_at.isoformat(),
                "source_record_id": fact.source_record_id,
                "content_hash": fact.content_hash,
                "value": str(fact.value),
                "unit": fact.unit,
            }
            for fact in sorted(facts, key=lambda item: item.version_id)
        ]

    @staticmethod
    def _to_domain(model: OperatingForecastVersionModel) -> OperatingForecastVersion:
        facts = tuple(
            OperatingFactEvidence(
                version_id=row.pit_fact_version_id,
                dataset=row.dataset,
                business_key=row.business_key,
                metric_code=row.metric_code,
                subject_type=row.subject_type,
                subject_code=row.subject_code,
                effective_at=row.effective_at,
                available_at=row.available_at,
                source_record_id=row.source_record_id,
                content_hash=row.pit_content_hash,
                value=row.value,
                unit=row.unit,
            )
            for row in model.fact_references.all()
        )
        assumptions = tuple(
            OperatingForecastAssumption(
                scenario=ForecastScenario(row.scenario),
                assumption_key=row.assumption_key,
                value=row.value,
                unit=row.unit,
                input_kind=ForecastInputKind(row.input_kind),
                rationale=row.rationale,
                observed_fact_version_id=row.observed_fact_version_id,
                human_assumption_ref=row.human_assumption_ref,
                model_version=row.model_version,
                observed_metric_role=(
                    OperatingMetricRole(row.observed_metric_role)
                    if row.observed_metric_role
                    else None
                ),
            )
            for row in model.assumptions.all()
        )
        projections = tuple(
            OperatingForecastProjection(
                scenario=ForecastScenario(row.scenario),
                revenue=row.revenue,
                net_profit=row.net_profit,
                currency_unit=row.currency_unit,
                sensitivities=tuple(
                    ValuationSensitivityPoint(
                        sensitivity_key=point.sensitivity_key,
                        input_value=point.input_value,
                        input_unit=point.input_unit,
                        output_value=point.output_value,
                        output_unit=point.output_unit,
                        method_version=point.method_version,
                    )
                    for point in row.sensitivities.all()
                ),
            )
            for row in model.projections.all()
        )
        return OperatingForecastVersion(
            forecast_id=model.forecast_id,
            forecast_key=model.forecast_key,
            forecast_version=model.forecast_version,
            subject_code=model.subject_code,
            industry_code=model.industry_code,
            as_of_time=model.as_of_time,
            target_period_end=model.target_period_end,
            horizon_quarters=model.horizon_quarters,
            methodology_ref=model.methodology_ref,
            created_by_ref=model.created_by_ref,
            facts=facts,
            assumptions=assumptions,
            projections=projections,
            valuation_consumable=model.valuation_consumable,
            promotion_decision_id=model.promotion_decision_id,
        )


__all__ = [
    "DjangoOperatingFactEvidenceProvider",
    "DjangoOperatingForecastRepository",
    "RuntimeResearchPromotionDecisionChecker",
]
