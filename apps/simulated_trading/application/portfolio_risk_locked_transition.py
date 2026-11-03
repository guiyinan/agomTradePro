"""Short serial risk window shared by existing order acceptance and execution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation_fill import LocalSimulatedFillEventV1
from apps.simulated_trading.application.portfolio_risk_execution_gate import (
    PortfolioRiskLockedFillGuard,
    PortfolioRiskLockedOrderGuard,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent


def revalidate_locked_portfolio_order(
    *,
    guard: PortfolioRiskLockedOrderGuard | None,
    intent: SimulatedTradeIntent,
    fee_cap: Decimal,
    market_purpose: str | None = None,
    execution_session: date,
    as_of: datetime,
    read_clock: Callable[[], datetime],
    read_execution_session: Callable[[datetime], date],
) -> datetime:
    """Return a new real execution clock after risk and its expiry/policy recheck."""

    if guard is None:
        return as_of
    qualification = guard.validate_locked_order(
        intent=intent,
        fee_cap=fee_cap,
        market_purpose=market_purpose,
        execution_session=execution_session,
        as_of=as_of,
    )
    checked_at = read_clock()
    if read_execution_session(checked_at) != execution_session:
        raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_EXECUTION_SESSION_CHANGED")
    guard.verify_locked_qualification(qualification=qualification, as_of=checked_at)
    return checked_at


def revalidate_locked_portfolio_fill(
    *,
    guard: PortfolioRiskLockedFillGuard | None,
    intent: SimulatedTradeIntent,
    event: LocalSimulatedFillEventV1,
    market_purpose: str | None = None,
    execution_session: date,
    as_of: datetime,
    read_clock: Callable[[], datetime],
) -> datetime:
    """Recheck one accepted hold and then re-read the actual final execution clock."""

    if guard is None:
        return as_of
    qualification = guard.validate_locked_fill(
        intent=intent,
        event=event,
        market_purpose=market_purpose,
        execution_session=execution_session,
        as_of=as_of,
    )
    checked_at = read_clock()
    guard.verify_locked_qualification(qualification=qualification, as_of=checked_at)
    return checked_at
