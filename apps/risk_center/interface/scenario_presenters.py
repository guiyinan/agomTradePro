"""Stable JSON projections for governed scenario transports."""

from __future__ import annotations

from typing import Any

from apps.risk_center.application.scenario_dtos import (
    ScenarioSummaryDTO,
    ScenarioValidationDTO,
)
from apps.risk_center.domain.scenarios import (
    ScenarioActivation,
    ScenarioImpact,
    ScenarioRevision,
    ScenarioSetRevision,
    scenario_parameters_to_dict,
)


def present_revision(revision: ScenarioRevision) -> dict[str, Any]:
    """Project one immutable scenario revision with provenance metadata."""

    return {
        "revision_id": revision.revision_id,
        "scenario_key": revision.scenario_key,
        "version": revision.version,
        "based_on_version": revision.based_on_version,
        "status": revision.status.value,
        "scenario_type": revision.scenario_type.value,
        "parameters": scenario_parameters_to_dict(revision.parameters),
        "assumptions": list(revision.assumptions),
        "source_type": revision.source_type.value,
        "source_evidence": list(revision.source_evidence),
        "content_hash": revision.content_hash,
        "created_by": revision.created_by,
        "change_reason": revision.change_reason,
        "effective_at": (revision.effective_at.isoformat() if revision.effective_at else None),
        "created_at": revision.created_at.isoformat(),
    }


def present_summary(summary: ScenarioSummaryDTO) -> dict[str, Any]:
    """Project a stable definition plus its repository-selected revision."""

    definition = summary.definition
    return {
        "scenario_key": definition.scenario_key,
        "name": definition.name,
        "description": definition.description,
        "category": definition.category,
        "owner": definition.owner,
        "status": definition.status.value,
        "legacy_aliases": list(definition.legacy_aliases),
        "revision": present_revision(summary.revision),
    }


def present_set_revision(revision: ScenarioSetRevision) -> dict[str, Any]:
    """Project a versioned scenario set and explicit probability sources."""

    return {
        "revision_id": revision.revision_id,
        "set_key": revision.set_key,
        "version": revision.version,
        "status": revision.status.value,
        "members": [
            {
                "scenario_revision_id": member.scenario_revision_id,
                "probability": str(member.probability),
                "probability_source": member.probability_source.value,
                "sort_order": member.sort_order,
            }
            for member in revision.members
        ],
        "driver_axes": list(revision.driver_axes),
        "created_by": revision.created_by,
        "change_reason": revision.change_reason,
        "created_at": revision.created_at.isoformat(),
        "effective_from": (
            revision.effective_from.isoformat() if revision.effective_from else None
        ),
        "effective_to": (revision.effective_to.isoformat() if revision.effective_to else None),
        "content_hash": revision.content_hash,
    }


def present_validation(result: ScenarioValidationDTO) -> dict[str, Any]:
    """Project a zero-side-effect validation result."""

    return {
        "valid": result.valid,
        "scenario_revision_id": result.scenario_revision_id,
        "content_hash": result.content_hash,
        "errors": list(result.errors),
        "validated_at": result.validated_at.isoformat(),
    }


def present_activation(activation: ScenarioActivation) -> dict[str, Any]:
    """Project one auditable active-set pointer transition."""

    return {
        "activation_id": activation.activation_id,
        "environment": activation.environment,
        "purpose": activation.purpose,
        "scenario_set_revision_id": activation.scenario_set_revision_id,
        "previous_activation_id": activation.previous_activation_id,
        "activated_by": activation.activated_by,
        "reason": activation.reason,
        "activated_at": activation.activated_at.isoformat(),
        "correlation_id": activation.correlation_id,
    }


def present_impact(impact: ScenarioImpact) -> dict[str, Any]:
    """Project a deterministic scenario impact without execution semantics."""

    return {
        "scenario_revision_id": impact.scenario_revision_id,
        "initial_value": str(impact.initial_value),
        "final_value": str(impact.final_value),
        "total_return": str(impact.total_return),
        "max_drawdown": str(impact.max_drawdown),
        "recovery_periods": impact.recovery_periods,
        "volatility": str(impact.volatility),
        "var_95": str(impact.var_95),
        "var_99": str(impact.var_99),
        "period_start": impact.period_start.isoformat() if impact.period_start else None,
        "period_end": impact.period_end.isoformat() if impact.period_end else None,
        "result_hash": impact.result_hash,
    }
