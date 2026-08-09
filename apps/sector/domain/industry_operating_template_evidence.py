"""Immutable run evidence and evaluator for industry operating templates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from apps.sector.domain.industry_operating_template import (
    DriverInputKind,
    ExpressionOperator,
    FinancialStage,
    ForecastAssumptionDraft,
    ForecastProjectionDraft,
    ForecastScenario,
    IndustryOperatingTemplate,
    IndustryTemplateRunResult,
    OperatingForecastDraft,
    PITDriverFact,
    StageValue,
    TemplateRunStatus,
    _canonical_hash,
    _require_aware,
    _require_sha256,
    _require_token,
)


@dataclass(frozen=True)
class ImmutableTemplateRunEvidence:
    """Append-only storage payload for one exact template run version."""

    run_key: str
    run_version: int
    template_code: str
    template_version: int
    template_content_hash: str
    as_of_time: datetime
    status: TemplateRunStatus
    content_hash: str
    payload_json: str
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool

    def __post_init__(self) -> None:
        _require_token(self.run_key, "ImmutableTemplateRunEvidence.run_key", maximum=128)
        if isinstance(self.run_version, bool) or self.run_version <= 0:
            raise ValueError("ImmutableTemplateRunEvidence.run_version must be positive")
        _require_token(
            self.template_code,
            "ImmutableTemplateRunEvidence.template_code",
            maximum=80,
        )
        if isinstance(self.template_version, bool) or self.template_version <= 0:
            raise ValueError("ImmutableTemplateRunEvidence.template_version must be positive")
        if self.template_content_hash:
            _require_sha256(
                self.template_content_hash,
                "ImmutableTemplateRunEvidence.template_content_hash",
            )
        _require_aware(self.as_of_time, "ImmutableTemplateRunEvidence.as_of_time")
        if not isinstance(self.status, TemplateRunStatus):
            raise ValueError("ImmutableTemplateRunEvidence.status is invalid")
        _require_sha256(self.content_hash, "ImmutableTemplateRunEvidence.content_hash")
        if (
            not self.research_only
            or not self.must_not_use_for_decision
            or not self.must_not_execute
        ):
            raise ValueError("template run evidence must remain research-only")
        try:
            parsed = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("template run payload_json is invalid") from exc
        if not isinstance(parsed, dict):
            raise ValueError("template run payload_json must encode an object")
        payload = cast(dict[str, object], parsed)
        if _canonical_hash(payload) != self.content_hash:
            raise ValueError("template run content_hash mismatch")
        if payload.get("status") != self.status.value:
            raise ValueError("template run status conflicts with payload")


def build_template_run_evidence(
    result: IndustryTemplateRunResult,
) -> ImmutableTemplateRunEvidence:
    """Build immutable persistence evidence from one validated run result."""

    payload = result.to_payload()
    return ImmutableTemplateRunEvidence(
        run_key=result.run_key,
        run_version=result.run_version,
        template_code=result.template_code,
        template_version=result.template_version,
        template_content_hash=result.template_content_hash,
        as_of_time=result.as_of_time,
        status=result.status,
        content_hash=_canonical_hash(payload),
        payload_json=json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        research_only=True,
        must_not_use_for_decision=True,
        must_not_execute=True,
    )


def _evidence_object(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return cast(dict[str, object], value)


def _evidence_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return cast(list[object], value)


def _evidence_text(value: object, field_name: str, *, allow_blank: bool = False) -> str:
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise ValueError(f"{field_name} must be text")
    return value


def _evidence_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _evidence_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _evidence_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a finite decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal")
    return parsed


def _evidence_datetime(value: object, field_name: str) -> datetime:
    text = _evidence_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO datetime") from exc
    _require_aware(parsed, field_name)
    return parsed


def _evidence_date(value: object, field_name: str) -> date:
    text = _evidence_text(value, field_name)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _restore_driver_fact(raw: object) -> PITDriverFact:
    payload = _evidence_object(raw, "facts[]")
    return PITDriverFact(
        version_id=_evidence_int(payload.get("version_id"), "facts[].version_id"),
        dataset=_evidence_text(payload.get("dataset"), "facts[].dataset"),
        business_key=_evidence_text(payload.get("business_key"), "facts[].business_key"),
        metric_code=_evidence_text(payload.get("metric_code"), "facts[].metric_code"),
        metric_definition_version=_evidence_int(
            payload.get("metric_definition_version"),
            "facts[].metric_definition_version",
        ),
        subject_code=_evidence_text(payload.get("subject_code"), "facts[].subject_code"),
        effective_at=_evidence_datetime(
            payload.get("effective_at"),
            "facts[].effective_at",
        ),
        available_at=_evidence_datetime(
            payload.get("available_at"),
            "facts[].available_at",
        ),
        value=_evidence_decimal(payload.get("value"), "facts[].value"),
        unit=_evidence_text(payload.get("unit"), "facts[].unit"),
        frequency=_evidence_text(payload.get("frequency"), "facts[].frequency"),
        source=_evidence_text(payload.get("source"), "facts[].source"),
        source_record_id=_evidence_text(
            payload.get("source_record_id"),
            "facts[].source_record_id",
        ),
        content_hash=_evidence_text(payload.get("content_hash"), "facts[].content_hash"),
        is_verified=_evidence_bool(payload.get("is_verified"), "facts[].is_verified"),
    )


def _restore_assumption(raw: object) -> ForecastAssumptionDraft:
    payload = _evidence_object(raw, "forecast_draft.assumptions[]")
    input_kind = DriverInputKind(
        _evidence_text(payload.get("input_kind"), "assumptions[].input_kind")
    )
    lineage_ref = _evidence_text(payload.get("lineage_ref"), "assumptions[].lineage_ref")
    observed_fact_version_id: int | None = None
    human_assumption_ref = ""
    model_version = ""
    if input_kind is DriverInputKind.OBSERVED_FACT:
        prefix = "data_center_pit_fact:"
        if not lineage_ref.startswith(prefix):
            raise ValueError("observed assumption lineage_ref is invalid")
        try:
            observed_fact_version_id = int(lineage_ref.removeprefix(prefix))
        except ValueError as exc:
            raise ValueError("observed assumption lineage_ref is invalid") from exc
    elif input_kind is DriverInputKind.HUMAN_ASSUMPTION:
        human_assumption_ref = lineage_ref
    else:
        model_version = lineage_ref
    return ForecastAssumptionDraft(
        scenario=ForecastScenario(
            _evidence_text(payload.get("scenario"), "assumptions[].scenario")
        ),
        assumption_key=_evidence_text(
            payload.get("assumption_key"),
            "assumptions[].assumption_key",
        ),
        value=_evidence_decimal(payload.get("value"), "assumptions[].value"),
        unit=_evidence_text(payload.get("unit"), "assumptions[].unit"),
        input_kind=input_kind,
        rationale=_evidence_text(payload.get("rationale"), "assumptions[].rationale"),
        observed_fact_version_id=observed_fact_version_id,
        human_assumption_ref=human_assumption_ref,
        model_version=model_version,
    )


def _restore_projection(raw: object) -> ForecastProjectionDraft:
    payload = _evidence_object(raw, "forecast_draft.projections[]")
    stage_values = tuple(
        StageValue(
            stage=FinancialStage(
                _evidence_text(
                    stage_payload.get("stage"),
                    "projections[].stage_values[].stage",
                )
            ),
            node_key=_evidence_text(
                stage_payload.get("node_key"),
                "projections[].stage_values[].node_key",
            ),
            value=_evidence_decimal(
                stage_payload.get("value"),
                "projections[].stage_values[].value",
            ),
            unit=_evidence_text(
                stage_payload.get("unit"),
                "projections[].stage_values[].unit",
            ),
        )
        for stage_payload in (
            _evidence_object(item, "projections[].stage_values[]")
            for item in _evidence_list(
                payload.get("stage_values"),
                "projections[].stage_values",
            )
        )
    )
    return ForecastProjectionDraft(
        scenario=ForecastScenario(
            _evidence_text(payload.get("scenario"), "projections[].scenario")
        ),
        revenue=_evidence_decimal(payload.get("revenue"), "projections[].revenue"),
        net_profit=_evidence_decimal(
            payload.get("net_profit"),
            "projections[].net_profit",
        ),
        cash_flow=_evidence_decimal(payload.get("cash_flow"), "projections[].cash_flow"),
        currency_unit=_evidence_text(
            payload.get("currency_unit"),
            "projections[].currency_unit",
        ),
        stage_values=stage_values,
    )


def _restore_forecast_draft(raw: object) -> OperatingForecastDraft:
    payload = _evidence_object(raw, "forecast_draft")
    return OperatingForecastDraft(
        forecast_id=_evidence_text(payload.get("forecast_id"), "forecast_draft.forecast_id"),
        forecast_key=_evidence_text(
            payload.get("forecast_key"),
            "forecast_draft.forecast_key",
        ),
        forecast_version=_evidence_int(
            payload.get("forecast_version"),
            "forecast_draft.forecast_version",
        ),
        subject_code=_evidence_text(
            payload.get("subject_code"),
            "forecast_draft.subject_code",
        ),
        industry_code=_evidence_text(
            payload.get("industry_code"),
            "forecast_draft.industry_code",
        ),
        as_of_time=_evidence_datetime(
            payload.get("as_of_time"),
            "forecast_draft.as_of_time",
        ),
        target_period_end=_evidence_date(
            payload.get("target_period_end"),
            "forecast_draft.target_period_end",
        ),
        horizon_quarters=_evidence_int(
            payload.get("horizon_quarters"),
            "forecast_draft.horizon_quarters",
        ),
        methodology_ref=_evidence_text(
            payload.get("methodology_ref"),
            "forecast_draft.methodology_ref",
        ),
        created_by_ref=_evidence_text(
            payload.get("created_by_ref"),
            "forecast_draft.created_by_ref",
        ),
        template_code=_evidence_text(
            payload.get("template_code"),
            "forecast_draft.template_code",
        ),
        template_version=_evidence_int(
            payload.get("template_version"),
            "forecast_draft.template_version",
        ),
        template_content_hash=_evidence_text(
            payload.get("template_content_hash"),
            "forecast_draft.template_content_hash",
        ),
        fact_version_ids=tuple(
            _evidence_int(item, "forecast_draft.fact_version_ids[]")
            for item in _evidence_list(
                payload.get("fact_version_ids"),
                "forecast_draft.fact_version_ids",
            )
        ),
        assumptions=tuple(
            _restore_assumption(item)
            for item in _evidence_list(
                payload.get("assumptions"),
                "forecast_draft.assumptions",
            )
        ),
        projections=tuple(
            _restore_projection(item)
            for item in _evidence_list(
                payload.get("projections"),
                "forecast_draft.projections",
            )
        ),
        research_only=_evidence_bool(
            payload.get("research_only"),
            "forecast_draft.research_only",
        ),
    )


def restore_template_run_result(
    evidence: ImmutableTemplateRunEvidence,
) -> IndustryTemplateRunResult:
    """Restore typed run output only from hash-verified immutable evidence."""

    parsed = json.loads(evidence.payload_json)
    payload = _evidence_object(parsed, "template_run")
    forecast_raw = payload.get("forecast_draft")
    result = IndustryTemplateRunResult(
        run_key=_evidence_text(payload.get("run_key"), "template_run.run_key"),
        run_version=_evidence_int(payload.get("run_version"), "template_run.run_version"),
        template_code=_evidence_text(
            payload.get("template_code"),
            "template_run.template_code",
        ),
        template_version=_evidence_int(
            payload.get("template_version"),
            "template_run.template_version",
        ),
        template_content_hash=_evidence_text(
            payload.get("template_content_hash"),
            "template_run.template_content_hash",
            allow_blank=True,
        ),
        subject_code=_evidence_text(payload.get("subject_code"), "template_run.subject_code"),
        industry_code=_evidence_text(
            payload.get("industry_code"),
            "template_run.industry_code",
        ),
        as_of_time=_evidence_datetime(
            payload.get("as_of_time"),
            "template_run.as_of_time",
        ),
        status=TemplateRunStatus(_evidence_text(payload.get("status"), "template_run.status")),
        facts=tuple(
            _restore_driver_fact(item)
            for item in _evidence_list(payload.get("facts"), "template_run.facts")
        ),
        forecast_draft=(None if forecast_raw is None else _restore_forecast_draft(forecast_raw)),
        blocked_reasons=tuple(
            _evidence_text(item, "template_run.blocked_reasons[]")
            for item in _evidence_list(
                payload.get("blocked_reasons"),
                "template_run.blocked_reasons",
            )
        ),
        research_only=_evidence_bool(
            payload.get("research_only"),
            "template_run.research_only",
        ),
        must_not_use_for_decision=_evidence_bool(
            payload.get("must_not_use_for_decision"),
            "template_run.must_not_use_for_decision",
        ),
        must_not_execute=_evidence_bool(
            payload.get("must_not_execute"),
            "template_run.must_not_execute",
        ),
    )
    rebuilt = build_template_run_evidence(result)
    if rebuilt != evidence:
        raise ValueError("template run evidence metadata conflicts with its sealed payload")
    return result


class TemplateEvaluationError(ValueError):
    """Stable fail-closed calculation error from the finite evaluator."""


def evaluate_template(
    template: IndustryOperatingTemplate,
    driver_values: dict[str, Decimal],
) -> tuple[StageValue, ...]:
    """Evaluate the finite AST without eval, exec or arbitrary callables."""

    expected = {driver.driver_key for driver in template.drivers}
    if set(driver_values) != expected:
        missing = sorted(expected - set(driver_values))
        extra = sorted(set(driver_values) - expected)
        raise TemplateEvaluationError(
            f"driver_set_mismatch:missing={','.join(missing)}:extra={','.join(extra)}"
        )
    if any(
        not isinstance(value, Decimal) or not value.is_finite() for value in driver_values.values()
    ):
        raise TemplateEvaluationError("driver_value_non_finite")
    values = dict(driver_values)
    nodes = {node.node_key: node for node in template.nodes}
    for node_key in template.topological_node_keys:
        node = nodes[node_key]
        operands = [values[reference.key] for reference in node.operands]
        try:
            if node.operator is ExpressionOperator.IDENTITY:
                value = operands[0]
            elif node.operator is ExpressionOperator.ADD:
                value = sum(operands, Decimal("0"))
            elif node.operator is ExpressionOperator.SUBTRACT:
                value = operands[0] - operands[1]
            elif node.operator is ExpressionOperator.MULTIPLY:
                value = operands[0] * operands[1]
            else:
                if operands[1] == 0:
                    raise TemplateEvaluationError(f"division_by_zero:{node.node_key}")
                value = operands[0] / operands[1]
        except (InvalidOperation, OverflowError) as exc:
            raise TemplateEvaluationError(f"numeric_failure:{node.node_key}") from exc
        if not value.is_finite():
            raise TemplateEvaluationError(f"non_finite_result:{node.node_key}")
        values[node.node_key] = value
    nodes_by_key = {node.node_key: node for node in template.nodes}
    return tuple(
        StageValue(
            stage=stage,
            node_key=node_key,
            value=values[node_key],
            unit=nodes_by_key[node_key].output_unit,
        )
        for stage, node_key in sorted(
            template.stage_output_keys.items(),
            key=lambda item: item[0].value,
        )
    )


__all__ = [
    "ImmutableTemplateRunEvidence",
    "TemplateEvaluationError",
    "build_template_run_evidence",
    "evaluate_template",
    "restore_template_run_result",
]
