"""Account profile and reference data API views."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application import interface_services

from .permissions import GeneralPermission, TradingPermission
from .serializers import (
    AccountProfileSerializer,
    AccountProfileUpdateSerializer,
    AssetMetadataSerializer,
    TradingCostCalculationSerializer,
    TradingCostConfigCreateSerializer,
    TradingCostConfigSerializer,
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
        profile = interface_services.get_api_profile(request.user.id)
        serializer = AccountProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request):
        """更新当前用户的账户配置"""
        serializer = AccountProfileUpdateSerializer(data=request.data, partial=True)

        if serializer.is_valid():
            profile = interface_services.update_api_profile(
                request.user.id,
                profile_data=serializer.validated_data,
                email=request.data.get('email'),
            )
            return Response(AccountProfileUpdateSerializer(profile).data)
        return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

class AssetMetadataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    资产元数据 API ViewSet (只读)

    - GET /api/account/assets/ - 获取资产列表
    - GET /api/account/assets/{id}/ - 获取资产详情
    - GET /api/account/assets/by-class/{asset_class}/ - 按类别查询
    """

    serializer_class = AssetMetadataSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return the asset metadata queryset via application service."""

        return interface_services.get_asset_metadata_queryset()

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
        return Response(interface_services.get_account_health_payload(request.user.id))

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
        query = request.GET.get("q", "").strip()

        if not query or len(query) < 2:
            return Response({
                "success": True,
                "results": []
            })

        return Response({
            "success": True,
            "results": interface_services.search_observer_candidates(
                owner_user_id=request.user.id,
                query=query,
            ),
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
        return interface_services.get_trading_cost_config_queryset(self.request.user.id)

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
        serializer.instance = interface_services.save_api_trading_cost_config(
            actor_user_id=self.request.user.id,
            portfolio_id=portfolio.id,
            validated_data={
                "commission_rate": serializer.validated_data["commission_rate"],
                "min_commission": serializer.validated_data["min_commission"],
                "stamp_duty_rate": serializer.validated_data["stamp_duty_rate"],
                "transfer_fee_rate": serializer.validated_data["transfer_fee_rate"],
                "is_active": serializer.validated_data.get("is_active", True),
            },
        )

    def perform_update(self, serializer):
        """更新时禁止越权修改配置归属"""
        portfolio = serializer.validated_data.get("portfolio", serializer.instance.portfolio)
        if portfolio.user != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("无权修改此投资组合的费率")
        serializer.instance = interface_services.save_api_trading_cost_config(
            actor_user_id=self.request.user.id,
            portfolio_id=portfolio.id,
            validated_data={
                "commission_rate": serializer.validated_data.get(
                    "commission_rate", serializer.instance.commission_rate
                ),
                "min_commission": serializer.validated_data.get(
                    "min_commission", serializer.instance.min_commission
                ),
                "stamp_duty_rate": serializer.validated_data.get(
                    "stamp_duty_rate", serializer.instance.stamp_duty_rate
                ),
                "transfer_fee_rate": serializer.validated_data.get(
                    "transfer_fee_rate", serializer.instance.transfer_fee_rate
                ),
                "is_active": serializer.validated_data.get(
                    "is_active", serializer.instance.is_active
                ),
            },
        )

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

