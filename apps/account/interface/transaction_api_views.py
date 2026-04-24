"""Account transaction and capital flow API views."""

from decimal import Decimal
from importlib import import_module
from typing import Any

from django.db import models
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.interface_services import (
    get_user_capital_flow_queryset,
    get_user_portfolio,
    get_user_transaction_queryset,
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

class TransactionViewSet(viewsets.ModelViewSet):
    """
    交易记录 API ViewSet

    提供以下接口:
    - GET /api/account/transactions/ - 获取交易列表
    - POST /api/account/transactions/ - 创建交易记录
    - GET /api/account/transactions/{id}/ - 获取交易详情
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的交易"""
        return get_user_transaction_queryset(self.request.user.id)

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return TransactionCreateSerializer
        return TransactionSerializer

    def perform_create(self, serializer):
        """创建时验证持仓归属"""
        portfolio = serializer.validated_data.get('portfolio')
        position = serializer.validated_data.get('position')
        if position and position.portfolio.user != self.request.user:
            raise PermissionDenied("无权为此持仓创建交易记录")
        if position and portfolio and position.portfolio_id != portfolio.id:
            raise ValidationError({"position": "持仓不属于该投资组合"})

        # 计算成交金额
        shares = serializer.validated_data['shares']
        price = serializer.validated_data['price']
        notional = shares * float(price)

        serializer.save(notional=notional)

class CapitalFlowViewSet(viewsets.ModelViewSet):
    """
    资金流水 API ViewSet

    提供以下接口:
    - GET /api/account/capital-flows/ - 获取资金流水列表
    - POST /api/account/capital-flows/ - 创建资金流水
    - GET /api/account/capital-flows/{id}/ - 获取流水详情
    - DELETE /api/account/capital-flows/{id}/ - 删除流水
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的资金流水"""
        return get_user_capital_flow_queryset(self.request.user.id)

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return CapitalFlowCreateSerializer
        return CapitalFlowSerializer

    def perform_create(self, serializer):
        """创建时验证投资组合归属"""
        portfolio_value = serializer.validated_data.get("portfolio")
        portfolio_id = getattr(portfolio_value, "id", None) or self.request.data.get("portfolio")
        portfolio = get_user_portfolio(
            user_id=self.request.user.id,
            portfolio_id=portfolio_id,
        )
        if portfolio is None:
            raise NotFound()
        serializer.save(portfolio=portfolio, user=self.request.user)

