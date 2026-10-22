"""Composition root for the read-only simulated rebalance preview."""

from __future__ import annotations

import os

from django.db import DEFAULT_DB_ALIAS

from apps.risk_center.execution_settlement_composition import (
    build_execution_settlement_v3_rule_reader,
)
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
    build_current_reference_identity_reader,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.price_provider import DataCenterPriceProvider
from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
    DjangoRebalanceResourceSnapshotRepository,
)
from apps.strategy.application.execution_gateway import get_strategy_execution_gateway


def build_readonly_rebalance_plan_preview_builder() -> ReadOnlyRebalancePlanPreviewBuilder:
    """Bind existing price, identity, fee, Risk, ledger, and Strategy read ports."""

    return ReadOnlyRebalancePlanPreviewBuilder(
        price_reader=DataCenterPriceProvider(),
        identity_reader=build_current_reference_identity_reader(
            runtime_environment=_runtime_environment(),
        ),
        classification_reader=build_current_reference_classification_reader(
            runtime_environment=_runtime_environment(),
        ),
        fee_policy_reader=DjangoFeePolicyV2Repository(using=DEFAULT_DB_ALIAS),
        quantity_rule_reader=build_execution_settlement_v3_rule_reader(),
        resource_snapshot_reader=DjangoRebalanceResourceSnapshotRepository(using=DEFAULT_DB_ALIAS),
        position_rule_evaluator=get_strategy_execution_gateway(),
    )


def _runtime_environment() -> str:
    """Use the configured production identity scope only in production settings."""

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    return "production" if settings_module.endswith(".production") else "development"


__all__: tuple[str, ...] = ("build_readonly_rebalance_plan_preview_builder",)
