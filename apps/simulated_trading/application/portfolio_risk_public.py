"""Owner-scoped public entry points for simulation-only portfolio risk."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioPressureOptionsPayload,
    PortfolioRiskReportPayload,
)
from apps.simulated_trading.application.order_reservation_fill import LocalSimulatedFillEventV1
from apps.simulated_trading.application.portfolio_risk_qualification import (
    PortfolioRiskExecutionQualification,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import RebalancePlanPreview
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from core.exceptions import AuthorizationError, BusinessLogicError, InvalidInputError


class PortfolioRiskAccountAccessDenied(AuthorizationError):
    """The actor cannot inspect or run risk for this simulated account."""

    default_code = "PORTFOLIO_RISK_ACCOUNT_ACCESS_DENIED"


class PortfolioRiskUnavailable(BusinessLogicError):
    """The risk read service cannot obtain a consistent account snapshot."""

    default_code = "PORTFOLIO_RISK_UNAVAILABLE"
    default_status_code = 503


class PortfolioRiskService(Protocol):
    """Read an owned report or explicitly retain a pressure-run proof."""

    def get_report(self, *, user_id: int, account_id: int) -> PortfolioRiskReportPayload:
        """Read constraints without changing business state."""
        ...

    def run_pressure(
        self,
        *,
        user_id: int,
        account_id: int,
        scenario_version_id: str,
        idempotency_key: str,
    ) -> PortfolioRiskReportPayload:
        """Persist only explicitly requested, owner-scoped Scenario evidence."""
        ...

    def validate_order(
        self,
        *,
        intent: SimulatedTradeIntent,
        fee_cap: Decimal,
        market_purpose: str | None,
        as_of: datetime,
        execution_session: date,
    ) -> PortfolioRiskExecutionQualification:
        """Revalidate one actual locked submission against current risk inputs."""
        ...

    def verify_qualification(
        self, *, qualification: PortfolioRiskExecutionQualification, as_of: datetime
    ) -> None:
        """Reject expiry or policy replacement before the final market check."""
        ...

    def validate_reserved_fill(
        self,
        *,
        intent: SimulatedTradeIntent,
        event: LocalSimulatedFillEventV1,
        market_purpose: str | None,
        execution_session: date,
        as_of: datetime,
    ) -> PortfolioRiskExecutionQualification:
        """Recheck an actual accepted hold without double counting its fill."""
        ...

    def assess_preview(
        self, *, user_id: int, account_id: int, preview: RebalancePlanPreview
    ) -> PortfolioRiskReportPayload:
        """Assess all candidate orders without placing or reserving them."""
        ...

    def get_pressure_options(
        self, *, user_id: int, account_id: int
    ) -> PortfolioPressureOptionsPayload:
        """Read approved Scenario choices only after checking account read scope."""
        ...


_service_factory: Callable[[str], PortfolioRiskService] | None = None


def configure_portfolio_risk_service(factory: Callable[[str], PortfolioRiskService]) -> None:
    """Register a lazy composition-root factory without reading account data."""

    global _service_factory
    _service_factory = factory


def _service(*, user_id: int, account_id: int, using: str = "default") -> PortfolioRiskService:
    if type(user_id) is not int or user_id <= 0:
        raise PortfolioRiskAccountAccessDenied()
    if type(account_id) is not int or account_id <= 0:
        raise PortfolioRiskAccountAccessDenied()
    if _service_factory is None:
        raise PortfolioRiskUnavailable()
    return _service_factory(using)


def validate_owner_portfolio_order(
    *,
    intent: SimulatedTradeIntent,
    fee_cap: Decimal,
    market_purpose: str | None,
    as_of: datetime,
    execution_session: date,
    using: str,
) -> PortfolioRiskExecutionQualification:
    """Recheck a server-owned submission within its existing locked transaction."""

    intent.__post_init__()
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise InvalidInputError(code="PORTFOLIO_RISK_NAIVE_CUTOFF")
    return _service(
        user_id=intent.user_id, account_id=intent.account_id, using=using
    ).validate_order(
        intent=intent,
        fee_cap=fee_cap,
        market_purpose=market_purpose,
        as_of=as_of,
        execution_session=execution_session,
    )


def verify_owner_portfolio_qualification(
    *, qualification: PortfolioRiskExecutionQualification, as_of: datetime, using: str
) -> None:
    """Verify the unchanged policy identity and original deadline at execution time."""

    _service(
        user_id=qualification.owner_user_id, account_id=qualification.account_id, using=using
    ).verify_qualification(qualification=qualification, as_of=as_of)


def validate_owner_portfolio_reserved_fill(
    *,
    intent: SimulatedTradeIntent,
    event: LocalSimulatedFillEventV1,
    market_purpose: str | None,
    execution_session: date,
    as_of: datetime,
    using: str,
) -> PortfolioRiskExecutionQualification:
    """Qualify an actual existing local fill inside the account's ledger transaction."""

    return _service(
        user_id=intent.user_id, account_id=intent.account_id, using=using
    ).validate_reserved_fill(
        intent=intent,
        event=event,
        market_purpose=market_purpose,
        execution_session=execution_session,
        as_of=as_of,
    )


def get_owner_portfolio_risk(*, user_id: int, account_id: int) -> PortfolioRiskReportPayload:
    """Return an owned simulated account's read-only constraint report."""

    return _service(user_id=user_id, account_id=account_id).get_report(
        user_id=user_id, account_id=account_id
    )


def assess_owner_portfolio_preview(
    *, user_id: int, account_id: int, preview: RebalancePlanPreview
) -> PortfolioRiskReportPayload:
    """Assess one complete read-only preview using the current owner-scoped inputs."""

    return _service(user_id=user_id, account_id=account_id).assess_preview(
        user_id=user_id, account_id=account_id, preview=preview
    )


def get_owner_portfolio_pressure_options(
    *, user_id: int, account_id: int
) -> PortfolioPressureOptionsPayload:
    """Return named approved scenarios without exposing an unscoped account directory."""

    return _service(user_id=user_id, account_id=account_id).get_pressure_options(
        user_id=user_id, account_id=account_id
    )


def run_owner_portfolio_pressure(
    *,
    user_id: int,
    account_id: int,
    scenario_version_id: str,
    idempotency_key: str,
    confirmed: bool,
) -> PortfolioRiskReportPayload:
    """Run an explicitly confirmed pressure scenario without executing orders."""

    if confirmed is not True:
        raise InvalidInputError(code="PORTFOLIO_PRESSURE_CONFIRMATION_REQUIRED")
    if not scenario_version_id.strip() or not idempotency_key.strip():
        raise InvalidInputError(code="PORTFOLIO_PRESSURE_IDENTITY_REQUIRED")
    return _service(user_id=user_id, account_id=account_id).run_pressure(
        user_id=user_id,
        account_id=account_id,
        scenario_version_id=scenario_version_id,
        idempotency_key=idempotency_key,
    )
