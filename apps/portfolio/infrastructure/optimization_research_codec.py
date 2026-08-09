"""Lossless ORM codecs for governed optimization result evidence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from apps.portfolio.domain._optimization_canonical import decimal_text, utc_text
from apps.portfolio.domain.constrained_optimization_contracts import (
    CandidateKind,
    SolverConvergenceStatus,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleEventType,
    OptimizationLifecycleOwnerAttestation,
    OptimizationResearchLifecycleEvent,
)
from apps.portfolio.domain.optimization_research_result import (
    CandidateBlockerEvidence,
    CandidateMetricEvidence,
    GovernedCandidateEvidence,
    GovernedOptimizationResearchResult,
    GovernedOptimizationResultStatus,
)

from .optimization_research_models import (
    GovernedOptimizationInputReceiptModel,
    GovernedOptimizationResearchResultModel,
    OptimizationResearchLifecycleEventModel,
)


def result_model(
    result: GovernedOptimizationResearchResult,
    input_receipt: GovernedOptimizationInputReceiptModel,
) -> GovernedOptimizationResearchResultModel:
    """Build an unsaved immutable result row."""

    if (
        result.input_receipt_id != input_receipt.receipt_id
        or result.input_receipt_hash != input_receipt.content_hash
        or result.input_receipt_schema_version != input_receipt.receipt_version
        or result.input_set_id != input_receipt.input_set_id
        or result.input_set_hash != input_receipt.input_set_hash
    ):
        raise ValueError("optimization result receipt relation differs from canonical anchors")
    candidates = [_candidate_payload(item) for item in result.candidates]
    blockers = [list(item) for item in result.problem_blockers]
    return GovernedOptimizationResearchResultModel(
        input_receipt=input_receipt,
        result_id=result.result_id,
        result_version=result.result_version,
        run_key=result.run_key,
        run_version=result.run_version,
        assembly_hash=result.assembly_hash,
        problem_id=result.problem_id,
        problem_hash=result.problem_hash,
        input_set_id=result.input_set_id,
        input_set_hash=result.input_set_hash,
        status=result.status.value,
        selected_candidate=(
            "" if result.selected_candidate is None else result.selected_candidate.value
        ),
        candidates=candidates,
        problem_blockers=blockers,
        evaluated_at=result.evaluated_at,
        valid_until=result.valid_until,
        content_hash=result.content_hash,
        canonical_payload=_result_payload(result),
        research_only=result.research_only,
        must_not_execute=result.must_not_execute,
        must_not_use_for_decision=result.must_not_use_for_decision,
    )


def result_to_domain(
    row: GovernedOptimizationResearchResultModel,
    *,
    allow_legacy: bool = False,
) -> GovernedOptimizationResearchResult:
    """Restore and integrity-check one result row and its canonical payload."""

    if row.input_receipt_id is None:
        if not allow_legacy:
            raise ValueError("legacy optimization result requires explicit research-only read")
        if row.result_version != "governed-optimization-result.v1":
            raise ValueError("new optimization result has a null input receipt relation")
        receipt_id: str | None = None
        receipt_hash: str | None = None
        receipt_schema_version: str | None = None
    else:
        if allow_legacy:
            raise ValueError("legacy optimization result cannot alias an input receipt")
        if row.result_version != "governed-optimization-result.v2":
            raise ValueError("legacy optimization result cannot alias an input receipt")
        receipt = row.input_receipt
        if receipt is None:
            raise ValueError("new optimization result has a null input receipt relation")
        if receipt.input_set_id != row.input_set_id or receipt.input_set_hash != row.input_set_hash:
            raise ValueError("optimization result receipt relation is substituted")
        receipt_id = receipt.receipt_id
        receipt_hash = receipt.content_hash
        receipt_schema_version = receipt.receipt_version
    raw_candidates = _list(row.candidates, "result candidates")
    candidates = tuple(_candidate_from_payload(_dict(item, "candidate")) for item in raw_candidates)
    raw_blockers = _list(row.problem_blockers, "problem blockers")
    blockers = tuple(
        (
            str(_pair(item, "problem blocker")[0]),
            str(_pair(item, "problem blocker")[1]),
        )
        for item in raw_blockers
    )
    result = GovernedOptimizationResearchResult(
        result_id=row.result_id,
        result_version=row.result_version,
        run_key=row.run_key,
        run_version=row.run_version,
        assembly_hash=row.assembly_hash,
        problem_id=row.problem_id,
        problem_hash=row.problem_hash,
        input_set_id=row.input_set_id,
        input_set_hash=row.input_set_hash,
        input_receipt_id=receipt_id,
        input_receipt_hash=receipt_hash,
        input_receipt_schema_version=receipt_schema_version,
        status=GovernedOptimizationResultStatus(row.status),
        candidates=candidates,
        selected_candidate=(
            None if not row.selected_candidate else CandidateKind(row.selected_candidate)
        ),
        problem_blockers=blockers,
        evaluated_at=row.evaluated_at,
        valid_until=row.valid_until,
        content_hash=row.content_hash,
        research_only=row.research_only,
        must_not_execute=row.must_not_execute,
        must_not_use_for_decision=row.must_not_use_for_decision,
    )
    if row.canonical_payload != _result_payload(result):
        raise ValueError("persisted optimization result canonical payload mismatch")
    return result


def lifecycle_model(
    event: OptimizationResearchLifecycleEvent,
    result: GovernedOptimizationResearchResultModel,
) -> OptimizationResearchLifecycleEventModel:
    """Build an unsaved immutable lifecycle row."""

    return OptimizationResearchLifecycleEventModel(
        event_id=event.event_id,
        result=result,
        result_hash=event.result_hash,
        event_type=event.event_type.value,
        sequence=event.sequence,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        reason_codes=list(event.reason_codes),
        previous_event_hash=event.previous_event_hash,
        promotion_attestation=(
            None
            if event.promotion_attestation is None
            else _promotion_payload(event.promotion_attestation)
        ),
        owner_attestation=(
            None
            if event.owner_attestation is None
            else _owner_attestation_payload(event.owner_attestation)
        ),
        content_hash=event.content_hash,
        canonical_payload=_lifecycle_payload(event),
        research_only=event.research_only,
        must_not_execute=event.must_not_execute,
        must_not_use_for_decision=event.must_not_use_for_decision,
    )


def lifecycle_to_domain(
    row: OptimizationResearchLifecycleEventModel,
) -> OptimizationResearchLifecycleEvent:
    """Restore and integrity-check one lifecycle row."""

    promotion = (
        None
        if row.promotion_attestation is None
        else _promotion_from_payload(_dict(row.promotion_attestation, "promotion attestation"))
    )
    owner = (
        None
        if row.owner_attestation is None
        else _owner_attestation_from_payload(_dict(row.owner_attestation, "owner attestation"))
    )
    event = OptimizationResearchLifecycleEvent(
        event_id=row.event_id,
        result_id=row.result_id,
        result_hash=row.result_hash,
        event_type=OptimizationLifecycleEventType(row.event_type),
        sequence=row.sequence,
        occurred_at=row.occurred_at,
        recorded_at=row.recorded_at,
        reason_codes=tuple(str(item) for item in _list(row.reason_codes, "reason codes")),
        previous_event_hash=row.previous_event_hash,
        promotion_attestation=promotion,
        owner_attestation=owner,
        content_hash=row.content_hash,
        research_only=row.research_only,
        must_not_execute=row.must_not_execute,
        must_not_use_for_decision=row.must_not_use_for_decision,
    )
    if row.canonical_payload != _lifecycle_payload(event):
        raise ValueError("persisted optimization lifecycle canonical payload mismatch")
    return event


def _candidate_payload(candidate: GovernedCandidateEvidence) -> dict[str, object]:
    return {
        "candidate_kind": candidate.candidate_kind.value,
        "eligible_for_comparison": candidate.eligible_for_comparison,
        "weights": [decimal_text(item) for item in candidate.weights],
        "cash_weight": decimal_text(candidate.cash_weight),
        "solver_status": candidate.solver_status.value,
        "solver_iterations": candidate.solver_iterations,
        "solver_residual": decimal_text(candidate.solver_residual),
        "solver_detail": candidate.solver_detail,
        "metrics": None if candidate.metrics is None else _metrics_payload(candidate.metrics),
        "blockers": [_blocker_payload(item) for item in candidate.blockers],
        "source_evaluation_hash": candidate.source_evaluation_hash,
        "content_hash": candidate.content_hash,
    }


def _candidate_from_payload(payload: dict[str, Any]) -> GovernedCandidateEvidence:
    raw_metrics = payload.get("metrics")
    raw_blockers = _list(payload.get("blockers"), "candidate blockers")
    return GovernedCandidateEvidence(
        candidate_kind=CandidateKind(str(payload["candidate_kind"])),
        eligible_for_comparison=_bool(
            payload["eligible_for_comparison"],
            "eligible_for_comparison",
        ),
        weights=tuple(Decimal(str(item)) for item in _list(payload["weights"], "weights")),
        cash_weight=Decimal(str(payload["cash_weight"])),
        solver_status=SolverConvergenceStatus(str(payload["solver_status"])),
        solver_iterations=_int(payload["solver_iterations"], "solver_iterations"),
        solver_residual=Decimal(str(payload["solver_residual"])),
        solver_detail=str(payload["solver_detail"]),
        metrics=(
            None
            if raw_metrics is None
            else _metrics_from_payload(_dict(raw_metrics, "candidate metrics"))
        ),
        blockers=tuple(
            _blocker_from_payload(_dict(item, "candidate blocker")) for item in raw_blockers
        ),
        source_evaluation_hash=str(payload["source_evaluation_hash"]),
        content_hash=str(payload["content_hash"]),
    )


def _metrics_payload(metrics: CandidateMetricEvidence) -> dict[str, object]:
    return {
        "expected_return": decimal_text(metrics.expected_return),
        "variance": decimal_text(metrics.variance),
        "transaction_cost": decimal_text(metrics.transaction_cost),
        "turnover": decimal_text(metrics.turnover),
        "maximum_drawdown": decimal_text(metrics.maximum_drawdown),
        "scenario_losses": [[code, decimal_text(value)] for code, value in metrics.scenario_losses],
        "macro_factor_variance": decimal_text(metrics.macro_factor_variance),
        "macro_contribution_shares": [
            [code, decimal_text(value)] for code, value in metrics.macro_contribution_shares
        ],
        "macro_max_target_deviation": decimal_text(metrics.macro_max_target_deviation),
        "objective_value": decimal_text(metrics.objective_value),
    }


def _metrics_from_payload(payload: dict[str, Any]) -> CandidateMetricEvidence:
    return CandidateMetricEvidence(
        expected_return=Decimal(str(payload["expected_return"])),
        variance=Decimal(str(payload["variance"])),
        transaction_cost=Decimal(str(payload["transaction_cost"])),
        turnover=Decimal(str(payload["turnover"])),
        maximum_drawdown=Decimal(str(payload["maximum_drawdown"])),
        scenario_losses=_decimal_pairs(payload["scenario_losses"], "scenario_losses"),
        macro_factor_variance=Decimal(str(payload["macro_factor_variance"])),
        macro_contribution_shares=_decimal_pairs(
            payload["macro_contribution_shares"],
            "macro_contribution_shares",
        ),
        macro_max_target_deviation=Decimal(str(payload["macro_max_target_deviation"])),
        objective_value=Decimal(str(payload["objective_value"])),
    )


def _blocker_payload(blocker: CandidateBlockerEvidence) -> dict[str, object]:
    return {
        "code": blocker.code,
        "detail": blocker.detail,
        "asset_code": blocker.asset_code,
        "scenario_revision_id": blocker.scenario_revision_id,
    }


def _blocker_from_payload(payload: dict[str, Any]) -> CandidateBlockerEvidence:
    return CandidateBlockerEvidence(
        code=str(payload["code"]),
        detail=str(payload["detail"]),
        asset_code=(None if payload.get("asset_code") is None else str(payload["asset_code"])),
        scenario_revision_id=(
            None
            if payload.get("scenario_revision_id") is None
            else str(payload["scenario_revision_id"])
        ),
    )


def _result_payload(result: GovernedOptimizationResearchResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": result.result_version,
        "result_id": result.result_id,
        "run_key": result.run_key,
        "run_version": result.run_version,
        "assembly_hash": result.assembly_hash,
        "problem_id": result.problem_id,
        "problem_hash": result.problem_hash,
        "input_set_id": result.input_set_id,
        "input_set_hash": result.input_set_hash,
        "status": result.status.value,
        "candidates": [_candidate_payload(item) for item in result.candidates],
        "selected_candidate": (
            None if result.selected_candidate is None else result.selected_candidate.value
        ),
        "problem_blockers": [list(item) for item in result.problem_blockers],
        "evaluated_at": utc_text(result.evaluated_at),
        "valid_until": utc_text(result.valid_until),
        "content_hash": result.content_hash,
        "research_only": result.research_only,
        "must_not_execute": result.must_not_execute,
        "must_not_use_for_decision": result.must_not_use_for_decision,
    }
    if result.result_version == "governed-optimization-result.v2":
        payload.update(
            {
                "input_receipt_id": result.input_receipt_id,
                "input_receipt_hash": result.input_receipt_hash,
                "input_receipt_schema_version": result.input_receipt_schema_version,
            }
        )
    return payload


def _promotion_payload(attestation: ExactPromotionAttestation) -> dict[str, object]:
    return {
        "capability_key": attestation.capability_key,
        "artifact_id": attestation.artifact_id,
        "artifact_version": attestation.artifact_version,
        "artifact_content_hash": attestation.artifact_content_hash,
        "decision_id": attestation.decision_id,
        "decision_content_hash": attestation.decision_content_hash,
        "owner": attestation.owner,
        "approved_at": utc_text(attestation.approved_at),
        "valid_until": utc_text(attestation.valid_until),
        "retired_at": (
            None if attestation.retired_at is None else utc_text(attestation.retired_at)
        ),
        "attestation_hash": attestation.attestation_hash,
    }


def _promotion_from_payload(payload: dict[str, Any]) -> ExactPromotionAttestation:
    return ExactPromotionAttestation(
        capability_key=str(payload["capability_key"]),
        artifact_id=str(payload["artifact_id"]),
        artifact_version=str(payload["artifact_version"]),
        artifact_content_hash=str(payload["artifact_content_hash"]),
        decision_id=str(payload["decision_id"]),
        decision_content_hash=str(payload["decision_content_hash"]),
        owner=str(payload["owner"]),
        approved_at=datetime.fromisoformat(str(payload["approved_at"])),
        valid_until=datetime.fromisoformat(str(payload["valid_until"])),
        retired_at=(
            None
            if payload.get("retired_at") is None
            else datetime.fromisoformat(str(payload["retired_at"]))
        ),
        attestation_hash=str(payload["attestation_hash"]),
    )


def _owner_attestation_payload(
    attestation: OptimizationLifecycleOwnerAttestation,
) -> dict[str, object]:
    return {
        "attestation_id": attestation.attestation_id,
        "owner": attestation.owner,
        "result_id": attestation.result_id,
        "result_hash": attestation.result_hash,
        "event_type": attestation.event_type.value,
        "reason_hash": attestation.reason_hash,
        "issued_at": utc_text(attestation.issued_at),
        "content_hash": attestation.content_hash,
    }


def _owner_attestation_from_payload(
    payload: dict[str, Any],
) -> OptimizationLifecycleOwnerAttestation:
    return OptimizationLifecycleOwnerAttestation(
        attestation_id=str(payload["attestation_id"]),
        owner=str(payload["owner"]),
        result_id=str(payload["result_id"]),
        result_hash=str(payload["result_hash"]),
        event_type=OptimizationLifecycleEventType(str(payload["event_type"])),
        reason_hash=str(payload["reason_hash"]),
        issued_at=datetime.fromisoformat(str(payload["issued_at"])),
        content_hash=str(payload["content_hash"]),
    )


def _lifecycle_payload(event: OptimizationResearchLifecycleEvent) -> dict[str, object]:
    return {
        "schema_version": "optimization-research-lifecycle-event.v1",
        "event_id": event.event_id,
        "result_id": event.result_id,
        "result_hash": event.result_hash,
        "event_type": event.event_type.value,
        "sequence": event.sequence,
        "occurred_at": utc_text(event.occurred_at),
        "recorded_at": utc_text(event.recorded_at),
        "reason_codes": list(event.reason_codes),
        "previous_event_hash": event.previous_event_hash,
        "promotion_attestation": (
            None
            if event.promotion_attestation is None
            else _promotion_payload(event.promotion_attestation)
        ),
        "owner_attestation": (
            None
            if event.owner_attestation is None
            else _owner_attestation_payload(event.owner_attestation)
        ),
        "content_hash": event.content_hash,
        "research_only": event.research_only,
        "must_not_execute": event.must_not_execute,
        "must_not_use_for_decision": event.must_not_use_for_decision,
    }


def _dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"persisted {label} must be an object")
    return cast(dict[str, Any], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"persisted {label} must be an array")
    return cast(list[object], value)


def _pair(value: object, label: str) -> list[object]:
    pair = _list(value, label)
    if len(pair) != 2:
        raise ValueError(f"persisted {label} must contain two values")
    return pair


def _decimal_pairs(value: object, label: str) -> tuple[tuple[str, Decimal], ...]:
    return tuple(
        (str(pair[0]), Decimal(str(pair[1])))
        for pair in (_pair(item, label) for item in _list(value, label))
    )


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"persisted {label} must be a boolean")
    return value


def _int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"persisted {label} must be an integer")
    return value


__all__ = [
    "lifecycle_model",
    "lifecycle_to_domain",
    "result_model",
    "result_to_domain",
]
