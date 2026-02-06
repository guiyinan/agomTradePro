"""
Factor Module Interface Layer - Views

DRF ViewSets for the factor module API.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.factor.infrastructure.models import (
    FactorDefinitionModel,
    FactorPortfolioConfigModel,
    FactorPortfolioHoldingModel,
)
from apps.factor.infrastructure.services import FactorIntegrationService
from apps.factor.interface.serializers import (
    FactorDefinitionSerializer,
    FactorPortfolioConfigSerializer,
    FactorPortfolioHoldingSerializer,
    FactorScoreRequestSerializer,
    FactorScoreResponseSerializer,
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

    permission_classes = []  # Allow unauthenticated access

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
    permission_classes = []  # Allow unauthenticated access

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

