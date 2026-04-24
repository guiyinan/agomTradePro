"""Beta Gate repository provider for application consumers."""

from __future__ import annotations

from apps.beta_gate.infrastructure.repositories import (
    GateConfigRepository,
    GateDecisionRepository,
    VisibilityUniverseRepository,
)


def get_beta_gate_config_repository() -> GateConfigRepository:
    """Return the Beta Gate config repository."""

    return GateConfigRepository()


def get_beta_gate_decision_repository() -> GateDecisionRepository:
    """Return the Beta Gate decision repository."""

    return GateDecisionRepository()


def get_beta_gate_universe_repository() -> VisibilityUniverseRepository:
    """Return the Beta Gate universe repository."""

    return VisibilityUniverseRepository()
