"""Application-level query helpers for TUI/runtime consumers."""

from __future__ import annotations

from apps.beta_gate.application.repository_provider import (
    get_beta_gate_config_repository,
    get_beta_gate_decision_repository,
    get_beta_gate_universe_repository,
)


def has_beta_gate_configs() -> bool:
    """Return whether any Beta Gate config rows exist for operator selection."""

    config_repo = get_beta_gate_config_repository()
    return bool(config_repo.list_latest(limit=1))


def has_beta_gate_decisions() -> bool:
    """Return whether any Beta Gate decision rows exist for operator selection."""

    decision_repo = get_beta_gate_decision_repository()
    return bool(decision_repo.get_latest(limit=1))


def has_beta_gate_universe_snapshots() -> bool:
    """Return whether any Beta Gate universe rows exist for operator selection."""

    universe_repo = get_beta_gate_universe_repository()
    return bool(universe_repo.get_history(limit=1))
