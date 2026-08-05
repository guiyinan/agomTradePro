"""Configured scenario persistence ports for public application facades."""

from __future__ import annotations

from apps.risk_center.application.scenario_ports import (
    ScenarioActivationRepositoryProtocol,
    ScenarioQueryRepositoryProtocol,
    ScenarioRevisionRepositoryProtocol,
    ScenarioRunEvidenceRepositoryProtocol,
)

_query_repository: ScenarioQueryRepositoryProtocol | None = None
_revision_repository: ScenarioRevisionRepositoryProtocol | None = None
_activation_repository: ScenarioActivationRepositoryProtocol | None = None
_evidence_repository: ScenarioRunEvidenceRepositoryProtocol | None = None


def configure_scenario_repositories(
    *,
    query_repository: ScenarioQueryRepositoryProtocol,
    revision_repository: ScenarioRevisionRepositoryProtocol,
    activation_repository: ScenarioActivationRepositoryProtocol,
    evidence_repository: ScenarioRunEvidenceRepositoryProtocol,
) -> None:
    """Configure scenario ports at the Risk Center composition root."""

    global _query_repository, _revision_repository, _activation_repository, _evidence_repository
    _query_repository = query_repository
    _revision_repository = revision_repository
    _activation_repository = activation_repository
    _evidence_repository = evidence_repository


def get_scenario_query_repository() -> ScenarioQueryRepositoryProtocol:
    """Return the configured query repository or fail closed."""

    if _query_repository is None:
        raise RuntimeError("scenario query repository is not configured")
    return _query_repository


def get_scenario_revision_repository() -> ScenarioRevisionRepositoryProtocol:
    """Return the configured append repository or fail closed."""

    if _revision_repository is None:
        raise RuntimeError("scenario revision repository is not configured")
    return _revision_repository


def get_scenario_activation_repository() -> ScenarioActivationRepositoryProtocol:
    """Return the configured activation repository or fail closed."""

    if _activation_repository is None:
        raise RuntimeError("scenario activation repository is not configured")
    return _activation_repository


def get_scenario_evidence_repository() -> ScenarioRunEvidenceRepositoryProtocol:
    """Return the configured run-evidence repository or fail closed."""

    if _evidence_repository is None:
        raise RuntimeError("scenario evidence repository is not configured")
    return _evidence_repository


__all__ = [
    "configure_scenario_repositories",
    "get_scenario_activation_repository",
    "get_scenario_evidence_repository",
    "get_scenario_query_repository",
    "get_scenario_revision_repository",
]
