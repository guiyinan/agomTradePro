"""Production composition always supplies the full portfolio-risk guard."""

from __future__ import annotations

from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    CorporateActionTaxCashCoverageReader,
)
from apps.simulated_trading.application.portfolio_risk_execution_gate import (
    ConfiguredPortfolioRiskLockedOrderGuard,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)


class DjangoPortfolioRiskExecutionRepository(DjangoSimulatedTradeExecutionRepository):
    """Keep low-level ledger mechanics injectable and user execution guarded."""

    def __init__(
        self,
        *,
        using: str,
        tax_cash_coverage_reader: CorporateActionTaxCashCoverageReader | None = None,
    ) -> None:
        """Bind the mandatory risk adapter to the same database as the ledger."""

        super().__init__(
            using=using,
            portfolio_risk_guard=ConfiguredPortfolioRiskLockedOrderGuard(using=using),
            tax_cash_coverage_reader=tax_cash_coverage_reader,
        )
