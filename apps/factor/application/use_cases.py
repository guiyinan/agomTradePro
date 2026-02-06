"""
Factor Module Application Layer - Use Cases

Application use cases for the factor module.
Orchestrates domain services and infrastructure adapters.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Callable

from apps.factor.domain.entities import (
    FactorPortfolioConfig,
    FactorScore,
    FactorPortfolioHolding,
)
from apps.factor.domain.services import (
    FactorCalculationContext,
    FactorEngine,
    ScoringService,
)
from apps.factor.application.dtos import (
    FactorCalculationRequest,
    FactorScoreResponse,
    FactorPortfolioRequest,
    FactorPortfolioResponse,
)


@dataclass
class FactorUseCaseContext:
    """Context for use case execution"""
    trade_date: date
    universe: List[str]

    # Repository accessors (injected)
    get_factor_value: Callable[[str, str, date], Optional[float]]
    get_stock_info: Callable[[str], Optional[Dict]]
    get_factor_definitions: Callable[[], List]


class CalculateFactorScoresUseCase:
    """
    Use case: Calculate factor scores for stocks.

    Orchestrates domain services to calculate composite factor scores.
    """

    def __init__(self, context: FactorUseCaseContext):
        self.context = context

    def execute(self, request: FactorCalculationRequest) -> List[FactorScoreResponse]:
        """Execute factor score calculation"""
        # Get factor definitions
        factor_definitions = self.context.get_factor_definitions()

        # Create domain context
        domain_context = FactorCalculationContext(
            trade_date=request.trade_date,
            universe=request.universe,
            factor_definitions=factor_definitions,
            get_factor_value=self.context.get_factor_value,
            get_stock_info=self.context.get_stock_info,
        )

        # Create scoring service
        scoring_service = ScoringService(domain_context)

        # Calculate scores
        factor_weights = self._get_default_weights(request.factor_codes)
        scores = scoring_service.get_top_stocks(factor_weights, top_n=len(request.universe))

        # Convert to response DTOs
        return [
            FactorScoreResponse(
                stock_code=score.stock_code,
                stock_name=score.stock_name,
                composite_score=score.composite_score,
                percentile_rank=score.percentile_rank,
                factor_scores=score.factor_scores,
                sector=score.sector,
                market_cap=score.market_cap,
            )
            for score in scores
        ]

    def _get_default_weights(self, factor_codes: List[str]) -> Dict[str, float]:
        """Get default equal weights for factors"""
        n = len(factor_codes)
        return {code: 1.0 / n for code in factor_codes}


class CreateFactorPortfolioUseCase:
    """
    Use case: Create a factor-based portfolio.

    Selects top stocks based on factor scores and creates portfolio.
    """

    def __init__(self, context: FactorUseCaseContext):
        self.context = context

    def execute(self, request: FactorPortfolioRequest) -> FactorPortfolioResponse:
        """Execute portfolio creation"""
        # Get configuration
        # For now, use default config
        from apps.factor.domain.entities import create_default_factor_config

        config = create_default_factor_config()

        # Get factor definitions
        factor_definitions = self.context.get_factor_definitions()

        # Create domain context
        domain_context = FactorCalculationContext(
            trade_date=request.trade_date,
            universe=self.context.universe,
            factor_definitions=factor_definitions,
            get_factor_value=self.context.get_factor_value,
            get_stock_info=self.context.get_stock_info,
        )

        # Create engine and select portfolio
        engine = FactorEngine(domain_context)
        holdings = engine.select_portfolio(config)

        # Convert to response DTO
        return FactorPortfolioResponse(
            config_name=request.config_name,
            trade_date=request.trade_date,
            holdings=[
                {
                    "stock_code": h.stock_code,
                    "stock_name": h.stock_name,
                    "weight": h.weight,
                    "factor_score": h.factor_score,
                    "rank": h.rank,
                }
                for h in holdings
            ],
            total_weight=sum(h.weight for h in holdings),
        )


class GetTopStocksUseCase:
    """
    Use case: Get top N stocks by factor score.

    Simple query use case for getting top stocks.
    """

    def __init__(self, context: FactorUseCaseContext):
        self.context = context

    def execute(
        self,
        factor_weights: Dict[str, float],
        top_n: int = 30
    ) -> List[FactorScoreResponse]:
        """Execute top stocks query"""
        # Get factor definitions
        factor_definitions = self.context.get_factor_definitions()

        # Create domain context
        domain_context = FactorCalculationContext(
            trade_date=self.context.trade_date,
            universe=self.context.universe,
            factor_definitions=factor_definitions,
            get_factor_value=self.context.get_factor_value,
            get_stock_info=self.context.get_stock_info,
        )

        # Create scoring service
        scoring_service = ScoringService(domain_context)

        # Get top stocks
        scores = scoring_service.get_top_stocks(factor_weights, top_n)

        # Convert to response DTOs
        return [
            FactorScoreResponse(
                stock_code=score.stock_code,
                stock_name=score.stock_name,
                composite_score=score.composite_score,
                percentile_rank=score.percentile_rank,
                factor_scores=score.factor_scores,
                sector=score.sector,
                market_cap=score.market_cap,
            )
            for score in scores
        ]
