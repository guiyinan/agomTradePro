"""Pure migration contracts for database routing and reverse safety."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.db.migrations import RunPython

_migration = importlib.import_module(
    "apps.risk_center.migrations.0012_m1_rebalance_risk_policy_immutable"
)


class _RejectingRouter:
    """Record the alias passed to callbacks and reject database changes."""

    def __init__(self) -> None:
        self.aliases: list[str] = []

    def allow_migrate_model(self, alias: str, model: type[object]) -> bool:
        """Reject migration while retaining the exact alias for the assertion."""

        del model
        self.aliases.append(alias)
        return False


def test_trigger_operation_is_bound_to_the_revision_model_and_reversible() -> None:
    """Django's operation router can target the M1 model and has a real reverse."""

    operations = [
        operation
        for operation in _migration.Migration.operations
        if isinstance(operation, RunPython)
    ]
    assert len(operations) == 1
    operation = operations[0]
    assert operation.hints == {"model_name": "m1rebalance_risk_policy_revision_model"}
    assert operation.code is _migration.install_revision_immutability
    assert operation.reverse_code is _migration.remove_revision_immutability


def test_trigger_callbacks_respect_the_schema_editor_database_alias(monkeypatch) -> None:
    """Forward and reverse callbacks stop before touching a router-rejected alias."""

    rejecting_router = _RejectingRouter()
    monkeypatch.setattr(_migration, "router", rejecting_router)
    schema_editor = SimpleNamespace(
        connection=SimpleNamespace(alias="risk_archive", vendor="sqlite")
    )

    _migration.install_revision_immutability(django_apps, schema_editor)
    _migration.remove_revision_immutability(django_apps, schema_editor)

    assert rejecting_router.aliases == ["risk_archive", "risk_archive"]
