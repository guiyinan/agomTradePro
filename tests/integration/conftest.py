"""Shared opt-in fixtures for integration runtime contracts."""

import pytest


@pytest.fixture
def active_decision_runtime(db: object) -> None:
    """Explicitly admit decision-facing integration requests for one test scope."""

    from apps.config_center.infrastructure.decision_runtime_models import (
        DecisionRuntimeStateModel,
    )

    DecisionRuntimeStateModel._default_manager.update_or_create(
        pk=1,
        defaults={
            "status": "active",
            "reason": "",
            "changed_by": "pytest:integration-contract",
        },
    )
