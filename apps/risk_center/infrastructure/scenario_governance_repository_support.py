"""Shared persistence state and value guards for scenario governance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from apps.risk_center.application.scenario_governance import (
    CommitScenarioGovernanceCommand,
)
from apps.risk_center.domain.scenario_governance import (
    ScenarioGovernanceAuditRecord,
    ScenarioGovernanceError,
    ScenarioGovernanceErrorCode,
    ScenarioGovernanceOutcome,
    governance_json_value,
)
from apps.risk_center.infrastructure.models import (
    ScenarioActivationModel,
    ScenarioSetRevisionModel,
    StressScenarioDefinitionModel,
    StressScenarioRevisionModel,
)
from apps.risk_center.infrastructure.scenario_governance_models import (
    ScenarioGovernancePreviewModel,
)


@dataclass(frozen=True)
class ResolvedScenarioGovernanceState:
    """Authoritative state resolved for one governance request."""

    scenario_key: str | None
    base_version: int | None
    base_hash: str | None
    after_hash: str
    definition: StressScenarioDefinitionModel | None = None
    latest_revision: StressScenarioRevisionModel | None = None
    target_set_revision: ScenarioSetRevisionModel | None = None
    rollback_target: ScenarioSetRevisionModel | None = None
    current_activation: ScenarioActivationModel | None = None


@dataclass(frozen=True)
class ScenarioGovernanceCommitContext:
    """Bound preview and resolved state for one atomic commit."""

    command: CommitScenarioGovernanceCommand
    preview: ScenarioGovernancePreviewModel
    state: ResolvedScenarioGovernanceState
    request_fingerprint: str


@dataclass(frozen=True)
class ScenarioGovernanceCommitProduct:
    """Outcome and audit evidence produced by one commit executor."""

    outcome: ScenarioGovernanceOutcome
    audit: ScenarioGovernanceAuditRecord


def json_object(value: object) -> dict[str, object]:
    """Normalize one persistence value as a JSON object."""

    safe = governance_json_value(value)
    if not isinstance(safe, Mapping):
        raise ValueError("governance persistence value must be an object")
    return {str(key): item for key, item in safe.items()}


def json_array(value: object) -> list[object]:
    """Normalize one persistence value as a JSON array."""

    safe = governance_json_value(value)
    if not isinstance(safe, list):
        raise ValueError("governance persistence value must be an array")
    return safe


def required_text(
    payload: Mapping[str, object],
    field_name: str,
    *,
    maximum: int,
) -> str:
    """Read one required bounded text field from a payload."""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ScenarioGovernanceError(
            ScenarioGovernanceErrorCode.INVALID_REQUEST,
            f"{field_name} is required and must not exceed {maximum} characters",
        )
    return value.strip()


def optional_payload_text(
    payload: Mapping[str, object],
    field_name: str,
    *,
    maximum: int,
) -> str:
    """Read one optional bounded text field from a payload."""

    value = payload.get(field_name)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise ScenarioGovernanceError(
            ScenarioGovernanceErrorCode.INVALID_REQUEST,
            f"{field_name} must not exceed {maximum} characters",
        )
    return value.strip()
