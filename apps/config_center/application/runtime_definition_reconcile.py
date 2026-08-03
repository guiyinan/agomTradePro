"""Idempotent bootstrap of the Config Center runtime definition registry."""

from __future__ import annotations

from apps.config_center.application.runtime_config import (
    RuntimeConfigDefinitionRepositoryPort,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigCriticality,
    RuntimeConfigDefinition,
    RuntimeConfigReloadMode,
    RuntimeValueType,
)

DEFAULT_RUNTIME_DEFINITIONS: tuple[RuntimeConfigDefinition, ...] = (
    RuntimeConfigDefinition(
        key="data_center.provider.failover_tolerance",
        namespace="data_center",
        owner_app="data_center",
        value_type=RuntimeValueType.DECIMAL,
        constraints={"minimum": 0.0, "maximum": 1.0},
        criticality=RuntimeConfigCriticality.CRITICAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Cross-provider consistency tolerance for macro failover.",
        user_impact="Controls when provider responses are considered inconsistent.",
    ),
    RuntimeConfigDefinition(
        key="data_center.provider.enable_failover",
        namespace="data_center",
        owner_app="data_center",
        value_type=RuntimeValueType.BOOL,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Whether the macro provider adapter may fail over to a backup source.",
        user_impact="Disabling failover leaves only the configured primary provider.",
    ),
)


def reconcile_runtime_definitions(
    repository: RuntimeConfigDefinitionRepositoryPort,
    definitions: tuple[RuntimeConfigDefinition, ...] = DEFAULT_RUNTIME_DEFINITIONS,
) -> tuple[RuntimeConfigDefinition, ...]:
    """Upsert the owned definition catalog and return persisted definitions.

    The infrastructure repository performs an update-or-create by stable key,
    so running this operation repeatedly is safe and does not create duplicate
    definitions.
    """

    persisted: list[RuntimeConfigDefinition] = []
    for definition in definitions:
        persisted.append(repository.save(definition))
    return tuple(persisted)


__all__ = ["DEFAULT_RUNTIME_DEFINITIONS", "reconcile_runtime_definitions"]
