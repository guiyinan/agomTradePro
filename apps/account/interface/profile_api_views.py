"""Account profile and reference data API views."""

from decimal import Decimal
from typing import Any

from django.apps import apps as django_apps
from django.db import models
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetMetadataModel,
    CapitalFlowModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
    TradingCostConfigModel,
    TransactionModel,
)
from apps.account.infrastructure.repositories import (
    PortfolioRepository,
    PositionRepository,
)

from .permissions import GeneralPermission, ObserverAccessPermission, TradingPermission
from .serializers import (
    AccountProfileSerializer,
    AccountProfileUpdateSerializer,
    AssetMetadataSerializer,
    CapitalFlowCreateSerializer,
    CapitalFlowSerializer,
    ObserverGrantCreateSerializer,
    ObserverGrantSerializer,
    ObserverGrantUpdateSerializer,
    PortfolioCreateSerializer,
    PortfolioSerializer,
    PortfolioStatisticsSerializer,
    PositionCreateSerializer,
    PositionSerializer,
    PositionUpdateSerializer,
    TradingCostCalculationSerializer,
    TradingCostConfigCreateSerializer,
    TradingCostConfigSerializer,
    TransactionCreateSerializer,
    TransactionSerializer,
)

class AccountProfileView(APIView):
    """
    账户配置 API

    - GET /api/account/profile/ - 获取账户配置
    - PUT /api/account/profile/ - 更新账户配置
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

class AssetMetadataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    资产元数据 API ViewSet (只读)

    - GET /api/account/assets/ - 获取资产列表
    - GET /api/account/assets/{id}/ - 获取资产详情
    - GET /api/account/assets/by-class/{asset_class}/ - 按类别查询
    """

    queryset = AssetMetadataModel._default_manager.all()
    serializer_class = AssetMetadataSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='by-class/(?P<asset_class>[^/]+)')
    def by_class(self, request, asset_class=None):
        """
        按资产类别查询

        GET /api/account/assets/by-class/{asset_class}/
        """
        assets = self.get_queryset().filter(asset_class=asset_class)
        serializer = AssetMetadataSerializer(assets, many=True)
        return Response({
            'success': True,
            'count': assets.count(),
            'data': serializer.data
        })

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

class UserSearchView(APIView):
    """
    用户搜索 API

    用于协作页面添加观察员时的用户搜索

    - GET /api/account/users/search/?q=xxx - 搜索用户
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request):
        """
        搜索用户

        支持按用户名或显示名称搜索
        排除当前用户和已授权的用户
        """
        from django.contrib.auth.models import User

        from apps.account.infrastructure.models import PortfolioObserverGrantModel

        query = request.GET.get("q", "").strip()

        if not query or len(query) < 2:
            return Response({
                "success": True,
                "results": []
            })

        # 搜索用户（按用户名或显示名称）
        users = User._default_manager.filter(
            is_active=True
        ).filter(
            models.Q(username__icontains=query) |
            models.Q(account_profile__display_name__icontains=query)
        ).exclude(id=request.user.id).select_related("account_profile")[:10]

        # 获取已授权的用户ID列表
        granted_user_ids = PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id=request.user,
            status="active"
        ).values_list("observer_user_id", flat=True)

        # 格式化结果
        results = []
        for user in users:
            # 检查是否已授权
            is_already_granted = user.id in granted_user_ids

            results.append({
                "id": user.id,
                "username": user.username,
                "display_name": user.account_profile.display_name if hasattr(user, "account_profile") else user.username,
                "email": user.email or "",
                "is_already_granted": is_already_granted,
            })

        return Response({
            "success": True,
            "results": results
        })

class TradingCostConfigViewSet(viewsets.ModelViewSet):
    """
    交易费率配置 API ViewSet

    提供以下接口:
    - GET /api/account/trading-cost-configs/ - 获取费率配置列表
    - POST /api/account/trading-cost-configs/ - 创建费率配置
    - GET /api/account/trading-cost-configs/{id}/ - 获取费率配置详情
    - PUT /api/account/trading-cost-configs/{id}/ - 更新费率配置
    - DELETE /api/account/trading-cost-configs/{id}/ - 删除费率配置
    - POST /api/account/trading-cost-configs/{id}/calculate/ - 计算交易费用
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的费率配置"""
        user_portfolios = PortfolioModel._default_manager.filter(user=self.request.user)
        return TradingCostConfigModel._default_manager.filter(
            portfolio__in=user_portfolios
        ).select_related('portfolio')

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return TradingCostConfigCreateSerializer
        return TradingCostConfigSerializer

    def perform_create(self, serializer):
        """创建时验证投资组合归属"""
        portfolio = serializer.validated_data['portfolio']
        if portfolio.user != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("无权为此投资组合配置费率")
        serializer.save()

    def perform_update(self, serializer):
        """更新时禁止越权修改配置归属"""
        portfolio = serializer.validated_data.get("portfolio", serializer.instance.portfolio)
        if portfolio.user != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("无权修改此投资组合的费率")
        serializer.save()

    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        """
        计算交易费用

        POST /api/account/trading-cost-configs/{id}/calculate/

        Body:
            {
                "action": "buy" | "sell",
                "amount": 10000.0,
                "is_shanghai": true
            }
        """
        config_model = self.get_object()
        config = config_model.to_domain()

        payload = TradingCostCalculationSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        action_type = payload.validated_data["action"]
        amount = payload.validated_data["amount"]
        is_shanghai = payload.validated_data["is_shanghai"]

        if action_type == 'sell':
            cost = config.calculate_sell_cost(amount, is_shanghai)
        else:
            cost = config.calculate_buy_cost(amount, is_shanghai)

        cost['action'] = action_type
        cost['amount'] = amount
        cost['is_shanghai'] = is_shanghai
        cost['cost_ratio'] = round(cost['total'] / amount * 100, 4) if amount > 0 else 0

        return Response({'success': True, 'data': cost})

