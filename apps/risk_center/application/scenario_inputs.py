"""Typed conversion from validated transport payloads to scenario commands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import cast

from apps.risk_center.application.scenario_dtos import CreateScenarioRevisionCommandDTO
from apps.risk_center.domain.scenarios import (
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
    scenario_parameters_from_mapping,
)


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _string_tuple(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{key} must be an array")
    items = tuple(str(item).strip() for item in value)
    if not items or any(not item for item in items):
        raise ValueError(f"{key} must contain non-empty strings")
    return items


def _source_evidence(payload: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    value = payload.get("evidence")
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("evidence must be an array")
    evidence: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("evidence items must be objects")
        evidence.append({str(key): nested for key, nested in item.items()})
    review_date = payload.get("review_date")
    if isinstance(review_date, date):
        review_value = review_date.isoformat()
    else:
        review_value = str(review_date or "").strip()
    evidence.append(
        {
            "kind": "scenario_governance",
            "invalidation_logic": _string(payload, "invalidation_logic"),
            "review_date": review_value,
        }
    )
    return tuple(evidence)


def build_revision_command(
    payload: Mapping[str, object],
    *,
    actor: str,
    status: ScenarioRevisionStatus = ScenarioRevisionStatus.DRAFT,
) -> CreateScenarioRevisionCommandDTO:
    """Build a strict append command from serializer-validated input."""

    scenario_type = ScenarioType(_string(payload, "scenario_type"))
    raw_parameters = payload.get("parameters")
    if not isinstance(raw_parameters, Mapping):
        raise ValueError("parameters must be an object")
    based_on_raw = payload.get("based_on_version")
    if based_on_raw is None:
        based_on_version = None
    elif isinstance(based_on_raw, bool) or not isinstance(based_on_raw, int):
        raise ValueError("based_on_version must be an integer")
    else:
        based_on_version = based_on_raw
    return CreateScenarioRevisionCommandDTO(
        scenario_key=_string(payload, "scenario_key"),
        scenario_type=scenario_type,
        parameters=scenario_parameters_from_mapping(
            scenario_type,
            cast(Mapping[str, object], raw_parameters),
        ),
        assumptions=_string_tuple(payload, "assumptions"),
        source_type=ScenarioSourceType(_string(payload, "source_type")),
        created_by=actor,
        change_reason=_string(payload, "change_reason"),
        status=status,
        based_on_version=based_on_version,
        source_evidence=_source_evidence(payload),
    )


def build_validation_revision(
    payload: Mapping[str, object],
    *,
    actor: str,
) -> ScenarioRevision:
    """Build an ephemeral immutable revision for zero-write validation."""

    command = build_revision_command(payload, actor=actor)
    version = (command.based_on_version or 0) + 1
    return ScenarioRevision(
        revision_id="validation-preview",
        scenario_key=command.scenario_key,
        version=version,
        based_on_version=command.based_on_version,
        status=ScenarioRevisionStatus.DRAFT,
        scenario_type=command.scenario_type,
        parameters=command.parameters,
        assumptions=command.assumptions,
        source_type=command.source_type,
        source_evidence=command.source_evidence,
        created_by=actor,
        change_reason=command.change_reason,
        created_at=datetime.now(UTC),
    )


__all__ = ["build_revision_command", "build_validation_revision"]
