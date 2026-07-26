"""Policy hedging application orchestration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, TypedDict, cast

from django.utils import timezone

from apps.policy.application.repository_provider import get_hedge_position_repository
from apps.policy.domain.entities import PolicyLevel
from apps.policy.domain.hedging import (
    HedgeCalculationResult,
    HedgePolicyConfig,
    calculate_policy_hedge,
)
from core.integration.policy_hedging_registry import (
    get_position_repository as _get_account_position_repository,
)
from core.integration.policy_hedging_registry import (
    get_price_repository as get_realtime_price_repository,
)
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


class PositionWeight(TypedDict):
    """Minimal position projection used by hedge analysis."""

    asset_code: str
    weight: float


class PriceRecord(Protocol):
    """Latest-price projection consumed by hedge execution."""

    price: object


class RealtimePriceRepository(Protocol):
    """Price repository boundary for policy hedging."""

    def get_latest_price(self, instrument_code: str) -> PriceRecord | None:
        """Return the latest price for an instrument."""


class AccountPositionRepository(Protocol):
    """Account-owned portfolio and position boundary."""

    def user_owns_portfolio(self, *, portfolio_id: int, user_id: int) -> bool:
        """Return whether the user owns the portfolio."""

    def list_portfolio_position_weights(self, portfolio_id: int) -> list[PositionWeight]:
        """Return normalized position weights."""


class HedgeSnapshot(TypedDict, total=False):
    """Hedge persistence projection consumed by the application."""

    id: int
    portfolio_id: int
    instrument_code: str
    instrument_type: str
    hedge_ratio: float
    hedge_value: Decimal
    policy_level: str
    status: str
    execution_price: Decimal | None
    executed_at: datetime | None
    opening_cost: Decimal | None
    closing_cost: Decimal | None
    total_cost: Decimal | None
    beta_before: float | None
    beta_after: float | None
    hedge_profit: Decimal | None
    notes: str


class HedgePositionRepository(Protocol):
    """Policy-owned hedge persistence boundary."""

    def create_hedge_position(
        self,
        *,
        portfolio_id: int,
        instrument_code: str,
        instrument_type: str,
        hedge_ratio: float,
        hedge_value: Decimal,
        policy_level: str,
        status: str,
        notes: str,
        execution_price: Decimal | None = None,
        opening_cost: Decimal | None = None,
        total_cost: Decimal | None = None,
        executed_at: datetime | None = None,
    ) -> Mapping[str, object]:
        """Create and return a hedge snapshot."""

    def get_hedge_position(
        self,
        *,
        hedge_id: int,
        portfolio_id: int,
    ) -> Mapping[str, object] | None:
        """Return one hedge scoped to a portfolio."""

    def update_beta_metrics(
        self,
        *,
        hedge_id: int,
        portfolio_id: int,
        beta_before: float,
        beta_after: float,
    ) -> bool:
        """Update beta metrics on a portfolio-scoped hedge."""


def list_portfolio_position_weights(portfolio_id: int) -> list[PositionWeight]:
    """Return position weights through the registered account repository."""

    repository = cast(AccountPositionRepository, _get_account_position_repository())
    return repository.list_portfolio_position_weights(portfolio_id)


class _AccountPositionRepository:
    """Typed adapter over the app-neutral account registry."""

    def _repository(self) -> AccountPositionRepository:
        return cast(AccountPositionRepository, _get_account_position_repository())

    def user_owns_portfolio(self, *, portfolio_id: int, user_id: int) -> bool:
        return self._repository().user_owns_portfolio(
            portfolio_id=portfolio_id,
            user_id=user_id,
        )

    def list_portfolio_position_weights(self, portfolio_id: int) -> list[PositionWeight]:
        return list_portfolio_position_weights(portfolio_id)


def get_account_position_repository() -> AccountPositionRepository:
    """Return the default typed account-position adapter."""

    return _AccountPositionRepository()


@dataclass(frozen=True)
class HedgeExecutionResult:
    """Persisted hedge execution result."""

    hedge_id: int
    instrument_code: str
    hedge_ratio: float
    hedge_value: Decimal
    execution_price: Decimal
    cost: Decimal
    executed_at: datetime


class CalculateHedgeUseCase:
    """Calculate policy hedging using externally supplied runtime configuration."""

    def __init__(self, config: HedgePolicyConfig) -> None:
        self.config = config

    def calculate_hedge_requirement(
        self,
        portfolio_id: int,
        policy_level: str,
        portfolio_value: Decimal,
        equity_exposure: Decimal,
    ) -> HedgeCalculationResult:
        """Validate inputs and delegate the financial rule to Domain."""

        if isinstance(portfolio_id, bool) or portfolio_id <= 0:
            raise ValueError("portfolio_id must be a positive integer")
        try:
            level = PolicyLevel(policy_level)
        except ValueError as exc:
            raise ValueError("unsupported policy level") from exc
        if level is PolicyLevel.PENDING:
            raise ValueError("pending policy level cannot drive hedging")
        return calculate_policy_hedge(
            policy_level=level,
            portfolio_value=portfolio_value,
            equity_exposure=equity_exposure,
            config=self.config,
        )


class ExecuteHedgingUseCase:
    """Execute a validated hedge for a portfolio owner."""

    def __init__(
        self,
        hedge_repository: HedgePositionRepository | None = None,
        account_position_repository: AccountPositionRepository | None = None,
        price_repository: RealtimePriceRepository | None = None,
    ) -> None:
        self.hedge_repository = hedge_repository or cast(
            HedgePositionRepository,
            get_hedge_position_repository(),
        )
        self.account_position_repository = (
            account_position_repository or get_account_position_repository()
        )
        self.price_repository = price_repository

    def execute_hedge(
        self,
        portfolio_id: int,
        user_id: int,
        calculation: HedgeCalculationResult,
    ) -> HedgeExecutionResult | None:
        """Persist an executed hedge only after ownership and price validation."""

        if isinstance(portfolio_id, bool) or portfolio_id <= 0:
            raise ValueError("portfolio_id must be a positive integer")
        if isinstance(user_id, bool) or user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        if not self.account_position_repository.user_owns_portfolio(
            portfolio_id=portfolio_id,
            user_id=user_id,
        ):
            raise PermissionError("portfolio is not owned by user")
        if not calculation.should_hedge:
            return None

        execution_price = self._get_instrument_price(calculation.recommended_instrument)
        executed_at = timezone.now()
        hedge = self.hedge_repository.create_hedge_position(
            portfolio_id=portfolio_id,
            instrument_code=calculation.recommended_instrument,
            instrument_type=calculation.instrument_type,
            hedge_ratio=calculation.hedge_ratio,
            hedge_value=calculation.hedge_value,
            policy_level=calculation.policy_level.value,
            status="executed",
            notes=calculation.reason,
            execution_price=execution_price,
            opening_cost=calculation.estimated_cost,
            total_cost=calculation.estimated_cost,
            executed_at=executed_at,
        )
        hedge_id = hedge.get("id")
        if isinstance(hedge_id, bool) or not isinstance(hedge_id, int) or hedge_id <= 0:
            raise RuntimeError("hedge repository returned an invalid identifier")

        return HedgeExecutionResult(
            hedge_id=hedge_id,
            instrument_code=calculation.recommended_instrument,
            hedge_ratio=calculation.hedge_ratio,
            hedge_value=calculation.hedge_value,
            execution_price=execution_price,
            cost=calculation.estimated_cost,
            executed_at=executed_at,
        )

    def _get_instrument_price(self, instrument_code: str) -> Decimal:
        """Return a finite positive execution price or fail closed."""

        if not instrument_code.strip():
            raise ValueError("hedge instrument code is required")
        try:
            repository = self.price_repository or cast(
                RealtimePriceRepository,
                get_realtime_price_repository(),
            )
            price_data = repository.get_latest_price(instrument_code)
            price = Decimal(str(price_data.price)) if price_data is not None else None
        except (InvalidOperation, TypeError, ValueError, RuntimeError) as exc:
            logger.warning("Hedge instrument price is unavailable", exc_info=True)
            raise RuntimeError("hedge instrument price is unavailable") from exc
        if price is None or not price.is_finite() or price <= 0:
            raise RuntimeError("hedge instrument price is unavailable")
        return price


class HedgeEffectivenessAnalyzer:
    """Analyze persisted hedge cost and estimated beta change."""

    def __init__(
        self,
        hedge_repository: HedgePositionRepository | None = None,
        account_position_repository: AccountPositionRepository | None = None,
    ) -> None:
        self.hedge_repository = hedge_repository or cast(
            HedgePositionRepository,
            get_hedge_position_repository(),
        )
        self.account_position_repository = (
            account_position_repository or get_account_position_repository()
        )

    def analyze_hedge_effectiveness(
        self,
        portfolio_id: int,
        hedge_id: int,
        user_id: int,
    ) -> dict[str, float | str | None]:
        """Return finite hedge metrics scoped to one portfolio."""

        if (
            isinstance(portfolio_id, bool)
            or portfolio_id <= 0
            or isinstance(hedge_id, bool)
            or hedge_id <= 0
            or isinstance(user_id, bool)
            or user_id <= 0
        ):
            raise ValueError("portfolio_id, hedge_id and user_id must be positive integers")
        if not self.account_position_repository.user_owns_portfolio(
            portfolio_id=portfolio_id,
            user_id=user_id,
        ):
            raise PermissionError("portfolio is not owned by user")
        hedge = self.hedge_repository.get_hedge_position(
            hedge_id=hedge_id,
            portfolio_id=portfolio_id,
        )
        if hedge is None:
            return {
                "error": "hedge position not found",
                "beta_before": None,
                "beta_after": None,
                "hedge_cost": 0.0,
                "hedge_benefit": 0.0,
                "net_benefit": 0.0,
            }

        opening_cost = self._non_negative_metric(hedge.get("opening_cost"), "opening_cost")
        closing_cost = self._non_negative_metric(hedge.get("closing_cost"), "closing_cost")
        total_cost = self._optional_non_negative_metric(hedge.get("total_cost"), "total_cost")
        if total_cost is None:
            total_cost = opening_cost + closing_cost
        hedge_profit = self._finite_metric(hedge.get("hedge_profit"), "hedge_profit")

        beta_before = self._optional_finite_metric(hedge.get("beta_before"), "beta_before")
        beta_after = self._optional_finite_metric(hedge.get("beta_after"), "beta_after")
        if beta_before is None or beta_after is None:
            beta_before, beta_after = self._compute_beta_change(portfolio_id, hedge)
            if not self.hedge_repository.update_beta_metrics(
                hedge_id=hedge_id,
                portfolio_id=portfolio_id,
                beta_before=beta_before,
                beta_after=beta_after,
            ):
                raise RuntimeError("hedge beta metrics could not be persisted")

        return {
            "beta_before": beta_before,
            "beta_after": beta_after,
            "hedge_cost": total_cost,
            "hedge_benefit": hedge_profit,
            "net_benefit": hedge_profit - total_cost,
        }

    def _compute_beta_change(
        self,
        portfolio_id: int,
        hedge: Mapping[str, object],
    ) -> tuple[float, float]:
        """Estimate beta change from the validated hedge ratio."""

        positions = self.account_position_repository.list_portfolio_position_weights(portfolio_id)
        if not positions:
            raise RuntimeError("portfolio positions are unavailable")
        hedge_ratio = safe_float(hedge.get("hedge_ratio"))
        if hedge_ratio is None or not 0.0 <= hedge_ratio <= 1.0:
            raise ValueError("hedge_ratio must be finite and in [0, 1]")
        return 1.0, max(0.0, 1.0 - hedge_ratio)

    @staticmethod
    def _finite_metric(value: object, name: str) -> float:
        if value is None:
            return 0.0
        parsed = safe_float(value)
        if parsed is None:
            raise ValueError(f"{name} must be finite")
        return parsed

    @staticmethod
    def _non_negative_metric(value: object, name: str) -> float:
        parsed = HedgeEffectivenessAnalyzer._finite_metric(value, name)
        if parsed < 0:
            raise ValueError(f"{name} must be non-negative")
        return parsed

    @staticmethod
    def _optional_finite_metric(value: object, name: str) -> float | None:
        if value is None:
            return None
        parsed = safe_float(value)
        if parsed is None:
            raise ValueError(f"{name} must be finite")
        return parsed

    @staticmethod
    def _optional_non_negative_metric(value: object, name: str) -> float | None:
        parsed = HedgeEffectivenessAnalyzer._optional_finite_metric(value, name)
        if parsed is not None and parsed < 0:
            raise ValueError(f"{name} must be non-negative")
        return parsed


__all__ = [
    "CalculateHedgeUseCase",
    "ExecuteHedgingUseCase",
    "HedgeCalculationResult",
    "HedgeEffectivenessAnalyzer",
    "HedgeExecutionResult",
    "HedgePolicyConfig",
]
