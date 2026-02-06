"""
Factor Module Infrastructure Layer - Integration Services

Integration services that connect domain logic with data adapters.
"""

from datetime import date, datetime
from typing import Dict, List, Optional, Callable
import logging

from apps.factor.domain.entities import (
    FactorDefinition,
    FactorScore,
    FactorPortfolioConfig,
    FactorPortfolioHolding,
)
from apps.factor.domain.services import (
    FactorCalculationContext,
    FactorEngine,
    ScoringService,
)
from apps.factor.infrastructure.repositories import (
    FactorDefinitionRepository,
    FactorPortfolioConfigRepository,
    FactorPortfolioHoldingRepository,
)
from apps.factor.infrastructure.adapters import FailoverFactorAdapter

logger = logging.getLogger(__name__)


class FactorIntegrationService:
    """
    High-level service for factor operations.

    Integrates domain services with repositories and data adapters.
    """

    def __init__(self, factor_adapter=None):
        self.factor_adapter = factor_adapter or FailoverFactorAdapter()
        self.factor_repo = FactorDefinitionRepository()
        self.config_repo = FactorPortfolioConfigRepository()
        self.holding_repo = FactorPortfolioHoldingRepository()

    def calculate_factor_scores(
        self,
        universe: List[str],
        factor_weights: Dict[str, float],
        trade_date: Optional[date] = None,
        top_n: int = 50
    ) -> List[Dict]:
        """
        Calculate factor scores for stocks.

        Args:
            universe: List of stock codes
            factor_weights: Factor weights dictionary
            trade_date: Calculation date
            top_n: Number of top stocks to return

        Returns:
            List of factor score dictionaries
        """
        trade_date = trade_date or date.today()

        # Get factor definitions
        factor_definitions = self.factor_repo.get_active()

        # Create domain context
        def get_factor_value(stock_code: str, factor_code: str, calc_date: date) -> Optional[float]:
            return self.factor_adapter.get_factor_value(stock_code, factor_code, calc_date)

        def get_stock_info(stock_code: str) -> Optional[Dict]:
            # Get stock info from equity module if available
            try:
                from apps.equity.infrastructure.repositories import StockInfoRepository
                equity_repo = StockInfoRepository()
                stock = equity_repo.get_by_code(stock_code)
                if stock:
                    return {
                        'name': stock.name,
                        'sector': stock.sector,
                        'market_cap': stock.list_date,  # Placeholder
                    }
            except Exception:
                pass

            # Fallback to basic info
            return {
                'name': stock_code,
                'sector': 'Unknown',
                'market_cap': None,
            }

        context = FactorCalculationContext(
            trade_date=trade_date,
            universe=universe,
            factor_definitions=factor_definitions,
            get_factor_value=get_factor_value,
            get_stock_info=get_stock_info,
        )

        # Create scoring service
        scoring_service = ScoringService(context)

        # Calculate scores
        scores = scoring_service.get_top_stocks(factor_weights, top_n)

        # Convert to dictionaries
        return [
            {
                'stock_code': score.stock_code,
                'stock_name': score.stock_name,
                'composite_score': round(score.composite_score, 2),
                'percentile_rank': round(score.percentile_rank, 4),
                'factor_scores': {k: round(v, 2) for k, v in score.factor_scores.items()},
                'sector': score.sector,
                'style': score.style,
                'size': score.size,
                'valuation_score': round(score.valuation_score, 2),
                'quality_score': round(score.quality_score, 2),
                'growth_score': round(score.growth_score, 2),
                'momentum_score': round(score.momentum_score, 2),
            }
            for score in scores
        ]

    def create_factor_portfolio(
        self,
        config_name: str,
        trade_date: Optional[date] = None
    ) -> Optional[Dict]:
        """
        Create factor portfolio based on configuration.

        Args:
            config_name: Configuration name
            trade_date: Trade date

        Returns:
            Portfolio summary
        """
        trade_date = trade_date or date.today()

        # Get configuration
        config = self.config_repo.get_by_name(config_name)
        if not config:
            logger.error(f"Configuration not found: {config_name}")
            return None

        # Determine universe
        universe = self._get_universe_stocks(config.universe)

        # Calculate scores
        scores = self.calculate_factor_scores(
            universe,
            config.factor_weights,
            trade_date,
            config.top_n
        )

        if not scores:
            return None

        # Select top N
        top_scores = scores[:config.top_n]

        # Calculate weights
        holdings = self._create_holdings_from_scores(
            config_name,
            trade_date,
            top_scores,
            config.weight_method
        )

        # Save holdings
        self.holding_repo.save_holdings(config_name, trade_date, holdings)

        return {
            'config_name': config_name,
            'trade_date': trade_date.isoformat(),
            'total_stocks': len(holdings),
            'holdings': [
                {
                    'stock_code': h.stock_code,
                    'stock_name': h.stock_name,
                    'weight': round(h.weight * 100, 2),
                    'factor_score': round(h.factor_score, 2),
                    'rank': h.rank,
                    'sector': h.sector,
                }
                for h in holdings
            ],
        }

    def get_factor_portfolio(self, config_name: str) -> Optional[Dict]:
        """
        Get latest factor portfolio for a configuration.

        Args:
            config_name: Configuration name

        Returns:
            Portfolio summary
        """
        holdings = self.holding_repo.get_latest_holdings(config_name)

        if not holdings:
            return None

        return {
            'config_name': config_name,
            'trade_date': holdings[0].trade_date.isoformat() if holdings else '',
            'total_stocks': len(holdings),
            'holdings': [
                {
                    'stock_code': h.stock_code,
                    'stock_name': h.stock_name,
                    'weight': round(h.weight * 100, 2),
                    'factor_score': round(h.factor_score, 2),
                    'rank': h.rank,
                    'sector': h.sector,
                }
                for h in holdings
            ],
        }

    def explain_stock_score(
        self,
        stock_code: str,
        factor_weights: Dict[str, float],
        trade_date: Optional[date] = None
    ) -> Optional[Dict]:
        """
        Explain factor score breakdown for a stock.

        Args:
            stock_code: Stock code
            factor_weights: Factor weights
            trade_date: Calculation date

        Returns:
            Score breakdown
        """
        trade_date = trade_date or date.today()

        # Get factor definitions
        factor_definitions = self.factor_repo.get_active()

        # Create domain context
        def get_factor_value(stock_code: str, factor_code: str, calc_date: date) -> Optional[float]:
            return self.factor_adapter.get_factor_value(stock_code, factor_code, calc_date)

        def get_stock_info(stock_code: str) -> Optional[Dict]:
            try:
                from apps.equity.infrastructure.repositories import StockInfoRepository
                equity_repo = StockInfoRepository()
                stock = equity_repo.get_by_code(stock_code)
                if stock:
                    return {
                        'name': stock.name,
                        'sector': stock.sector,
                        'market_cap': stock.list_date,
                    }
            except Exception:
                pass
            return None

        context = FactorCalculationContext(
            trade_date=trade_date,
            universe=[stock_code],
            factor_definitions=factor_definitions,
            get_factor_value=get_factor_value,
            get_stock_info=get_stock_info,
        )

        scoring_service = ScoringService(context)
        explanation = scoring_service.explain_stock_score(stock_code, factor_weights)

        return explanation

    def _get_universe_stocks(self, universe: str) -> List[str]:
        """Get stock list for a universe"""
        # Map universe codes to actual stock lists
        from apps.equity.infrastructure.repositories import StockInfoRepository

        equity_repo = StockInfoRepository()

        if universe == 'hs300':
            # Return沪深300 component stocks
            # For now, return all stocks with market cap > 50 billion
            all_stocks = equity_repo.get_all()
            return [s.stock_code for s in all_stocks if s.market_cap and s.market_cap > 50000000000]
        elif universe == 'zz500':
            # 中证500 - mid cap
            all_stocks = equity_repo.get_all()
            return [s.stock_code for s in all_stocks if s.market_cap and 5000000000 < s.market_cap < 50000000000]
        elif universe == 'all_a':
            # All A-shares
            all_stocks = equity_repo.get_all()
            return [s.stock_code for s in all_stocks]
        else:
            # Default to all stocks
            all_stocks = equity_repo.get_all()
            return [s.stock_code for s in all_stocks]

    def _create_holdings_from_scores(
        self,
        config_name: str,
        trade_date: date,
        scores: List[Dict],
        weight_method: str
    ) -> List[FactorPortfolioHolding]:
        """Create holdings from scores"""
        n = len(scores)
        holdings = []

        if weight_method == 'equal_weight':
            weight = 1.0 / n
            for i, score in enumerate(scores):
                holdings.append(FactorPortfolioHolding(
                    config_name=config_name,
                    trade_date=trade_date,
                    stock_code=score['stock_code'],
                    stock_name=score['stock_name'],
                    weight=weight,
                    factor_score=score['composite_score'],
                    rank=i + 1,
                    sector=score['sector'],
                    factor_scores=score['factor_scores'],
                ))

        elif weight_method == 'factor_weighted':
            total_score = sum(s['composite_score'] for s in scores)
            for i, score in enumerate(scores):
                weight = score['composite_score'] / total_score if total_score > 0 else 1.0 / n
                holdings.append(FactorPortfolioHolding(
                    config_name=config_name,
                    trade_date=trade_date,
                    stock_code=score['stock_code'],
                    stock_name=score['stock_name'],
                    weight=weight,
                    factor_score=score['composite_score'],
                    rank=i + 1,
                    sector=score['sector'],
                    factor_scores=score['factor_scores'],
                ))

        else:  # Default to equal weight
            weight = 1.0 / n
            for i, score in enumerate(scores):
                holdings.append(FactorPortfolioHolding(
                    config_name=config_name,
                    trade_date=trade_date,
                    stock_code=score['stock_code'],
                    stock_name=score['stock_name'],
                    weight=weight,
                    factor_score=score['composite_score'],
                    rank=i + 1,
                    sector=score['sector'],
                    factor_scores=score['factor_scores'],
                ))

        return holdings

    def get_factor_definitions(self) -> List[Dict]:
        """Get all factor definitions"""
        factors = self.factor_repo.get_active()

        return [
            {
                'code': f.code,
                'name': f.name,
                'category': f.category.value,
                'description': f.description,
                'data_source': f.data_source,
                'direction': f.direction.value,
                'is_active': f.is_active,
            }
            for f in factors
        ]

    def get_all_configs(self) -> List[Dict]:
        """Get all portfolio configurations"""
        configs = self.config_repo.get_all()

        return [
            {
                'name': c.name,
                'description': c.description,
                'factor_weights': c.factor_weights,
                'universe': c.universe,
                'top_n': c.top_n,
                'rebalance_frequency': c.rebalance_frequency,
                'weight_method': c.weight_method,
                'is_active': c.is_active,
            }
            for c in configs
        ]

    def get_top_stocks(
        self,
        factor_preferences: Dict[str, str],
        top_n: int = 30
    ) -> List[Dict]:
        """
        Get top stocks based on factor preferences.

        Args:
            factor_preferences: Factor preference settings
                e.g., {'value': 'high', 'quality': 'high', 'growth': 'medium'}
            top_n: Number of stocks to return

        Returns:
            Top stocks list
        """
        # Build factor weights from preferences
        factor_weights = {}

        # Get all active factors
        all_factors = self.factor_repo.get_active()

        for factor in all_factors:
            category = factor.category.value
            preference = factor_preferences.get(category, 'medium')

            if preference == 'high':
                # Positive weight
                base_weight = 0.2
            elif preference == 'low':
                # Negative weight
                base_weight = -0.1
            else:
                # Neutral/medium
                base_weight = 0.0

            if factor.direction.value == 'negative':
                factor_weights[factor.code] = -base_weight
            else:
                factor_weights[factor.code] = base_weight

        # Normalize weights
        total_weight = sum(abs(w) for w in factor_weights.values())
        if total_weight > 0:
            factor_weights = {k: abs(v) / total_weight for k, v in factor_weights.items()}

        # Get universe
        universe = self._get_universe_stocks('all_a')

        # Calculate scores
        scores = self.calculate_factor_scores(
            universe,
            factor_weights,
            top_n=top_n
        )

        return scores[:top_n]
