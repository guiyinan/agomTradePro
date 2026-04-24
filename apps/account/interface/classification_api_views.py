"""DRF API Views for Asset Classification and Multi-Currency Support."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.interface_services import (
    convert_currency_amount,
    create_asset_category,
    create_exchange_rate,
    delete_asset_category,
    delete_exchange_rate,
    get_asset_category_children,
    get_asset_category_queryset,
    get_asset_category_roots,
    get_asset_category_tree_roots,
    get_base_currency,
    get_currency_queryset,
    get_exchange_rate_queryset,
    get_latest_exchange_rate,
    get_portfolio_allocation_payload,
    update_asset_category,
    update_exchange_rate,
)

from .classification_serializers import (
    AssetAllocationSerializer,
    AssetCategorySerializer,
    AssetCategoryTreeSerializer,
    CurrencyAllocationSerializer,
    CurrencyConvertSerializer,
    CurrencySerializer,
    ExchangeRateCreateSerializer,
    ExchangeRateSerializer,
)

# ==================== Asset Category ViewSet ====================

class AssetCategoryViewSet(viewsets.ModelViewSet):
    """
    资产分类 API ViewSet

    提供以下接口:
    - GET /api/account/categories/ - 获取分类列表
    - POST /api/account/categories/ - 创建分类
    - GET /api/account/categories/tree/ - 获取分类树
    - GET /api/account/categories/roots/ - 获取一级分类
    - GET /api/account/categories/{id}/children/ - 获取子分类
    """

    serializer_class = AssetCategorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return active asset categories through the application layer."""

        return get_asset_category_queryset()

    def get_permissions(self):
        """只有管理员可以创建/更新/删除分类"""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        """Create asset categories through the application layer."""

        serializer.instance = create_asset_category(validated_data=serializer.validated_data)

    def perform_update(self, serializer):
        """Update asset categories through the application layer."""

        serializer.instance = update_asset_category(
            category_id=self.get_object().id,
            validated_data=serializer.validated_data,
        )

    def perform_destroy(self, instance):
        """Delete asset categories through the application layer."""

        delete_asset_category(category_id=instance.id)

    @action(detail=False, methods=['get'])
    def roots(self, request):
        """
        获取一级分类

        GET /api/account/categories/roots/
        """
        categories = get_asset_category_roots()
        serializer = AssetCategorySerializer(categories, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        })

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """
        获取完整分类树

        GET /api/account/categories/tree/
        """
        roots = get_asset_category_tree_roots()
        serializer = AssetCategoryTreeSerializer(roots, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        })

    @action(detail=True, methods=['get'])
    def children(self, request, pk=None):
        """
        获取子分类

        GET /api/account/categories/{id}/children/
        """
        category = self.get_object()
        children = get_asset_category_children(category_id=category.id)
        serializer = AssetCategorySerializer(children, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        })


# ==================== Currency ViewSet ====================

class CurrencyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    币种 API ViewSet (只读)

    - GET /api/account/currencies/ - 获取币种列表
    - GET /api/account/currencies/{id}/ - 获取币种详情
    - GET /api/account/currencies/base/ - 获取基准货币
    """

    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return active currencies through the application layer."""

        return get_currency_queryset()

    @action(detail=False, methods=['get'])
    def base(self, request):
        """
        获取基准货币

        GET /api/account/currencies/base/
        """
        currency = get_base_currency()
        if not currency:
            return Response({
                'success': False,
                'error': 'No base currency found'
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = CurrencySerializer(currency)
        return Response(serializer.data)


# ==================== Exchange Rate ViewSet ====================

class ExchangeRateViewSet(viewsets.ModelViewSet):
    """
    汇率 API ViewSet

    提供以下接口:
    - GET /api/account/exchange-rates/ - 获取汇率列表
    - POST /api/account/exchange-rates/ - 创建汇率
    - GET /api/account/exchange-rates/latest/ - 获取最新汇率
    - POST /api/account/exchange-rates/convert/ - 货币转换
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return exchange rates through the application layer."""

        return get_exchange_rate_queryset()

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return ExchangeRateCreateSerializer
        return ExchangeRateSerializer

    def get_permissions(self):
        """只有管理员可以创建/更新/删除汇率"""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        """Create exchange rates through the application layer."""

        serializer.instance = create_exchange_rate(validated_data=serializer.validated_data)

    def perform_update(self, serializer):
        """Update exchange rates through the application layer."""

        serializer.instance = update_exchange_rate(
            exchange_rate_id=self.get_object().id,
            validated_data=serializer.validated_data,
        )

    def perform_destroy(self, instance):
        """Delete exchange rates through the application layer."""

        delete_exchange_rate(exchange_rate_id=instance.id)

    @action(detail=False, methods=['get'], url_path='latest/(?P<from_code>[^/]+)/(?P<to_code>[^/]+)')
    def latest(self, request, from_code=None, to_code=None):
        """
        获取最新汇率

        GET /api/account/exchange-rates/latest/{from_code}/{to_code}/
        """
        rate = get_latest_exchange_rate(from_code=from_code, to_code=to_code)
        if not rate:
            return Response({
                'success': False,
                'error': f'No exchange rate found for {from_code} -> {to_code}'
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = ExchangeRateSerializer(rate)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def convert(self, request):
        """
        货币转换

        POST /api/account/exchange-rates/convert/
        {
            "amount": 100,
            "from_currency": "USD",
            "to_currency": "CNY",
            "date": "2024-01-01"  // 可选
        }
        """
        serializer = CurrencyConvertSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        try:
            conversion = convert_currency_amount(
                amount=data['amount'],
                from_currency=data['from_currency'],
                to_currency=data['to_currency'],
                date_value=data.get('date'),
            )

            return Response({
                'success': True,
                'converted_amount': conversion['converted_amount'],
                'rate_used': conversion['rate_used'],
                'rate_date': conversion['rate_date'],
            })

        except ValueError as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


# ==================== Portfolio Allocation API ====================

class PortfolioAllocationView(APIView):
    """
    投资组合配置分析 API

    - GET /api/account/portfolios/{id}/allocation/ - 获取资产配置
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, portfolio_id):
        """
        获取投资组合的资产配置分析

        支持按资产分类和币种进行配置分析
        """
        dimension = request.query_params.get('dimension', 'category')
        payload = get_portfolio_allocation_payload(
            portfolio_id=portfolio_id,
            user_id=request.user.id,
            dimension=dimension,
        )
        if payload is None:
            return Response(
                {
                    'success': False,
                    'error': f'Portfolio not found: {portfolio_id}',
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer_class = CurrencyAllocationSerializer if dimension == 'currency' else AssetAllocationSerializer
        serializer = serializer_class(payload['data'], many=True)
        response_payload = {
            'success': True,
            'dimension': payload['dimension'],
            'data': serializer.data,
        }
        if payload['dimension'] == 'currency':
            response_payload['base_currency'] = payload['base_currency']
            response_payload['total_value_base'] = payload['total_value_base']
        else:
            response_payload['total_value'] = payload['total_value']
        return Response(response_payload)


