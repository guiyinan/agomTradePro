"""
DRF API Views for Asset Classification and Multi-Currency Support.

资产分类、币种和汇率管理的 API 视图。
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.db.models import Sum
from decimal import Decimal

from apps.account.infrastructure.models import (
    AssetCategoryModel,
    CurrencyModel,
    ExchangeRateModel,
    PortfolioModel,
    PositionModel,
)
from .classification_serializers import (
    AssetCategorySerializer,
    AssetCategoryTreeSerializer,
    CurrencySerializer,
    ExchangeRateSerializer,
    ExchangeRateCreateSerializer,
    CurrencyConvertSerializer,
    AssetAllocationSerializer,
    CurrencyAllocationSerializer,
)


# ==================== Asset Category ViewSet ====================

class AssetCategoryViewSet(viewsets.ModelViewSet):
    """
    资产分类 API ViewSet

    提供以下接口:
    - GET /account/api/categories/ - 获取分类列表
    - POST /account/api/categories/ - 创建分类
    - GET /account/api/categories/tree/ - 获取分类树
    - GET /account/api/categories/roots/ - 获取一级分类
    - GET /account/api/categories/{id}/children/ - 获取子分类
    """

    queryset = AssetCategoryModel.objects.filter(is_active=True)
    serializer_class = AssetCategorySerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        """只有管理员可以创建/更新/删除分类"""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    @action(detail=False, methods=['get'])
    def roots(self, request):
        """
        获取一级分类

        GET /account/api/categories/roots/
        """
        categories = self.queryset.filter(level=1).order_by('sort_order')
        serializer = AssetCategorySerializer(categories, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        })

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """
        获取完整分类树

        GET /account/api/categories/tree/
        """
        roots = self.queryset.filter(level=1, parent__isnull=True).order_by('sort_order')
        serializer = AssetCategoryTreeSerializer(roots, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        })

    @action(detail=True, methods=['get'])
    def children(self, request, pk=None):
        """
        获取子分类

        GET /account/api/categories/{id}/children/
        """
        category = self.get_object()
        children = category.children.filter(is_active=True).order_by('sort_order')
        serializer = AssetCategorySerializer(children, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        })


# ==================== Currency ViewSet ====================

class CurrencyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    币种 API ViewSet (只读)

    - GET /account/api/currencies/ - 获取币种列表
    - GET /account/api/currencies/{id}/ - 获取币种详情
    - GET /account/api/currencies/base/ - 获取基准货币
    """

    queryset = CurrencyModel.objects.filter(is_active=True)
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def base(self, request):
        """
        获取基准货币

        GET /account/api/currencies/base/
        """
        currency = CurrencyModel.get_base_currency()
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
    - GET /account/api/exchange-rates/ - 获取汇率列表
    - POST /account/api/exchange-rates/ - 创建汇率
    - GET /account/api/exchange-rates/latest/ - 获取最新汇率
    - POST /account/api/exchange-rates/convert/ - 货币转换
    """

    queryset = ExchangeRateModel.objects.all()
    permission_classes = [IsAuthenticated]

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

    @action(detail=False, methods=['get'], url_path='latest/(?P<from_code>[^/]+)/(?P<to_code>[^/]+)')
    def latest(self, request, from_code=None, to_code=None):
        """
        获取最新汇率

        GET /account/api/exchange-rates/latest/{from_code}/{to_code}/
        """
        rate = ExchangeRateModel.get_latest_rate(from_code, to_code)
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

        POST /account/api/exchange-rates/convert/
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
            converted_amount = ExchangeRateModel.convert_amount(
                amount=data['amount'],
                from_code=data['from_currency'],
                to_code=data['to_currency'],
                date=data.get('date')
            )

            # 获取使用的汇率
            queryset = ExchangeRateModel.objects.filter(
                from_currency__code=data['from_currency'],
                to_currency__code=data['to_currency']
            )

            if data.get('date'):
                queryset = queryset.filter(effective_date__lte=data['date']).order_by('-effective_date')
            else:
                queryset = queryset.order_by('-effective_date')

            rate = queryset.first()

            return Response({
                'success': True,
                'converted_amount': converted_amount,
                'rate_used': rate.rate,
                'rate_date': rate.effective_date
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

    - GET /account/api/portfolios/{id}/allocation/ - 获取资产配置
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, portfolio_id):
        """
        获取投资组合的资产配置分析

        支持按资产分类和币种进行配置分析
        """
        portfolio = PortfolioModel.objects.get(id=portfolio_id, user=request.user)

        dimension = request.query_params.get('dimension', 'category')  # category 或 currency

        if dimension == 'currency':
            return self._get_currency_allocation(portfolio)
        else:
            return self._get_category_allocation(portfolio)

    def _get_category_allocation(self, portfolio):
        """按资产分类统计配置"""
        positions = portfolio.positions.filter(is_closed=False).select_related('category')

        # 按分类汇总
        category_allocation = {}
        total_value = Decimal('0')

        for pos in positions:
            category_path = pos.category.get_full_path() if pos.category else '未分类'
            amount = pos.market_value

            if category_path not in category_allocation:
                category_allocation[category_path] = Decimal('0')
            category_allocation[category_path] += amount
            total_value += amount

        # 转换为序列化格式
        data = []
        for category_path, amount in category_allocation.items():
            data.append({
                'category_path': category_path,
                'amount': amount,
                'percentage': float(amount / total_value * 100) if total_value > 0 else 0
            })

        serializer = AssetAllocationSerializer(data, many=True)
        return Response({
            'success': True,
            'dimension': 'category',
            'total_value': total_value,
            'data': serializer.data
        })

    def _get_currency_allocation(self, portfolio):
        """按币种统计配置"""
        from apps.account.infrastructure.models import ExchangeRateModel

        positions = portfolio.positions.filter(is_closed=False)
        base_currency = portfolio.base_currency or CurrencyModel.get_base_currency()

        # 按币种汇总（原币）
        currency_allocation = {}
        total_value_base = Decimal('0')

        for pos in positions:
            currency_code = pos.currency.code if pos.currency else 'CNY'
            amount = pos.market_value  # 这里是原币金额

            if currency_code not in currency_allocation:
                currency_allocation[currency_code] = Decimal('0')
            currency_allocation[currency_code] += amount

            # 转换为基准货币
            if currency_code != base_currency.code:
                try:
                    amount_base = ExchangeRateModel.convert_amount(
                        amount=amount,
                        from_code=currency_code,
                        to_code=base_currency.code
                    )
                except ValueError:
                    # 如果没有汇率，使用原币金额
                    amount_base = amount
            else:
                amount_base = amount

            total_value_base += amount_base

        # 转换为序列化格式
        data = []
        for currency_code, amount in currency_allocation.items():
            currency = CurrencyModel.objects.filter(code=currency_code).first()

            # 转换为基准货币
            if currency_code != base_currency.code:
                try:
                    amount_base = ExchangeRateModel.convert_amount(
                        amount=amount,
                        from_code=currency_code,
                        to_code=base_currency.code
                    )
                except ValueError:
                    amount_base = amount
            else:
                amount_base = amount

            data.append({
                'currency_code': currency_code,
                'currency_name': currency.name if currency else currency_code,
                'amount': amount,
                'amount_base': amount_base,
                'percentage': float(amount_base / total_value_base * 100) if total_value_base > 0 else 0
            })

        serializer = CurrencyAllocationSerializer(data, many=True)
        return Response({
            'success': True,
            'dimension': 'currency',
            'base_currency': base_currency.code,
            'total_value_base': total_value_base,
            'data': serializer.data
        })
