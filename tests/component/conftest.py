"""Shared fixtures for component-level runtime contracts."""

from __future__ import annotations

import pytest

from tests.support import xdist_worker_contracts
from tests.support.runtime_config import configure_critical_runtime

_COMPONENT_JUNIT_PROPERTIES_KEY = xdist_worker_contracts.JUNIT_PROPERTIES_KEY
_component_junit_sink = xdist_worker_contracts.find_junit_sink
_component_worker_sqlite_test_path = xdist_worker_contracts.worker_sqlite_test_path
_record_component_testsuite_property = xdist_worker_contracts.wrap_testsuite_property_recorder
_replay_component_testsuite_properties = xdist_worker_contracts.replay_testsuite_properties
django_db_modify_db_settings_xdist_suffix = (
    xdist_worker_contracts.django_db_modify_db_settings_xdist_suffix
)
pytest_sessionstart = xdist_worker_contracts.pytest_sessionstart
pytest_testnodedown = xdist_worker_contracts.pytest_testnodedown
record_testsuite_property = xdist_worker_contracts.record_testsuite_property

__all__ = (
    "active_decision_runtime",
    "_COMPONENT_JUNIT_PROPERTIES_KEY",
    "_component_junit_sink",
    "_component_worker_sqlite_test_path",
    "_record_component_testsuite_property",
    "_replay_component_testsuite_properties",
    "django_db_modify_db_settings_xdist_suffix",
    "pytest_sessionstart",
    "pytest_testnodedown",
    "record_testsuite_property",
)


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
