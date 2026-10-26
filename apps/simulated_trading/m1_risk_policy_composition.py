"""Composition root for owner publishing and read-only M1 risk evaluation."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS

from apps.account.owner_profile_identity_composition import (
    build_account_owner_profile_identity_query,
)
from apps.risk_center.m1_rebalance_risk_policy_composition import (
    build_m1_risk_policy_application,
)
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    PublishOwnerM1RiskPolicyRevisionUseCase,
    RevokeOwnerM1RiskPolicyRevisionUseCase,
)
from apps.simulated_trading.infrastructure.m1_risk_policy_account_source_reader import (
    DjangoM1RiskPolicyAccountSourceReader,
)
from apps.simulated_trading.infrastructure.m1_risk_policy_strategy_source_reader import (
    AccountProfileScopedStrategyM1RiskSourceReader,
)
from apps.strategy.application.execution_gateway import get_strategy_execution_gateway


def build_strategy_m1_risk_source_reader() -> AccountProfileScopedStrategyM1RiskSourceReader:
    """Resolve User IDs through Account before asking Strategy for owner-scoped content."""

    return AccountProfileScopedStrategyM1RiskSourceReader(
        owner_profile_identity=build_account_owner_profile_identity_query(
            using=DEFAULT_DB_ALIAS,
        ),
        strategy_gateway=get_strategy_execution_gateway(),
    )


def build_owner_m1_risk_policy_publisher() -> PublishOwnerM1RiskPolicyRevisionUseCase:
    """Build the owner-only publisher from live account and Strategy sources."""

    return PublishOwnerM1RiskPolicyRevisionUseCase(
        account_source_reader=DjangoM1RiskPolicyAccountSourceReader(using=DEFAULT_DB_ALIAS),
        strategy_source_reader=build_strategy_m1_risk_source_reader(),
        risk_policy_application=build_m1_risk_policy_application(using=DEFAULT_DB_ALIAS),
    )


def build_owner_m1_risk_policy_revoker() -> RevokeOwnerM1RiskPolicyRevisionUseCase:
    """Build the owner-only revoker using the existing append-only audit model."""

    return RevokeOwnerM1RiskPolicyRevisionUseCase(
        account_source_reader=DjangoM1RiskPolicyAccountSourceReader(using=DEFAULT_DB_ALIAS),
        risk_policy_application=build_m1_risk_policy_application(using=DEFAULT_DB_ALIAS),
    )


__all__: tuple[str, ...] = (
    "build_strategy_m1_risk_source_reader",
    "build_owner_m1_risk_policy_publisher",
    "build_owner_m1_risk_policy_revoker",
)
