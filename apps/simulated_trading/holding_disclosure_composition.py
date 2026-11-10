"""Composition root for the read-only holding financial-disclosure path."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS

from apps.simulated_trading.application.holding_disclosures import (
    GetHoldingDisclosuresUseCase,
)
from apps.simulated_trading.composition import build_observer_grant_repository
from apps.simulated_trading.infrastructure.holding_disclosure_reader import (
    DjangoOwnedHoldingDisclosureReader,
    PublishedFinancialFactsReader,
)
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)
from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
    DjangoRebalanceResourceSnapshotRepository,
)


def build_holding_disclosure_use_case(
    using: str = DEFAULT_DB_ALIAS,
) -> GetHoldingDisclosuresUseCase:
    """Build the use case with established owner/observer read adapters."""

    account_scope_reader = DjangoPortfolioRiskResourceRepository(
        observer_grant_repository=build_observer_grant_repository(using=using),
        using=using,
    )
    return GetHoldingDisclosuresUseCase(
        holding_reader=DjangoOwnedHoldingDisclosureReader(
            account_scope_reader=account_scope_reader,
            positions_reader=DjangoRebalanceResourceSnapshotRepository(using=using),
        ),
        financial_facts_reader=PublishedFinancialFactsReader(),
    )


__all__: tuple[str, ...] = ("build_holding_disclosure_use_case",)
