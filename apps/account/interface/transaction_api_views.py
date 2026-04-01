"""Account transaction and capital flow API views."""

from decimal import Decimal
from importlib import import_module
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

CapitalFlowModel = django_apps.get_model("account", "CapitalFlowModel")
PortfolioModel = django_apps.get_model("account", "PortfolioModel")
TransactionModel = django_apps.get_model("account", "TransactionModel")

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

