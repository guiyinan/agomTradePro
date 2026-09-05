"""Shared fixtures for component-level runtime contracts."""

import pytest

from tests.support.runtime_config import configure_critical_runtime


@pytest.fixture
def active_decision_runtime(db: object) -> None:
    """Explicitly admit decision-facing component requests for the test scope."""

    configure_critical_runtime()

    from apps.config_center.infrastructure.decision_runtime_models import (
        DecisionRuntimeStateModel,
    )

    DecisionRuntimeStateModel._default_manager.update_or_create(
        pk=1,
        defaults={
            "status": "active",
            "reason": "",
            "changed_by": "pytest:component-contract",
        },
    )
