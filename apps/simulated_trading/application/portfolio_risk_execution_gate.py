"""Mandatory portfolio-risk revalidation for composed simulated execution."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from apps.simulated_trading.application.order_reservation_fill import LocalSimulatedFillEventV1
from apps.simulated_trading.application.portfolio_risk_public import (
    validate_owner_portfolio_order,
    validate_owner_portfolio_reserved_fill,
    verify_owner_portfolio_qualification,
)
from apps.simulated_trading.application.portfolio_risk_qualification import (
    PortfolioRiskExecutionQualification,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent


class PortfolioRiskLockedOrderGuard(Protocol):
    """Recheck policy, original sources and all account occupancy under row locks."""

    def validate_locked_order(
        self,
        *,
        intent: SimulatedTradeIntent,
        fee_cap: Decimal,
        market_purpose: str | None,
        as_of: datetime,
        execution_session: date,
    ) -> PortfolioRiskExecutionQualification:
        """Reject the whole ledger transaction when the fresh risk check cannot pass."""
        ...

    def verify_locked_qualification(
        self, *, qualification: PortfolioRiskExecutionQualification, as_of: datetime
    ) -> None:
        """Check expiry and policy identity against the final actual ledger clock."""
        ...


class ConfiguredPortfolioRiskLockedOrderGuard:
    """Call the owner Application service on the ledger's explicit database alias."""

    def __init__(self, *, using: str) -> None:
        """Keep risk reads in the execution transaction's database scope."""

        self._using = using

    def validate_locked_order(
        self,
        *,
        intent: SimulatedTradeIntent,
        fee_cap: Decimal,
        market_purpose: str | None,
        as_of: datetime,
        execution_session: date,
    ) -> PortfolioRiskExecutionQualification:
        """Require a current full risk pass before any trade is committed."""

        return validate_owner_portfolio_order(
            intent=intent,
            fee_cap=fee_cap,
            market_purpose=market_purpose,
            as_of=as_of,
            execution_session=execution_session,
            using=self._using,
        )

    def verify_locked_qualification(
        self, *, qualification: PortfolioRiskExecutionQualification, as_of: datetime
    ) -> None:
        """Keep a passed result from surviving source expiry or a policy replacement."""

        verify_owner_portfolio_qualification(
            qualification=qualification, as_of=as_of, using=self._using
        )

    def validate_locked_fill(
        self,
        *,
        intent: SimulatedTradeIntent,
        event: LocalSimulatedFillEventV1,
        market_purpose: str | None,
        execution_session: date,
        as_of: datetime,
    ) -> PortfolioRiskExecutionQualification:
        """Recheck the existing hold's risk before an existing fill is persisted."""

        return validate_owner_portfolio_reserved_fill(
            intent=intent,
            event=event,
            market_purpose=market_purpose,
            execution_session=execution_session,
            as_of=as_of,
            using=self._using,
        )


class PortfolioRiskLockedFillGuard(Protocol):
    """Risk check for an existing fill, whose accepted hold is already projected."""

    def validate_locked_fill(
        self,
        *,
        intent: SimulatedTradeIntent,
        event: LocalSimulatedFillEventV1,
        market_purpose: str | None,
        execution_session: date,
        as_of: datetime,
    ) -> PortfolioRiskExecutionQualification:
        """Bind an actual source event and the actual remaining accepted hold."""
        ...

    def verify_locked_qualification(
        self,
        *,
        qualification: PortfolioRiskExecutionQualification,
        as_of: datetime,
    ) -> None:
        """Reject source expiry or a policy replacement before persistence."""
        ...
