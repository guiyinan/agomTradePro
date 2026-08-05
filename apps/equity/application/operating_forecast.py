"""Application orchestration for the R1 operating-forecast ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol, cast

from apps.equity.domain.operating_forecast import (
    LegacyOperatingForecastVersion,
    OperatingFactEvidence,
    OperatingForecastAssumption,
    OperatingForecastEvaluation,
    OperatingForecastProjection,
    OperatingForecastSourceKind,
    OperatingForecastSourceLineageStatus,
    OperatingForecastVersion,
    build_quarterly_evaluations,
)
from apps.sector.domain.industry_operating_template import (
    ImmutableTemplateRunEvidence,
    TemplateRunStatus,
)


class OperatingFactEvidenceProvider(Protocol):
    """Resolve exact Data Center operating PIT fact versions."""

    def get_operating_facts(
        self,
        version_ids: tuple[int, ...],
        *,
        as_of_time: datetime,
    ) -> tuple[OperatingFactEvidence, ...]: ...


class ResearchPromotionDecisionChecker(Protocol):
    """Check immutable Research PromotionDecision evidence."""

    def is_approved(self, decision_id: str) -> bool: ...


class IndustryTemplateRunEvidenceProvider(Protocol):
    """Read one exact immutable Sector template-run evidence version."""

    def get_run_evidence(
        self,
        *,
        run_key: str,
        run_version: int,
    ) -> ImmutableTemplateRunEvidence | None:
        """Return one exact run evidence version without mutating Sector history."""


class OperatingForecastRepository(Protocol):
    """Append-only persistence contract owned by Equity."""

    def append_version(
        self,
        forecast: OperatingForecastVersion,
    ) -> OperatingForecastVersion: ...

    def get_version(
        self,
        forecast_id: str,
    ) -> OperatingForecastVersion | LegacyOperatingForecastVersion | None: ...

    def append_evaluations(
        self,
        evaluations: tuple[OperatingForecastEvaluation, ...],
    ) -> tuple[OperatingForecastEvaluation, ...]: ...


class OperatingForecastNotFoundError(LookupError):
    """Raised when a quarterly actual references an unknown forecast."""


class OperatingForecastPromotionError(PermissionError):
    """Raised when Valuation consumption lacks approved Research evidence."""


class OperatingForecastEvidenceError(ValueError):
    """Raised when requested PIT versions are missing or substituted."""


class OperatingForecastConflictError(ValueError):
    """Raised when an immutable forecast identity has conflicting content."""


class OperatingForecastTemplateEvidenceError(ValueError):
    """Raised when a forecast is not the exact output of an available Sector run."""


@dataclass(frozen=True)
class CreateOperatingForecastCommand:
    """Internal command for one immutable forecast version."""

    forecast_id: str
    forecast_key: str
    forecast_version: int
    subject_code: str
    industry_code: str
    as_of_time: datetime
    target_period_end: date
    horizon_quarters: int
    methodology_ref: str
    created_by_ref: str
    template_code: str
    template_version: int
    template_content_hash: str
    template_run_key: str
    template_run_version: int
    template_run_content_hash: str
    fact_version_ids: tuple[int, ...]
    assumptions: tuple[OperatingForecastAssumption, ...]
    projections: tuple[OperatingForecastProjection, ...]
    valuation_consumable: bool = False
    promotion_decision_id: str = ""


@dataclass(frozen=True)
class RecordQuarterlyActualCommand:
    """Internal command for actual-versus-forecast reconciliation."""

    forecast_id: str
    actual_period_end: date
    recorded_at: datetime
    actual_fact_version_ids: tuple[int, ...]
    actual_revenue: Decimal
    actual_net_profit: Decimal
    currency_unit: str


class CreateOperatingForecastVersionUseCase:
    """Resolve canonical facts and append one research-only schema-v2 version."""

    def __init__(
        self,
        repository: OperatingForecastRepository,
        fact_provider: OperatingFactEvidenceProvider,
        promotion_checker: ResearchPromotionDecisionChecker,
        template_run_evidence_provider: IndustryTemplateRunEvidenceProvider,
    ) -> None:
        self._repository = repository
        self._fact_provider = fact_provider
        self._promotion_checker = promotion_checker
        self._template_run_evidence_provider = template_run_evidence_provider

    def execute(self, command: CreateOperatingForecastCommand) -> OperatingForecastVersion:
        """Create one template-bound forecast; promotion remains fail closed."""

        if command.valuation_consumable or command.promotion_decision_id.strip():
            raise OperatingForecastPromotionError(
                "schema-v2 forecast promotion requires exact artifact binding, which is "
                "not implemented"
            )
        facts = self._fact_provider.get_operating_facts(
            command.fact_version_ids,
            as_of_time=command.as_of_time,
        )
        requested_ids = set(command.fact_version_ids)
        resolved_ids = {fact.version_id for fact in facts}
        if len(requested_ids) != len(command.fact_version_ids) or resolved_ids != requested_ids:
            raise OperatingForecastEvidenceError(
                "operating PIT evidence must resolve exactly without duplicates or substitution"
            )
        run_evidence = self._template_run_evidence_provider.get_run_evidence(
            run_key=command.template_run_key,
            run_version=command.template_run_version,
        )
        _validate_template_run_evidence(
            command=command,
            facts=facts,
            evidence=run_evidence,
        )
        forecast = OperatingForecastVersion(
            forecast_id=command.forecast_id,
            forecast_key=command.forecast_key,
            forecast_version=command.forecast_version,
            subject_code=command.subject_code,
            industry_code=command.industry_code,
            as_of_time=command.as_of_time,
            target_period_end=command.target_period_end,
            horizon_quarters=command.horizon_quarters,
            methodology_ref=command.methodology_ref,
            created_by_ref=command.created_by_ref,
            source_kind=OperatingForecastSourceKind.INDUSTRY_TEMPLATE,
            evidence_schema_version=2,
            source_lineage_status=OperatingForecastSourceLineageStatus.TEMPLATE_BOUND,
            template_code=command.template_code,
            template_version=command.template_version,
            template_content_hash=command.template_content_hash,
            template_run_key=command.template_run_key,
            template_run_version=command.template_run_version,
            template_run_content_hash=command.template_run_content_hash,
            facts=facts,
            assumptions=command.assumptions,
            projections=command.projections,
            valuation_consumable=command.valuation_consumable,
            promotion_decision_id=command.promotion_decision_id,
        )
        return self._repository.append_version(forecast)


def _decimal_text(value: Decimal) -> str:
    """Return the canonical decimal encoding used by Sector run evidence."""

    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _expected_draft_payload(command: CreateOperatingForecastCommand) -> dict[str, object]:
    """Project one Equity command back to the exact Sector draft payload shape."""

    return {
        "as_of_time": command.as_of_time.astimezone(UTC).isoformat(),
        "assumptions": [
            {
                "assumption_key": item.assumption_key,
                "input_kind": item.input_kind.value,
                "lineage_ref": item.lineage_ref,
                "rationale": item.rationale,
                "scenario": item.scenario.value,
                "unit": item.unit,
                "value": _decimal_text(item.value),
            }
            for item in sorted(
                command.assumptions,
                key=lambda item: (item.scenario.value, item.assumption_key),
            )
        ],
        "created_by_ref": command.created_by_ref,
        "fact_version_ids": list(command.fact_version_ids),
        "forecast_id": command.forecast_id,
        "forecast_key": command.forecast_key,
        "forecast_version": command.forecast_version,
        "horizon_quarters": command.horizon_quarters,
        "industry_code": command.industry_code,
        "methodology_ref": command.methodology_ref,
        "projections": [
            {
                "cash_flow": _decimal_text(item.cash_flow),
                "currency_unit": item.currency_unit,
                "net_profit": _decimal_text(item.net_profit),
                "revenue": _decimal_text(item.revenue),
                "scenario": item.scenario.value,
                "stage_values": [
                    {
                        "node_key": stage.node_key,
                        "stage": stage.stage.value,
                        "unit": stage.unit,
                        "value": _decimal_text(stage.value),
                    }
                    for stage in sorted(
                        item.stage_values,
                        key=lambda stage: stage.stage.value,
                    )
                ],
            }
            for item in sorted(command.projections, key=lambda item: item.scenario.value)
        ],
        "research_only": True,
        "subject_code": command.subject_code,
        "target_period_end": command.target_period_end.isoformat(),
        "template_code": command.template_code,
        "template_content_hash": command.template_content_hash,
        "template_version": command.template_version,
    }


def _validate_template_run_evidence(
    *,
    command: CreateOperatingForecastCommand,
    facts: tuple[OperatingFactEvidence, ...],
    evidence: ImmutableTemplateRunEvidence | None,
) -> None:
    """Require exact available Sector evidence and bind every PIT fact and draft field."""

    if evidence is None:
        raise OperatingForecastTemplateEvidenceError("industry template run evidence is missing")
    if evidence.status is not TemplateRunStatus.AVAILABLE:
        raise OperatingForecastTemplateEvidenceError("industry template run is not available")
    if (
        evidence.run_key != command.template_run_key
        or evidence.run_version != command.template_run_version
        or evidence.template_code != command.template_code
        or evidence.template_version != command.template_version
        or evidence.template_content_hash.lower() != command.template_content_hash.lower()
        or evidence.content_hash.lower() != command.template_run_content_hash.lower()
        or evidence.as_of_time != command.as_of_time
    ):
        raise OperatingForecastTemplateEvidenceError("industry template run identity mismatch")
    parsed = json.loads(evidence.payload_json)
    if not isinstance(parsed, dict):
        raise OperatingForecastTemplateEvidenceError("industry template run payload is invalid")
    payload = cast(dict[str, object], parsed)
    expected_outer = {
        "run_key": command.template_run_key,
        "run_version": command.template_run_version,
        "template_code": command.template_code,
        "template_version": command.template_version,
        "template_content_hash": command.template_content_hash,
        "subject_code": command.subject_code,
        "industry_code": command.industry_code,
        "as_of_time": command.as_of_time.astimezone(UTC).isoformat(),
        "status": TemplateRunStatus.AVAILABLE.value,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    if any(payload.get(key) != value for key, value in expected_outer.items()):
        raise OperatingForecastTemplateEvidenceError(
            "industry template run payload identity mismatch"
        )
    if payload.get("forecast_draft") != _expected_draft_payload(command):
        raise OperatingForecastTemplateEvidenceError("industry template forecast draft mismatch")
    raw_facts = payload.get("facts")
    if not isinstance(raw_facts, list):
        raise OperatingForecastTemplateEvidenceError("industry template PIT facts are missing")
    raw_by_id: dict[int, dict[str, object]] = {}
    for raw in raw_facts:
        if not isinstance(raw, dict) or not isinstance(raw.get("version_id"), int):
            raise OperatingForecastTemplateEvidenceError("industry template PIT fact is invalid")
        typed_raw = cast(dict[str, object], raw)
        version_id = cast(int, typed_raw["version_id"])
        if version_id in raw_by_id:
            raise OperatingForecastTemplateEvidenceError(
                "industry template PIT facts are duplicated"
            )
        raw_by_id[version_id] = typed_raw
    if set(raw_by_id) != {fact.version_id for fact in facts}:
        raise OperatingForecastTemplateEvidenceError("industry template PIT fact set mismatch")
    for fact in facts:
        raw = raw_by_id[fact.version_id]
        expected = {
            "available_at": fact.available_at.astimezone(UTC).isoformat(),
            "business_key": fact.business_key,
            "content_hash": fact.content_hash.lower(),
            "dataset": fact.dataset,
            "effective_at": fact.effective_at.astimezone(UTC).isoformat(),
            "is_verified": True,
            "metric_code": fact.metric_code,
            "source_record_id": fact.source_record_id,
            "subject_code": fact.subject_code,
            "unit": fact.unit,
            "value": _decimal_text(fact.value),
            "version_id": fact.version_id,
        }
        if fact.subject_type != "company" or any(
            raw.get(key) != value for key, value in expected.items()
        ):
            raise OperatingForecastTemplateEvidenceError(
                "industry template PIT fact identity mismatch"
            )


class RecordQuarterlyOperatingActualUseCase:
    """Append all three scenario error observations for one quarterly actual."""

    def __init__(
        self,
        repository: OperatingForecastRepository,
        fact_provider: OperatingFactEvidenceProvider,
    ) -> None:
        self._repository = repository
        self._fact_provider = fact_provider

    def execute(
        self,
        command: RecordQuarterlyActualCommand,
    ) -> tuple[OperatingForecastEvaluation, ...]:
        """Resolve actual evidence and append deterministic error metrics."""

        forecast = self._repository.get_version(command.forecast_id)
        if forecast is None:
            raise OperatingForecastNotFoundError(command.forecast_id)
        projection_units = {projection.currency_unit for projection in forecast.projections}
        if projection_units != {command.currency_unit}:
            raise OperatingForecastEvidenceError(
                "actual and forecast currency units must match exactly"
            )
        facts = self._fact_provider.get_operating_facts(
            command.actual_fact_version_ids,
            as_of_time=command.recorded_at,
        )
        requested_ids = set(command.actual_fact_version_ids)
        if (
            len(requested_ids) != len(command.actual_fact_version_ids)
            or {fact.version_id for fact in facts} != requested_ids
        ):
            raise OperatingForecastEvidenceError(
                "actual PIT evidence must resolve exactly without duplicates or substitution"
            )
        evaluations = build_quarterly_evaluations(
            forecast,
            actual_period_end=command.actual_period_end,
            recorded_at=command.recorded_at,
            actual_facts=facts,
            actual_revenue=command.actual_revenue,
            actual_net_profit=command.actual_net_profit,
            currency_unit=command.currency_unit,
        )
        return self._repository.append_evaluations(evaluations)


__all__ = [
    "CreateOperatingForecastCommand",
    "CreateOperatingForecastVersionUseCase",
    "IndustryTemplateRunEvidenceProvider",
    "OperatingFactEvidenceProvider",
    "OperatingForecastConflictError",
    "OperatingForecastEvidenceError",
    "OperatingForecastNotFoundError",
    "OperatingForecastPromotionError",
    "OperatingForecastRepository",
    "OperatingForecastTemplateEvidenceError",
    "RecordQuarterlyActualCommand",
    "RecordQuarterlyOperatingActualUseCase",
    "ResearchPromotionDecisionChecker",
]
