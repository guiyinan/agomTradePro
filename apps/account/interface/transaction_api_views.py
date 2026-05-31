"""Account transaction and capital flow API views."""


from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.interface_services import (
    get_user_capital_flow_queryset,
    get_user_portfolio,
    get_user_transaction_queryset,
)
from apps.account.application.manual_trade_sync import ManualTradeImportUseCase

from .permissions import TradingPermission
from .serializers import (
    CapitalFlowCreateSerializer,
    CapitalFlowSerializer,
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


class BrokerTradeImportSerializer(serializers.Serializer):
    """Validate manual broker trade import requests."""

    portfolio_id = serializers.IntegerField()
    broker_name = serializers.CharField(required=False, allow_blank=True, default="manual")
    file = serializers.FileField()


class BrokerTradeImportPreviewView(APIView):
    """Preview CSV/XLSX broker trades before importing."""

    permission_classes = [IsAuthenticated, TradingPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = BrokerTradeImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = serializer.validated_data["file"]
        result = ManualTradeImportUseCase().preview(
            user_id=request.user.id,
            portfolio_id=serializer.validated_data["portfolio_id"],
            broker_name=serializer.validated_data.get("broker_name") or "manual",
            filename=uploaded_file.name,
            content=uploaded_file.read(),
        )
        return Response(result.__dict__, status=status.HTTP_200_OK)


class BrokerTradeImportConfirmView(APIView):
    """Import CSV/XLSX broker trades and sync account positions."""

    permission_classes = [IsAuthenticated, TradingPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = BrokerTradeImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = serializer.validated_data["file"]
        result = ManualTradeImportUseCase().confirm(
            user_id=request.user.id,
            portfolio_id=serializer.validated_data["portfolio_id"],
            broker_name=serializer.validated_data.get("broker_name") or "manual",
            filename=uploaded_file.name,
            content=uploaded_file.read(),
        )
        return Response(result.__dict__, status=status.HTTP_201_CREATED)

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

