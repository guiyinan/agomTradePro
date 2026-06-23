"""Application-level config-center query helpers for TUI/runtime consumers."""

from __future__ import annotations

from apps.config_center.application.repository_provider import (
    get_qlib_training_run_repository,
)


def has_qlib_training_runs() -> bool:
    """Return whether training-run rows exist for same-screen detail drilldown."""

    run_repository = get_qlib_training_run_repository()
    return bool(run_repository.list_runs(limit=1))
