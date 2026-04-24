"""
Factor Module Application Layer - Use Cases

Application use cases for the factor module.
Orchestrates domain services and infrastructure adapters.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from apps.factor.application.dtos import (
    FactorCalculationRequest,
    FactorPortfolioRequest,
    FactorPortfolioResponse,
    FactorScoreResponse,
)
from apps.factor.domain.entities import (
    FactorPortfolioConfig,
    FactorPortfolioHolding,
    FactorScore,
)
from apps.factor.domain.services import (
    FactorCalculationContext,
    FactorEngine,
    ScoringService,
)


@dataclass
class FactorUseCaseContext:
    """Context for use case execution"""
    trade_date: date
    universe: list[str]

    # Repository accessors (injected)
    get_factor_value: Callable[[str, str, date], float | None]
    get_stock_info: Callable[[str], dict | None]
    get_factor_definitions: Callable[[], list]


class CalculateFactorScoresUseCase:
    """
    Use case: Calculate factor scores for stocks.

    Orchestrates domain services to calculate composite factor scores.
    """

    def __init__(self, context: FactorUseCaseContext):
        self.context = context

    def execute(self, request: FactorCalculationRequest) -> list[FactorScoreResponse]:
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

    def _get_default_weights(self, factor_codes: list[str]) -> dict[str, float]:
        """Get default equal weights for factors"""
        n = len(factor_codes)
        return dict.fromkeys(factor_codes, 1.0 / n)


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
        factor_weights: dict[str, float],
        top_n: int = 30
    ) -> list[FactorScoreResponse]:
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


# ============================================================================
# View Management UseCases
# ============================================================================

@dataclass
class FactorListViewRequest:
    """Request for listing factor definitions"""
    category: str | None = None
    is_active: bool | None = None
    search: str | None = None


@dataclass
class FactorListViewResponse:
    """Response for factor list view"""
    factors: list[Any]
    stats: dict
    categories: list[dict]
    category_choices: dict


@dataclass
class PortfolioListViewRequest:
    """Request for listing portfolio configurations"""
    is_active: bool | None = None
    search: str | None = None


@dataclass
class PortfolioListViewResponse:
    """Response for portfolio list view"""
    configs: list[Any]
    stats: dict
    factor_definitions: list[Any]
    universe_choices: dict
    weight_method_choices: dict
    rebalance_choices: dict


@dataclass
class FactorCalculateViewRequest:
    """Request for factor calculation view"""
    trade_date: date
    top_n: int = 30
    config_id: int | None = None


@dataclass
class FactorCalculateViewResponse:
    """Response for factor calculation view"""
    configs: list[Any]
    factors: list[Any]
    factors_by_category: dict
    category_choices: dict
    selected_config: Any | None
    calculated_results: dict | None
    trade_date: date
    top_n: int
    config_id: int | None


@dataclass
class CreatePortfolioConfigRequest:
    """Request for creating portfolio configuration"""
    name: str
    description: str
    universe: str
    top_n: int
    rebalance_frequency: str
    weight_method: str
    factor_weights: dict[str, float]
    min_market_cap: float | None = None
    max_market_cap: float | None = None
    max_pe: float | None = None
    max_pb: float | None = None
    max_debt_ratio: float | None = None


@dataclass
class CreatePortfolioConfigResponse:
    """Response for creating portfolio configuration"""
    success: bool
    config_id: int | None = None
    message: str | None = None
    error: str | None = None


@dataclass
class PortfolioConfigActionRequest:
    """Request for portfolio config actions"""
    config_id: int
    action_type: str  # 'activate', 'deactivate', 'generate'


@dataclass
class CalculateScoresRequest:
    """Request for calculating factor scores"""
    config_id: int
    top_n: int = 30
    trade_date: date = None


@dataclass
class CalculateScoresResponse:
    """Response for calculating factor scores"""
    success: bool
    total_scores: int | None = None
    scores: list[dict] | None = None
    message: str | None = None
    error: str | None = None


class GetFactorDefinitionsForViewUseCase:
    """UseCase for factor management page"""

    def __init__(self, factor_repo):
        self.factor_repo = factor_repo

    def execute(self, request: FactorListViewRequest) -> FactorListViewResponse:
        """Get factor definitions with filters for the view"""
        factors = self.factor_repo.list_models_for_view(
            category=request.category,
            is_active=request.is_active,
            search=request.search,
        )

        return FactorListViewResponse(
            factors=factors,
            stats=self.factor_repo.get_view_stats(),
            categories=self.factor_repo.list_category_rows(),
            category_choices=self.factor_repo.get_category_choices(),
        )


class GetPortfolioConfigsForViewUseCase:
    """UseCase for portfolio configuration management page"""

    def __init__(self, factor_repo, portfolio_repo):
        self.factor_repo = factor_repo
        self.portfolio_repo = portfolio_repo

    def execute(self, request: PortfolioListViewRequest) -> PortfolioListViewResponse:
        """Get portfolio configurations with filters for the view"""
        configs = self.portfolio_repo.list_models_for_view(
            is_active=request.is_active,
            search=request.search,
        )

        # Universe choices
        universe_choices = {
            'all_a': '全A',
            'csi_300': '沪深300',
            'csi_500': '中证500',
            'csi_1000': '中证1000',
            'star_50': '科创板50',
        }

        # Weight method choices
        weight_method_choices = {
            'equal_weight': '等权重',
            'market_cap_weight': '市值加权',
            'factor_score_weight': '因子得分加权',
        }

        # Rebalance frequency choices
        rebalance_choices = {
            'daily': '每日',
            'weekly': '每周',
            'monthly': '每月',
            'quarterly': '每季度',
        }

        return PortfolioListViewResponse(
            configs=configs,
            stats=self.portfolio_repo.get_view_stats(),
            factor_definitions=self.factor_repo.list_active_models(),
            universe_choices=universe_choices,
            weight_method_choices=weight_method_choices,
            rebalance_choices=rebalance_choices,
        )


class GetFactorCalculationDataUseCase:
    """UseCase for factor calculation page"""

    def __init__(self, portfolio_repo, factor_repo):
        self.portfolio_repo = portfolio_repo
        self.factor_repo = factor_repo

    def execute(self, request: FactorCalculateViewRequest) -> FactorCalculateViewResponse:
        """Get calculation page data"""
        configs = self.portfolio_repo.list_active_models()
        factors = self.factor_repo.list_active_models()

        # Group factors by category
        factors_by_category = {}
        for factor in factors:
            category_display = factor.get_category_display()
            if category_display not in factors_by_category:
                factors_by_category[category_display] = []
            factors_by_category[category_display].append(factor)

        # Selected config
        selected_config = None
        calculated_results = None

        if request.config_id:
            selected_config, calculated_results = (
                self.portfolio_repo.get_latest_calculation_results(
                    config_id=request.config_id,
                    top_n=request.top_n,
                )
            )

        return FactorCalculateViewResponse(
            configs=configs,
            factors=factors,
            factors_by_category=factors_by_category,
            category_choices=self.factor_repo.get_category_choices(),
            selected_config=selected_config,
            calculated_results=calculated_results,
            trade_date=request.trade_date,
            top_n=request.top_n,
            config_id=request.config_id,
        )


class CreatePortfolioConfigUseCase:
    """UseCase for creating a portfolio configuration"""

    def __init__(self, portfolio_repo):
        self.portfolio_repo = portfolio_repo

    def execute(self, request: CreatePortfolioConfigRequest) -> CreatePortfolioConfigResponse:
        """Create a new portfolio configuration"""
        try:
            if not request.name:
                return CreatePortfolioConfigResponse(
                    success=False,
                    error='配置名称不能为空'
                )

            # Create config using repository
            config_entity = FactorPortfolioConfig(
                name=request.name,
                description=request.description,
                factor_weights=request.factor_weights,
                universe=request.universe,
                top_n=request.top_n,
                rebalance_frequency=request.rebalance_frequency,
                weight_method=request.weight_method,
                min_market_cap=request.min_market_cap,
                max_market_cap=request.max_market_cap,
                max_pe=request.max_pe,
                max_pb=request.max_pb,
                max_debt_ratio=request.max_debt_ratio,
                is_active=True,
            )

            model = self.portfolio_repo.save(config_entity)

            return CreatePortfolioConfigResponse(
                success=True,
                config_id=model.id,
                message=f'组合配置 "{request.name}" 创建成功'
            )

        except Exception as e:
            return CreatePortfolioConfigResponse(
                success=False,
                error=str(e)
            )


class UpdatePortfolioConfigUseCase:
    """UseCase for updating a portfolio configuration (activate/deactivate/generate)"""

    def __init__(self, portfolio_repo, integration_service=None):
        self.portfolio_repo = portfolio_repo
        self.integration_service = integration_service

    def execute(self, request: PortfolioConfigActionRequest) -> dict:
        """Execute portfolio config action"""
        try:
            if request.action_type == 'activate':
                config = self.portfolio_repo.set_active(request.config_id, True)
                if config is None:
                    return {
                        'success': False,
                        'error': '配置不存在'
                    }
                return {
                    'success': True,
                    'message': f'组合配置 "{config.name}" 已启用'
                }

            elif request.action_type == 'deactivate':
                config = self.portfolio_repo.set_active(request.config_id, False)
                if config is None:
                    return {
                        'success': False,
                        'error': '配置不存在'
                    }
                return {
                    'success': True,
                    'message': f'组合配置 "{config.name}" 已禁用'
                }

            elif request.action_type == 'generate':
                config = self.portfolio_repo.get_model_by_id(request.config_id)
                if config is None:
                    return {
                        'success': False,
                        'error': '配置不存在'
                    }
                if self.integration_service:
                    portfolio = self.integration_service.create_factor_portfolio(config.name)

                    if portfolio:
                        return {
                            'success': True,
                            'message': f'组合 "{config.name}" 已生成',
                            'portfolio': portfolio
                        }
                    else:
                        return {
                            'success': False,
                            'error': '生成组合失败'
                        }
                else:
                    return {
                        'success': False,
                        'error': 'Integration service not available'
                    }

            else:
                return {
                    'success': False,
                    'error': 'Unknown action'
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


class CalculateScoresUseCase:
    """UseCase for calculating factor scores"""

    def __init__(self, integration_service, portfolio_repo=None):
        self.integration_service = integration_service
        if portfolio_repo is None:
            from apps.factor.infrastructure.repositories import FactorPortfolioConfigRepository

            portfolio_repo = FactorPortfolioConfigRepository()
        self.portfolio_repo = portfolio_repo

    def execute(self, request: CalculateScoresRequest) -> CalculateScoresResponse:
        """Calculate factor scores for a portfolio configuration"""
        try:
            if not request.config_id:
                return CalculateScoresResponse(
                    success=False,
                    error='请选择组合配置'
                )

            config = self.portfolio_repo.get_model_by_id(request.config_id)
            if config is None:
                return CalculateScoresResponse(
                    success=False,
                    error='配置不存在'
                )

            # Get factor weights from config
            factor_weights = config.factor_weights or {}

            universe = self.integration_service.resolve_universe_stocks(config.universe)

            # Calculate scores
            trade_date = request.trade_date or date.today()
            scores = self.integration_service.calculate_factor_scores(
                universe=universe,
                factor_weights=factor_weights,
                trade_date=trade_date,
                top_n=request.top_n,
            )

            return CalculateScoresResponse(
                success=True,
                total_scores=len(scores),
                scores=scores,
                message=f'计算完成，共 {len(scores)} 只股票'
            )

        except Exception as e:
            return CalculateScoresResponse(
                success=False,
                error=str(e)
            )
