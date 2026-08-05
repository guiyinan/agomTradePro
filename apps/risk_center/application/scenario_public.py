"""Stable application facade for scenario transports and compatibility callers."""

from __future__ import annotations

from apps.risk_center.application.scenario_dtos import (
    ActivateScenarioSetCommandDTO,
    CreateScenarioRevisionCommandDTO,
    ScenarioSummaryDTO,
    ScenarioValidationDTO,
)
from apps.risk_center.application.scenario_repository_provider import (
    get_scenario_activation_repository,
    get_scenario_query_repository,
    get_scenario_revision_repository,
)
from apps.risk_center.application.scenario_use_cases import (
    ActivateScenarioSetRevisionUseCase,
    CreateScenarioRevisionDraftUseCase,
    GetActiveScenarioSetUseCase,
    GetScenarioRevisionUseCase,
    ListScenarioDefinitionsUseCase,
    ListScenarioRevisionsUseCase,
    ValidateScenarioRevisionUseCase,
)
from apps.risk_center.domain.scenarios import (
    ScenarioActivation,
    ScenarioRevision,
    ScenarioSetRevision,
    ScenarioType,
)


def list_scenarios(
    *,
    scenario_type: ScenarioType | None = None,
    include_inactive: bool = False,
) -> tuple[ScenarioSummaryDTO, ...]:
    """List repository-driven current scenarios with no code fallback."""

    return ListScenarioDefinitionsUseCase(get_scenario_query_repository()).execute(
        scenario_type=scenario_type,
        include_inactive=include_inactive,
    )


def get_scenario(identifier: str, *, version: int | None = None) -> ScenarioRevision:
    """Resolve a scenario by immutable id, canonical key, or legacy alias."""

    return GetScenarioRevisionUseCase(get_scenario_query_repository()).execute(
        identifier,
        version=version,
    )


def list_scenario_revisions(identifier: str) -> tuple[ScenarioRevision, ...]:
    """List every immutable revision for a canonical key or legacy alias."""

    return ListScenarioRevisionsUseCase(get_scenario_query_repository()).execute(identifier)


def get_active_scenario_set(*, environment: str, purpose: str) -> ScenarioSetRevision:
    """Return the active scenario set or fail closed when it is absent."""

    return GetActiveScenarioSetUseCase(get_scenario_query_repository()).execute(
        environment=environment,
        purpose=purpose,
    )


def validate_scenario_revision(revision: ScenarioRevision) -> ScenarioValidationDTO:
    """Return side-effect-free validation and stable content-hash evidence."""

    return ValidateScenarioRevisionUseCase().execute(revision)


def create_scenario_revision_draft(
    command: CreateScenarioRevisionCommandDTO,
) -> ScenarioRevision:
    """Append a server-versioned candidate/draft/proposal revision."""

    return CreateScenarioRevisionDraftUseCase(get_scenario_revision_repository()).execute(command)


def activate_scenario_set_revision(
    command: ActivateScenarioSetCommandDTO,
) -> ScenarioActivation:
    """Atomically move the active pointer using optimistic-lock evidence."""

    return ActivateScenarioSetRevisionUseCase(get_scenario_activation_repository()).execute(command)


__all__ = [
    "activate_scenario_set_revision",
    "create_scenario_revision_draft",
    "get_active_scenario_set",
    "get_scenario",
    "list_scenarios",
    "list_scenario_revisions",
    "validate_scenario_revision",
]
