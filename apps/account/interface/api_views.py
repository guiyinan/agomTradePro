"""
DRF API Views for Account Module.

提供账户、投资组合、持仓、交易和资金流水的 RESTful API。
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q, Count
from django.db import models
from django.shortcuts import get_object_or_404
from decimal import Decimal

from apps.account.infrastructure.models import (
    AccountProfileModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
    CapitalFlowModel,
    AssetMetadataModel,
)
from apps.account.infrastructure.repositories import (
    PortfolioRepository,
    PositionRepository,
)
from .serializers import (
    AccountProfileSerializer,
    AccountProfileUpdateSerializer,
    PortfolioSerializer,
    PortfolioCreateSerializer,
    PositionSerializer,
    PositionCreateSerializer,
    PositionUpdateSerializer,
    TransactionSerializer,
    TransactionCreateSerializer,
    CapitalFlowSerializer,
    CapitalFlowCreateSerializer,
    AssetMetadataSerializer,
    PortfolioStatisticsSerializer,
)
from .permissions import TradingPermission, GeneralPermission


# ==================== Portfolio ViewSet ====================

class PortfolioViewSet(viewsets.ModelViewSet):
    """
    投资组合 API ViewSet

    提供以下接口:
    - GET /account/api/portfolios/ - 获取投资组合列表
    - POST /account/api/portfolios/ - 创建投资组合
    - GET /account/api/portfolios/{id}/ - 获取组合详情
    - PUT /account/api/portfolios/{id}/ - 更新组合
    - DELETE /account/api/portfolios/{id}/ - 删除组合
    - GET /account/api/portfolios/{id}/positions/ - 获取组合持仓
    - GET /account/api/portfolios/{id}/statistics/ - 获取统计信息
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户的投资组合"""
        return PortfolioModel._default_manager.filter(user=self.request.user)

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return PortfolioCreateSerializer
        return PortfolioSerializer

    def perform_create(self, serializer):
        """创建时自动关联当前用户"""
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['get'])
    def positions(self, request, pk=None):
        """
        获取投资组合的持仓列表

        GET /account/api/portfolios/{id}/positions/
        """
        portfolio = self.get_object()
        positions = portfolio.positions.filter(is_closed=False).select_related()

        serializer = PositionSerializer(positions, many=True)
        return Response({
            'success': True,
            'count': positions.count(),
            'data': serializer.data
        })

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        获取投资组合统计信息

        GET /account/api/portfolios/{id}/statistics/
        """
        portfolio = self.get_object()

        # 持仓统计
        positions = portfolio.positions.filter(is_closed=False)
        position_count = positions.count()

        total_value = positions.aggregate(total=Sum('market_value'))['total'] or Decimal('0')
        total_cost = positions.aggregate(
            total=Sum(
                models.F('shares') * models.F('avg_cost'),
                output_field=models.DecimalField(max_digits=20, decimal_places=2),
            )
        )['total'] or Decimal('0')
        total_pnl = total_value - total_cost
        total_pnl_pct = float((total_pnl / total_cost * 100) if total_cost > 0 else 0)

        # 资产类别分布
        asset_class_breakdown = {}
        for pos in positions:
            key = pos.get_asset_class_display()
            asset_class_breakdown[key] = asset_class_breakdown.get(key, 0) + float(pos.market_value)

        # 地区分布
        region_breakdown = {}
        for pos in positions:
            key = pos.get_region_display()
            region_breakdown[key] = region_breakdown.get(key, 0) + float(pos.market_value)

        # 资金流水
        capital_flows = CapitalFlowModel._default_manager.filter(portfolio=portfolio)
        total_inflow = capital_flows.filter(flow_type='deposit').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')
        total_outflow = capital_flows.filter(flow_type='withdraw').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        data = {
            'total_value': total_value,
            'total_cost': total_cost,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'position_count': position_count,
            'asset_class_breakdown': asset_class_breakdown,
            'region_breakdown': region_breakdown,
            'total_capital_inflow': total_inflow,
            'total_capital_outflow': total_outflow,
            'net_capital_flow': total_inflow - total_outflow,
        }

        serializer = PortfolioStatisticsSerializer(data)
        return Response(serializer.data)


# ==================== Position ViewSet ====================

class PositionViewSet(viewsets.ModelViewSet):
    """
    持仓 API ViewSet

    提供以下接口:
    - GET /account/api/positions/ - 获取持仓列表
    - POST /account/api/positions/ - 创建持仓
    - GET /account/api/positions/{id}/ - 获取持仓详情
    - PUT /account/api/positions/{id}/ - 更新持仓
    - DELETE /account/api/positions/{id}/ - 删除持仓
    - POST /account/api/positions/{id}/close/ - 平仓
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的持仓"""
        user_portfolios = PortfolioModel._default_manager.filter(user=self.request.user)
        return PositionModel._default_manager.filter(portfolio__in=user_portfolios)

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return PositionCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PositionUpdateSerializer
        return PositionSerializer

    def perform_create(self, serializer):
        """创建时需要指定投资组合"""
        portfolio_id = self.request.data.get('portfolio')
        portfolio = get_object_or_404(
            PortfolioModel,
            id=portfolio_id,
            user=self.request.user
        )

        # 计算市值和盈亏
        shares = serializer.validated_data['shares']
        avg_cost = serializer.validated_data['avg_cost']
        current_price = serializer.validated_data.get('current_price', avg_cost)
        market_value = shares * float(current_price)
        unrealized_pnl = market_value - (shares * float(avg_cost))
        unrealized_pnl_pct = (unrealized_pnl / (shares * float(avg_cost)) * 100) if avg_cost > 0 else 0

        serializer.save(
            portfolio=portfolio,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct
        )

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """
        平仓

        POST /account/api/positions/{id}/close/
        """
        position = self.get_object()

        if position.is_closed:
            return Response({
                'success': False,
                'error': '该持仓已平仓'
            }, status=status.HTTP_400_BAD_REQUEST)

        from datetime import datetime
        position.is_closed = True
        position.closed_at = datetime.now()
        position.save()

        serializer = PositionSerializer(position)
        return Response({
            'success': True,
            'message': '持仓已平仓',
            'data': serializer.data
        })


# ==================== Transaction ViewSet ====================

class TransactionViewSet(viewsets.ModelViewSet):
    """
    交易记录 API ViewSet

    提供以下接口:
    - GET /account/api/transactions/ - 获取交易列表
    - POST /account/api/transactions/ - 创建交易记录
    - GET /account/api/transactions/{id}/ - 获取交易详情
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的交易"""
        user_portfolios = PortfolioModel._default_manager.filter(user=self.request.user)
        return TransactionModel._default_manager.filter(portfolio__in=user_portfolios).select_related(
            'portfolio', 'position'
        )

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return TransactionCreateSerializer
        return TransactionSerializer

    def perform_create(self, serializer):
        """创建时验证持仓归属"""
        position = serializer.validated_data.get('position')
        if position and position.portfolio.user != self.request.user:
            raise PermissionError("无权为此持仓创建交易记录")

        # 计算成交金额
        shares = serializer.validated_data['shares']
        price = serializer.validated_data['price']
        notional = shares * float(price)

        serializer.save(notional=notional)


# ==================== Capital Flow ViewSet ====================

class CapitalFlowViewSet(viewsets.ModelViewSet):
    """
    资金流水 API ViewSet

    提供以下接口:
    - GET /account/api/capital-flows/ - 获取资金流水列表
    - POST /account/api/capital-flows/ - 创建资金流水
    - GET /account/api/capital-flows/{id}/ - 获取流水详情
    - DELETE /account/api/capital-flows/{id}/ - 删除流水
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的资金流水"""
        user_portfolios = PortfolioModel._default_manager.filter(user=self.request.user)
        return CapitalFlowModel._default_manager.filter(portfolio__in=user_portfolios).select_related('portfolio')

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return CapitalFlowCreateSerializer
        return CapitalFlowSerializer

    def perform_create(self, serializer):
        """创建时验证投资组合归属"""
        portfolio_id = self.request.data.get('portfolio')
        portfolio = get_object_or_404(
            PortfolioModel,
            id=portfolio_id,
            user=self.request.user
        )
        serializer.save(portfolio=portfolio, user=self.request.user)


# ==================== Account Profile API ====================

class AccountProfileView(APIView):
    """
    账户配置 API

    - GET /account/api/profile/ - 获取账户配置
    - PUT /account/api/profile/ - 更新账户配置
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request):
        """获取当前用户的账户配置"""
        profile = request.user.account_profile
        serializer = AccountProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request):
        """更新当前用户的账户配置"""
        profile = request.user.account_profile
        serializer = AccountProfileUpdateSerializer(profile, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            # 更新邮箱
            email = request.data.get('email')
            if email:
                request.user.email = email
                request.user.save()

            return Response(serializer.data)
        return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


# ==================== Asset Metadata API ====================

class AssetMetadataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    资产元数据 API ViewSet (只读)

    - GET /account/api/assets/ - 获取资产列表
    - GET /account/api/assets/{id}/ - 获取资产详情
    - GET /account/api/assets/by-class/{asset_class}/ - 按类别查询
    """

    queryset = AssetMetadataModel._default_manager.all()
    serializer_class = AssetMetadataSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='by-class/(?P<asset_class>[^/]+)')
    def by_class(self, request, asset_class=None):
        """
        按资产类别查询

        GET /account/api/assets/by-class/{asset_class}/
        """
        assets = self.get_queryset().filter(asset_class=asset_class)
        serializer = AssetMetadataSerializer(assets, many=True)
        return Response({
            'success': True,
            'count': assets.count(),
            'data': serializer.data
        })


# ==================== Health Check ====================

class AccountHealthView(APIView):
    """Account 服务健康检查"""

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request):
        """检查 Account 服务健康状态"""
        portfolio_count = PortfolioModel._default_manager.filter(user=request.user).count()
        position_count = PositionModel._default_manager.filter(
            portfolio__user=request.user,
            is_closed=False
        ).count()

        return Response({
            'status': 'healthy',
            'service': 'account',
            'portfolio_count': portfolio_count,
            'position_count': position_count
        })

