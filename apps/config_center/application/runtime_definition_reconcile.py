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
    RuntimeConfigDefinition(
        key="alpha.qlib.enabled",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.BOOL,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Whether Qlib-backed alpha inference is enabled.",
        user_impact="Controls whether the Qlib alpha provider may participate in inference.",
    ),
    RuntimeConfigDefinition(
        key="alpha.qlib.provider_uri",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.STRING,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.RESTART_REQUIRED,
        description="Qlib data provider URI used by alpha inference and calendar checks.",
        user_impact="Changing the URI changes the local Qlib data source used by alpha jobs.",
    ),
    RuntimeConfigDefinition(
        key="alpha.qlib.region",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.STRING,
        constraints={"choices": ["CN", "US"]},
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Qlib market region used when initializing the alpha runtime.",
        user_impact="Controls the market-specific Qlib calendar and instrument conventions.",
    ),
    RuntimeConfigDefinition(
        key="alpha.qlib.model_path",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.STRING,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.RESTART_REQUIRED,
        description="Filesystem path containing Qlib model artifacts.",
        user_impact="Changing the path changes which model artifacts can be loaded.",
    ),
    RuntimeConfigDefinition(
        key="alpha.qlib.default_universe",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.STRING,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Default Qlib instrument universe for alpha jobs.",
        user_impact="Controls the universe used when a job does not specify one explicitly.",
    ),
    RuntimeConfigDefinition(
        key="alpha.qlib.default_feature_set_id",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.STRING,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Default feature-set identifier for Qlib training and inference.",
        user_impact="Controls the feature contract used when a job omits a feature-set ID.",
    ),
    RuntimeConfigDefinition(
        key="alpha.qlib.default_label_id",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.STRING,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Default label identifier for Qlib training.",
        user_impact="Controls the prediction target when a training job omits a label ID.",
    ),
    RuntimeConfigDefinition(
        key="alpha.qlib.train_queue_name",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.STRING,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Celery queue used for Qlib training tasks.",
        user_impact="Changing the queue changes where training work is dispatched.",
    ),
    RuntimeConfigDefinition(
        key="alpha.qlib.infer_queue_name",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.STRING,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Celery queue used for Qlib inference tasks.",
        user_impact="Changing the queue changes where inference work is dispatched.",
    ),
    RuntimeConfigDefinition(
        key="alpha.qlib.allow_auto_activate",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.BOOL,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Whether Qlib training may automatically activate a produced model.",
        user_impact="Controls whether successful training can change the active model without manual review.",
    ),
    RuntimeConfigDefinition(
        key="alpha.runtime.fixed_provider",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.ENUM,
        constraints={"choices": ["", "qlib", "cache", "simple", "etf"]},
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Optional fixed Alpha provider; empty means controlled failover.",
        user_impact="Pins Alpha provider selection when explicitly configured.",
    ),
    RuntimeConfigDefinition(
        key="alpha.runtime.pool_mode",
        namespace="alpha",
        owner_app="alpha",
        value_type=RuntimeValueType.ENUM,
        constraints={"choices": ["strict_valuation", "market", "price_covered"]},
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Default Alpha candidate-pool mode.",
        user_impact="Controls which evidence-qualified candidate universe Alpha may use.",
    ),
    RuntimeConfigDefinition(
        key="config_center.market.color_convention",
        namespace="config_center",
        owner_app="config_center",
        value_type=RuntimeValueType.ENUM,
        constraints={"choices": ["cn_a_share", "us_market"]},
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.IMMEDIATE,
        description="Market visual convention used by client projections.",
        user_impact="Controls the display semantics of rising and falling values.",
    ),
    RuntimeConfigDefinition(
        key="config_center.market.benchmark_code_map",
        namespace="config_center",
        owner_app="config_center",
        value_type=RuntimeValueType.TYPED_JSON,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Named benchmark codes used by business Application facades.",
        user_impact="Controls benchmark instruments used in comparisons and attribution.",
    ),
    RuntimeConfigDefinition(
        key="config_center.market.asset_proxy_code_map",
        namespace="config_center",
        owner_app="config_center",
        value_type=RuntimeValueType.TYPED_JSON,
        criticality=RuntimeConfigCriticality.NORMAL,
        reload_mode=RuntimeConfigReloadMode.NEXT_TASK,
        description="Asset-class to canonical proxy code mapping.",
        user_impact="Controls proxy instruments used when an asset class has no direct quote.",
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
