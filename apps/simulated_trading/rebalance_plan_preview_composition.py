"""Composition root for the read-only simulated rebalance preview."""

from __future__ import annotations

import os

from django.db import DEFAULT_DB_ALIAS

from apps.risk_center.execution_settlement_composition import (
    build_execution_settlement_v3_rule_reader,
)
from apps.risk_center.m1_rebalance_risk_policy_composition import (
    build_m1_risk_policy_application,
)
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.application.rebalance_preview_reference_close import (
    ReferencePriceBasis,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
    build_current_reference_identity_reader,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.m1_risk_policy_account_source_reader import (
    DjangoM1RiskPolicyAccountSourceReader,
)
from apps.simulated_trading.infrastructure.price_provider import DataCenterPriceProvider
from apps.simulated_trading.infrastructure.published_close_price_reader import (
    PublishedClosePriceReader,
)
from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
    DjangoRebalanceResourceSnapshotRepository,
)
from apps.simulated_trading.m1_risk_policy_composition import (
    build_strategy_m1_risk_source_reader,
)
from apps.strategy.application.execution_gateway import get_strategy_execution_gateway


def build_readonly_rebalance_plan_preview_builder(
    *,
    reference_price_basis: ReferencePriceBasis = "market",
) -> ReadOnlyRebalancePlanPreviewBuilder:
    """Bind the selected price lane and existing identity, fee, Risk, and ledger ports."""

    if reference_price_basis not in {"market", "published_close"}:
        raise ValueError("Unsupported rebalance preview reference price basis")
    strategy_gateway = get_strategy_execution_gateway()
    risk_policy_application = build_m1_risk_policy_application(using=DEFAULT_DB_ALIAS)
    return ReadOnlyRebalancePlanPreviewBuilder(
        price_reader=DataCenterPriceProvider(),
        reference_close_reader=(
            PublishedClosePriceReader() if reference_price_basis == "published_close" else None
        ),
        reference_price_basis=reference_price_basis,
        identity_reader=build_current_reference_identity_reader(
            runtime_environment=_runtime_environment(),
        ),
        classification_reader=build_current_reference_classification_reader(
            runtime_environment=_runtime_environment(),
        ),
        fee_policy_reader=DjangoFeePolicyV2Repository(using=DEFAULT_DB_ALIAS),
        quantity_rule_reader=build_execution_settlement_v3_rule_reader(),
        resource_snapshot_reader=DjangoRebalanceResourceSnapshotRepository(using=DEFAULT_DB_ALIAS),
        position_rule_evaluator=strategy_gateway,
        risk_policy_qualifier=risk_policy_application.qualify,
        risk_policy_account_source_reader=DjangoM1RiskPolicyAccountSourceReader(
            using=DEFAULT_DB_ALIAS,
        ),
        strategy_risk_source_reader=build_strategy_m1_risk_source_reader(),
    )


def _runtime_environment() -> str:
    """Use the configured production identity scope only in production settings."""

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    return "production" if settings_module.endswith(".production") else "development"


__all__: tuple[str, ...] = ("build_readonly_rebalance_plan_preview_builder",)
