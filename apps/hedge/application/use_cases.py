"""
Hedge Module Application Layer - Use Cases

Application use cases for the hedge module.
Orchestrates domain services and infrastructure adapters.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Callable

from apps.hedge.domain.entities import HedgePair, HedgeAlert
from apps.hedge.domain.services import (
    HedgeContext,
    HedgePortfolioService,
    CorrelationMonitor,
)
from apps.hedge.application.dtos import (
    HedgeEffectivenessRequest,
    HedgeEffectivenessResponse,
    CorrelationMatrixRequest,
    CorrelationMatrixResponse,
    HedgeAlertResponse,
)


@dataclass
class HedgeUseCaseContext:
    """Context for hedge use case execution"""
    calc_date: date
    hedge_pairs: List[HedgePair]

    # Repository accessors (injected)
    get_asset_prices: Callable[[str, date, int], Optional[List[float]]]
    get_asset_name: Callable[[str], Optional[str]]
    get_hedge_pair: Callable[[str], Optional[HedgePair]]


class CheckHedgeEffectivenessUseCase:
    """
    Use case: Check hedge pair effectiveness.

    Returns effectiveness metrics and recommendations.
    """

    def __init__(self, context: HedgeUseCaseContext):
        self.context = context

    def execute(self, request: HedgeEffectivenessRequest) -> HedgeEffectivenessResponse:
        """Execute hedge effectiveness check"""
        # Get hedge pair
        pair = self.context.get_hedge_pair(request.pair_name)
        if not pair:
            raise ValueError(f"Hedge pair not found: {request.pair_name}")

        # Create domain context
        domain_context = HedgeContext(
            calc_date=self.context.calc_date,
            hedge_pairs=[pair],
            get_asset_prices=self.context.get_asset_prices,
            get_asset_name=self.context.get_asset_name,
        )

        # Create service and check effectiveness
        service = HedgePortfolioService(domain_context)
        effectiveness = service.check_hedge_effectiveness(pair)

        return HedgeEffectivenessResponse(
            pair_name=effectiveness["pair_name"],
            correlation=effectiveness["correlation"],
            beta=effectiveness["beta"],
            hedge_ratio=effectiveness["hedge_ratio"],
            hedge_method=effectiveness["hedge_method"],
            effectiveness=effectiveness["effectiveness"],
            rating=effectiveness["rating"],
            recommendation=effectiveness["recommendation"],
        )


class GetCorrelationMatrixUseCase:
    """
    Use case: Get correlation matrix for assets.

    Returns correlation matrix for specified assets.
    """

    def __init__(self, context: HedgeUseCaseContext):
        self.context = context

    def execute(self, request: CorrelationMatrixRequest) -> CorrelationMatrixResponse:
        """Execute correlation matrix calculation"""
        # Create domain context
        domain_context = HedgeContext(
            calc_date=self.context.calc_date,
            hedge_pairs=[],
            get_asset_prices=self.context.get_asset_prices,
            get_asset_name=self.context.get_asset_name,
        )

        # Create service and get matrix
        service = HedgePortfolioService(domain_context)
        matrix = service.get_correlation_matrix(
            request.asset_codes,
            request.window_days
        )

        return CorrelationMatrixResponse(
            matrix=matrix,
            calc_date=self.context.calc_date,
            window_days=request.window_days,
        )


class MonitorHedgeAlertsUseCase:
    """
    Use case: Monitor hedge pairs for alerts.

    Returns any alerts for hedge pairs.
    """

    def __init__(self, context: HedgeUseCaseContext):
        self.context = context

    def execute(self) -> List[HedgeAlertResponse]:
        """Execute hedge monitoring"""
        # Create domain context
        domain_context = HedgeContext(
            calc_date=self.context.calc_date,
            hedge_pairs=self.context.hedge_pairs,
            get_asset_prices=self.context.get_asset_prices,
            get_asset_name=self.context.get_asset_name,
        )

        # Create monitor and check for alerts
        monitor = CorrelationMonitor(domain_context)
        alerts = monitor.monitor_hedge_pairs()

        return [
            HedgeAlertResponse(
                pair_name=alert.pair_name,
                alert_date=alert.alert_date,
                alert_type=alert.alert_type.value,
                severity=alert.severity,
                message=alert.message,
                action_required=alert.action_required,
                priority=alert.action_priority,
            )
            for alert in alerts
        ]


class UpdateHedgePortfolioUseCase:
    """
    Use case: Update hedge portfolio state.

    Calculates current hedge ratios and portfolio state.
    """

    def __init__(self, context: HedgeUseCaseContext):
        self.context = context

    def execute(self, pair_name: str) -> Optional[Dict]:
        """Execute hedge portfolio update"""
        # Get hedge pair
        pair = self.context.get_hedge_pair(pair_name)
        if not pair:
            raise ValueError(f"Hedge pair not found: {pair_name}")

        # Create domain context
        domain_context = HedgeContext(
            calc_date=self.context.calc_date,
            hedge_pairs=[pair],
            get_asset_prices=self.context.get_asset_prices,
            get_asset_name=self.context.get_asset_name,
        )

        # Create service and update portfolio
        service = HedgePortfolioService(domain_context)
        portfolio = service.update_hedge_portfolio(pair)

        if portfolio is None:
            return None

        return {
            "pair_name": portfolio.pair_name,
            "trade_date": portfolio.trade_date,
            "long_weight": portfolio.long_weight,
            "hedge_weight": portfolio.hedge_weight,
            "hedge_ratio": portfolio.hedge_ratio,
            "current_correlation": portfolio.current_correlation,
            "portfolio_beta": portfolio.portfolio_beta,
            "hedge_effectiveness": portfolio.hedge_effectiveness,
            "rebalance_needed": portfolio.rebalance_needed,
            "rebalance_reason": portfolio.rebalance_reason,
        }
