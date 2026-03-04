"""
Factor Module Interface Layer - Views

DRF ViewSets and page views for the factor module.
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from datetime import date, datetime

from apps.factor.infrastructure.models import (
    FactorDefinitionModel,
    FactorPortfolioConfigModel,
    FactorPortfolioHoldingModel,
    FactorExposureModel,
)
from apps.factor.infrastructure.repositories import (
    FactorDefinitionRepository,
    FactorPortfolioConfigRepository,
    FactorPortfolioHoldingRepository,
)
from apps.factor.infrastructure.services import FactorIntegrationService
from apps.factor.interface.serializers import (
    FactorDefinitionSerializer,
    FactorPortfolioConfigSerializer,
    FactorPortfolioHoldingSerializer,
    FactorScoreRequestSerializer,
    FactorScoreResponseSerializer,
)

# Application layer UseCases
from apps.factor.application.use_cases import (
    GetFactorDefinitionsForViewUseCase,
    GetPortfolioConfigsForViewUseCase,
    GetFactorCalculationDataUseCase,
    CreatePortfolioConfigUseCase,
    UpdatePortfolioConfigUseCase,
    CalculateScoresUseCase,
    FactorListViewRequest,
    PortfolioListViewRequest,
    FactorCalculateViewRequest,
    CreatePortfolioConfigRequest,
    PortfolioConfigActionRequest,
    CalculateScoresRequest,
)


class FactorDefinitionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for FactorDefinition model"""
    queryset = FactorDefinitionModel._default_manager.filter(is_active=True)
    serializer_class = FactorDefinitionSerializer
    filterset_fields = ['category', 'is_active']
    search_fields = ['code', 'name', 'description']
    ordering_fields = ['category', 'code']

    @action(detail=False, methods=['get'])
    def all_active(self, request):
        """Get all active factor definitions"""
        service = FactorIntegrationService()
        factors = service.get_factor_definitions()
        return Response(factors)


class FactorPortfolioConfigViewSet(viewsets.ModelViewSet):
    """ViewSet for FactorPortfolioConfig model"""
    queryset = FactorPortfolioConfigModel._default_manager.all()
    serializer_class = FactorPortfolioConfigSerializer
    filterset_fields = ['is_active', 'universe', 'rebalance_frequency']
    search_fields = ['name', 'description']
    ordering = ['-is_active', '-created_at']

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate this configuration"""
        config = self.get_object()
        config.is_active = True
        config.save()
        return Response({'status': 'activated'})

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate this configuration"""
        config = self.get_object()
        config.is_active = False
        config.save()
        return Response({'status': 'deactivated'})

    @action(detail=True, methods=['post'])
    def generate_portfolio(self, request, pk=None):
        """Generate factor portfolio for this configuration"""
        config = self.get_object()
        service = FactorIntegrationService()

        portfolio = service.create_factor_portfolio(config.name)

        if portfolio:
            return Response(portfolio)
        return Response(
            {'error': 'Failed to generate portfolio'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class FactorScoreViewSet(viewsets.ViewSet):
    """ViewSet for factor score calculations"""

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def calculate_scores(self, request):
        """Calculate factor scores"""
        serializer = FactorScoreRequestSerializer(data=request.data)
        if serializer.is_valid():
            service = FactorIntegrationService()

            scores = service.calculate_factor_scores(
                universe=serializer.validated_data.get('universe', []),
                factor_weights=serializer.validated_data.get('factor_weights', {}),
                trade_date=serializer.validated_data.get('trade_date'),
                top_n=serializer.validated_data.get('top_n', 50),
            )

            return Response({
                'trade_date': serializer.validated_data.get('trade_date'),
                'total_scores': len(scores),
                'scores': scores,
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def explain_stock(self, request):
        """Explain factor score for a stock"""
        stock_code = request.data.get('stock_code')
        factor_weights = request.data.get('factor_weights')

        if not stock_code or not factor_weights:
            return Response(
                {'error': 'stock_code and factor_weights are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = FactorIntegrationService()
        explanation = service.explain_stock_score(
            stock_code=stock_code,
            factor_weights=factor_weights,
        )

        if explanation:
            return Response(explanation)
        return Response(
            {'error': 'Failed to explain stock score'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class FactorActionViewSet(viewsets.ViewSet):
    """ViewSet for factor actions (not tied to a specific model)"""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """Get available factor actions"""
        return Response({
            'actions': {
                'top_stocks': 'POST /factor/api/top_stocks/ - Get top stocks by factors',
                'create_portfolio': 'POST /factor/api/create_portfolio/ - Create factor portfolio',
                'explain_stock': 'POST /factor/api/explain_stock/ - Explain stock factor score',
            }
        })

    @action(detail=False, methods=['post'], url_path='top-stocks')
    def get_top_stocks(self, request):
        """
        Get top stocks by factor preferences

        Request body:
        {
            "factor_preferences": {
                "value": "high|medium|low",
                "quality": "high|medium|low",
                "growth": "high|medium|low",
                "momentum": "high|medium|low"
            },
            "top_n": 30
        }
        """
        factor_preferences = request.data.get('factor_preferences', {})
        top_n = request.data.get('top_n', 30)

        service = FactorIntegrationService()
        stocks = service.get_top_stocks(factor_preferences, top_n)

        return Response({
            'total_stocks': len(stocks),
            'stocks': stocks,
        })

    @action(detail=False, methods=['post'], url_path='create-portfolio')
    def create_portfolio_action(self, request):
        """
        Create factor portfolio

        Request body:
        {
            "config_name": "价值成长平衡组合",
            "trade_date": "2024-01-15"  // optional
        }
        """
        config_name = request.data.get('config_name')
        trade_date = request.data.get('trade_date')

        if not config_name:
            return Response(
                {'error': 'config_name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = FactorIntegrationService()
        portfolio = service.create_factor_portfolio(config_name, trade_date)

        if portfolio:
            return Response(portfolio)
        return Response(
            {'error': 'Failed to create portfolio'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    @action(detail=False, methods=['post'], url_path='explain-stock')
    def explain_stock_action(self, request):
        """
        Explain stock factor score breakdown

        Request body:
        {
            "stock_code": "000001.SZ",
            "factor_weights": {
                "pe_ttm": -0.3,
                "roe": 0.4,
                "revenue_growth": 0.3
            }
        }
        """
        stock_code = request.data.get('stock_code')
        factor_weights = request.data.get('factor_weights')

        if not stock_code or not factor_weights:
            return Response(
                {'error': 'stock_code and factor_weights are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = FactorIntegrationService()
        explanation = service.explain_stock_score(stock_code, factor_weights)

        if explanation:
            return Response(explanation)
        return Response(
            {'error': 'Failed to explain stock score'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    @action(detail=False, methods=['get'], url_path='all-configs')
    def get_all_configs(self, request):
        """Get all portfolio configurations"""
        service = FactorIntegrationService()
        configs = service.get_all_configs()
        return Response(configs)

    @action(detail=False, methods=['get'], url_path='all-factors')
    def get_all_factors(self, request):
        """Get all factor definitions"""
        service = FactorIntegrationService()
        factors = service.get_factor_definitions()
        return Response(factors)


# ============================================================================
# Page Views (HTML Templates)
# ============================================================================

def factor_home_redirect(request):
    """Redirect root /factor/ to manage page"""
    from django.shortcuts import redirect
    return redirect('factor:manage')


def factor_manage_view(request):
    """
    因子管理页面 - Factor Definition Management

    Displays all factor definitions with filtering and details.
    """
    # Create repository and UseCase
    factor_repo = FactorDefinitionRepository()
    use_case = GetFactorDefinitionsForViewUseCase(factor_repo)

    # Build request from query parameters
    category_filter = request.GET.get('category', '')
    is_active_str = request.GET.get('is_active', '')
    search = request.GET.get('search', '')

    use_case_request = FactorListViewRequest(
        category=category_filter if category_filter else None,
        is_active=(is_active_str == 'true') if is_active_str else None,
        search=search if search else None,
    )

    # Execute UseCase
    response = use_case.execute(use_case_request)

    context = {
        'factors': response.factors,
        'stats': response.stats,
        'categories': response.categories,
        'category_choices': response.category_choices,
        'filter_category': category_filter,
        'filter_is_active': is_active_str,
        'filter_search': search,
    }

    return render(request, 'factor/manage.html', context)


def portfolio_list_view(request):
    """
    因子组合配置页面 - Portfolio Configuration Management

    Displays portfolio configurations with CRUD operations.
    """
    # Create repositories and UseCase
    factor_repo = FactorDefinitionRepository()
    portfolio_repo = FactorPortfolioConfigRepository()
    use_case = GetPortfolioConfigsForViewUseCase(factor_repo, portfolio_repo)

    # Build request from query parameters
    is_active_str = request.GET.get('is_active', '')
    search = request.GET.get('search', '')

    use_case_request = PortfolioListViewRequest(
        is_active=(is_active_str == 'true') if is_active_str else None,
        search=search if search else None,
    )

    # Execute UseCase
    response = use_case.execute(use_case_request)

    context = {
        'configs': response.configs,
        'stats': response.stats,
        'factor_definitions': response.factor_definitions,
        'universe_choices': response.universe_choices,
        'weight_method_choices': response.weight_method_choices,
        'rebalance_choices': response.rebalance_choices,
        'filter_is_active': is_active_str,
        'filter_search': search,
    }

    return render(request, 'factor/portfolios.html', context)


def factor_calculate_view(request):
    """
    因子计算页面 - Factor Score Calculation

    Calculate factor scores, display Top N stocks, and explain scores.
    """
    # Create repositories and UseCase
    portfolio_repo = FactorPortfolioConfigRepository()
    factor_repo = FactorDefinitionRepository()
    use_case = GetFactorCalculationDataUseCase(portfolio_repo, factor_repo)

    # Get calculation parameters
    trade_date_str = request.GET.get('trade_date')
    if trade_date_str:
        try:
            from datetime import datetime
            trade_date = datetime.strptime(trade_date_str, '%Y-%m-%d').date()
        except ValueError:
            trade_date = date.today()
    else:
        trade_date = date.today()

    top_n = int(request.GET.get('top_n', 30))
    config_id = request.GET.get('config_id')
    config_id_int = int(config_id) if config_id else None

    # Build request
    use_case_request = FactorCalculateViewRequest(
        trade_date=trade_date,
        top_n=top_n,
        config_id=config_id_int,
    )

    # Execute UseCase
    response = use_case.execute(use_case_request)

    context = {
        'configs': response.configs,
        'factors': response.factors,
        'factors_by_category': response.factors_by_category,
        'category_choices': response.category_choices,
        'selected_config': response.selected_config,
        'calculated_results': response.calculated_results,
        'trade_date': response.trade_date,
        'top_n': response.top_n,
        'config_id': response.config_id,
    }

    return render(request, 'factor/calculate.html', context)


@require_http_methods(["POST"])
def create_portfolio_config_view(request):
    """
    Create a new portfolio configuration
    """
    import json

    # Create repository and UseCase
    portfolio_repo = FactorPortfolioConfigRepository()
    use_case = CreatePortfolioConfigUseCase(portfolio_repo)

    try:
        # Parse form data
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        universe = request.POST.get('universe', 'all_a')
        top_n = int(request.POST.get('top_n', 30))
        rebalance_frequency = request.POST.get('rebalance_frequency', 'monthly')
        weight_method = request.POST.get('weight_method', 'equal_weight')

        # Factor weights from JSON
        factor_weights_json = request.POST.get('factor_weights', '{}')
        factor_weights = json.loads(factor_weights_json) if factor_weights_json else {}

        # Optional constraints
        min_market_cap = request.POST.get('min_market_cap')
        max_market_cap = request.POST.get('max_market_cap')
        max_pe = request.POST.get('max_pe')
        max_pb = request.POST.get('max_pb')
        max_debt_ratio = request.POST.get('max_debt_ratio')

        # Build request
        use_case_request = CreatePortfolioConfigRequest(
            name=name,
            description=description,
            universe=universe,
            top_n=top_n,
            rebalance_frequency=rebalance_frequency,
            weight_method=weight_method,
            factor_weights=factor_weights,
            min_market_cap=float(min_market_cap) if min_market_cap else None,
            max_market_cap=float(max_market_cap) if max_market_cap else None,
            max_pe=float(max_pe) if max_pe else None,
            max_pb=float(max_pb) if max_pb else None,
            max_debt_ratio=float(max_debt_ratio) if max_debt_ratio else None,
        )

        # Execute UseCase
        response = use_case.execute(use_case_request)

        if response.success:
            return JsonResponse({
                'success': True,
                'config_id': response.config_id,
                'message': response.message
            })
        else:
            return JsonResponse({
                'success': False,
                'error': response.error
            }, status=400)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@require_http_methods(["POST", "DELETE"])
def portfolio_config_action_view(request, config_id):
    """
    Perform actions on portfolio config (activate, deactivate, delete)
    """
    # Handle DELETE separately
    if request.method == 'DELETE':
        try:
            config = FactorPortfolioConfigModel._default_manager.get(id=config_id)
            config_name = config.name
            config.delete()
            return JsonResponse({
                'success': True,
                'message': f'组合配置 "{config_name}" 已删除'
            })
        except FactorPortfolioConfigModel.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': '配置不存在'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    # POST actions via UseCase
    portfolio_repo = FactorPortfolioConfigRepository()
    integration_service = FactorIntegrationService()
    use_case = UpdatePortfolioConfigUseCase(portfolio_repo, integration_service)

    action_type = request.POST.get('action')

    use_case_request = PortfolioConfigActionRequest(
        config_id=config_id,
        action_type=action_type,
    )

    # Execute UseCase
    response = use_case.execute(use_case_request)

    if response.get('success'):
        return JsonResponse(response)
    else:
        status_code = 500 if response.get('error') == '生成组合失败' else 400
        return JsonResponse(response, status=status_code)


@require_http_methods(["POST"])
def calculate_scores_view(request):
    """
    Calculate factor scores for a portfolio configuration
    """
    # Create UseCase
    integration_service = FactorIntegrationService()
    use_case = CalculateScoresUseCase(integration_service)

    try:
        config_id = int(request.POST.get('config_id'))
        top_n = int(request.POST.get('top_n', 30))
        trade_date_str = request.POST.get('trade_date')

        # Parse trade_date from request or use today
        if trade_date_str:
            try:
                trade_date = datetime.strptime(trade_date_str, '%Y-%m-%d').date()
            except ValueError:
                trade_date = date.today()
        else:
            trade_date = date.today()

        # Build request
        use_case_request = CalculateScoresRequest(
            config_id=config_id,
            top_n=top_n,
            trade_date=trade_date,
        )

        # Execute UseCase
        response = use_case.execute(use_case_request)

        if response.success:
            return JsonResponse({
                'success': True,
                'total_scores': response.total_scores,
                'scores': response.scores,
                'message': response.message
            })
        else:
            return JsonResponse({
                'success': False,
                'error': response.error
            }, status=500)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
def explain_stock_view(request, stock_code):
    """
    Get factor score explanation for a specific stock
    """
    try:
        config_id = request.GET.get('config_id')

        if not config_id:
            return JsonResponse({
                'success': False,
                'error': '缺少 config_id 参数'
            }, status=400)

        config = FactorPortfolioConfigModel._default_manager.get(id=config_id)

        service = FactorIntegrationService()
        explanation = service.explain_stock_score(
            stock_code=stock_code,
            factor_weights=config.factor_weights or {},
        )

        if explanation:
            return JsonResponse({
                'success': True,
                'explanation': explanation
            })
        else:
            return JsonResponse({
                'success': False,
                'error': '无法获取因子解释'
            }, status=500)

    except FactorPortfolioConfigModel.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': '配置不存在'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
