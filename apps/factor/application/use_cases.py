"""
Factor Module Application Layer - Use Cases

Application use cases for the factor module.
Orchestrates domain services and infrastructure adapters.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Callable, Any

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


# ============================================================================
# View Management UseCases
# ============================================================================

@dataclass
class FactorListViewRequest:
    """Request for listing factor definitions"""
    category: Optional[str] = None
    is_active: Optional[bool] = None
    search: Optional[str] = None


@dataclass
class FactorListViewResponse:
    """Response for factor list view"""
    factors: List[Any]
    stats: Dict
    categories: List[Dict]
    category_choices: Dict


@dataclass
class PortfolioListViewRequest:
    """Request for listing portfolio configurations"""
    is_active: Optional[bool] = None
    search: Optional[str] = None


@dataclass
class PortfolioListViewResponse:
    """Response for portfolio list view"""
    configs: List[Any]
    stats: Dict
    factor_definitions: List[Any]
    universe_choices: Dict
    weight_method_choices: Dict
    rebalance_choices: Dict


@dataclass
class FactorCalculateViewRequest:
    """Request for factor calculation view"""
    trade_date: date
    top_n: int = 30
    config_id: Optional[int] = None


@dataclass
class FactorCalculateViewResponse:
    """Response for factor calculation view"""
    configs: List[Any]
    factors: List[Any]
    factors_by_category: Dict
    category_choices: Dict
    selected_config: Optional[Any]
    calculated_results: Optional[Dict]
    trade_date: date
    top_n: int
    config_id: Optional[int]


@dataclass
class CreatePortfolioConfigRequest:
    """Request for creating portfolio configuration"""
    name: str
    description: str
    universe: str
    top_n: int
    rebalance_frequency: str
    weight_method: str
    factor_weights: Dict[str, float]
    min_market_cap: Optional[float] = None
    max_market_cap: Optional[float] = None
    max_pe: Optional[float] = None
    max_pb: Optional[float] = None
    max_debt_ratio: Optional[float] = None


@dataclass
class CreatePortfolioConfigResponse:
    """Response for creating portfolio configuration"""
    success: bool
    config_id: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


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
    total_scores: Optional[int] = None
    scores: Optional[List[Dict]] = None
    message: Optional[str] = None
    error: Optional[str] = None


class GetFactorDefinitionsForViewUseCase:
    """UseCase for factor management page"""

    def __init__(self, factor_repo):
        self.factor_repo = factor_repo

    def execute(self, request: FactorListViewRequest) -> FactorListViewResponse:
        """Get factor definitions with filters for the view"""
        from apps.factor.infrastructure.models import FactorDefinitionModel
        from django.db.models import Count, Q

        # Base queryset
        queryset = FactorDefinitionModel._default_manager.all()

        # Apply filters
        if request.category:
            queryset = queryset.filter(category=request.category)
        if request.is_active is not None:
            queryset = queryset.filter(is_active=request.is_active)
        if request.search:
            queryset = queryset.filter(
                Q(code__icontains=request.search) |
                Q(name__icontains=request.search) |
                Q(description__icontains=request.search)
            )

        # Get factor list
        factors = list(queryset.order_by('category', 'code'))

        # Statistics
        stats = {
            'total': FactorDefinitionModel._default_manager.count(),
            'active': FactorDefinitionModel._default_manager.filter(is_active=True).count(),
            'by_category': dict(
                FactorDefinitionModel._default_manager.values('category')
                .annotate(count=Count('id'))
                .values_list('category', 'count')
            )
        }

        # Get all categories
        categories = list(
            FactorDefinitionModel._default_manager.values('category')
            .distinct()
        )
        category_choices = dict(
            FactorDefinitionModel._default_manager.model._meta.get_field('category').choices
        )

        return FactorListViewResponse(
            factors=factors,
            stats=stats,
            categories=categories,
            category_choices=category_choices,
        )


class GetPortfolioConfigsForViewUseCase:
    """UseCase for portfolio configuration management page"""

    def __init__(self, factor_repo, portfolio_repo):
        self.factor_repo = factor_repo
        self.portfolio_repo = portfolio_repo

    def execute(self, request: PortfolioListViewRequest) -> PortfolioListViewResponse:
        """Get portfolio configurations with filters for the view"""
        from apps.factor.infrastructure.models import (
            FactorPortfolioConfigModel,
            FactorDefinitionModel,
        )
        from django.db.models import Q

        # Base queryset
        queryset = FactorPortfolioConfigModel._default_manager.all()

        # Apply filters
        if request.is_active is not None:
            queryset = queryset.filter(is_active=request.is_active)
        if request.search:
            queryset = queryset.filter(
                Q(name__icontains=request.search) |
                Q(description__icontains=request.search)
            )

        # Get portfolio configurations
        configs = list(queryset.order_by('-is_active', '-created_at'))

        # For each config, get the latest holdings count
        for config in configs:
            latest_holding = config.holdings.order_by('-trade_date').first()
            config.latest_trade_date = latest_holding.trade_date if latest_holding else None
            config.holdings_count = (
                config.holdings.filter(trade_date=latest_holding.trade_date).count()
                if latest_holding else 0
            )

        # Statistics
        stats = {
            'total': FactorPortfolioConfigModel._default_manager.count(),
            'active': FactorPortfolioConfigModel._default_manager.filter(is_active=True).count(),
        }

        # Get available factor definitions for creating new config
        factor_definitions = list(
            FactorDefinitionModel._default_manager.filter(is_active=True)
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
            stats=stats,
            factor_definitions=factor_definitions,
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
        from apps.factor.infrastructure.models import (
            FactorPortfolioConfigModel,
            FactorDefinitionModel,
            FactorPortfolioHoldingModel,
        )

        # Get available portfolio configurations
        configs = list(
            FactorPortfolioConfigModel._default_manager.filter(is_active=True)
        )

        # Get available factor definitions
        factors = list(
            FactorDefinitionModel._default_manager.filter(is_active=True)
        )

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
            try:
                selected_config = FactorPortfolioConfigModel._default_manager.get(
                    id=request.config_id
                )

                # Get latest holdings for this config
                latest_holding = FactorPortfolioHoldingModel._default_manager.filter(
                    config=selected_config
                ).order_by('-trade_date').first()

                if latest_holding:
                    # Get holdings for this trade date
                    holdings = FactorPortfolioHoldingModel._default_manager.filter(
                        config=selected_config,
                        trade_date=latest_holding.trade_date
                    ).order_by('rank')[:request.top_n]

                    calculated_results = {
                        'trade_date': latest_holding.trade_date,
                        'total_stocks': holdings.count(),
                        'holdings': holdings,
                        'config_name': selected_config.name,
                        'top_n': request.top_n,
                    }
            except FactorPortfolioConfigModel.DoesNotExist:
                pass

        # Category choices for display
        category_choices = dict(
            FactorDefinitionModel._default_manager.model._meta.get_field('category').choices
        )

        return FactorCalculateViewResponse(
            configs=configs,
            factors=factors,
            factors_by_category=factors_by_category,
            category_choices=category_choices,
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
        from apps.factor.infrastructure.models import FactorPortfolioConfigModel

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

    def execute(self, request: PortfolioConfigActionRequest) -> Dict:
        """Execute portfolio config action"""
        from apps.factor.infrastructure.models import FactorPortfolioConfigModel

        try:
            config = FactorPortfolioConfigModel._default_manager.get(id=request.config_id)

            if request.action_type == 'activate':
                config.is_active = True
                config.save()
                return {
                    'success': True,
                    'message': f'组合配置 "{config.name}" 已启用'
                }

            elif request.action_type == 'deactivate':
                config.is_active = False
                config.save()
                return {
                    'success': True,
                    'message': f'组合配置 "{config.name}" 已禁用'
                }

            elif request.action_type == 'generate':
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

        except FactorPortfolioConfigModel.DoesNotExist:
            return {
                'success': False,
                'error': '配置不存在'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


class CalculateScoresUseCase:
    """UseCase for calculating factor scores"""

    def __init__(self, integration_service):
        self.integration_service = integration_service

    def execute(self, request: CalculateScoresRequest) -> CalculateScoresResponse:
        """Calculate factor scores for a portfolio configuration"""
        from apps.factor.infrastructure.models import FactorPortfolioConfigModel

        try:
            if not request.config_id:
                return CalculateScoresResponse(
                    success=False,
                    error='请选择组合配置'
                )

            config = FactorPortfolioConfigModel._default_manager.get(id=request.config_id)

            # Get factor weights from config
            factor_weights = config.factor_weights or {}

            # Get universe
            universe = []
            if config.universe == 'csi_300':
                universe = ['000001.SH', '399001.SZ']  # Simplified
            elif config.universe == 'all_a':
                universe = []  # Empty means all

            # Calculate scores
            trade_date = request.trade_date or date.today()
            scores = self.integration_service.calculate_factor_scores(
                universe=universe if universe else None,
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

        except FactorPortfolioConfigModel.DoesNotExist:
            return CalculateScoresResponse(
                success=False,
                error='配置不存在'
            )
        except Exception as e:
            return CalculateScoresResponse(
                success=False,
                error=str(e)
            )
