"""Account profile and reference data API views."""

from collections.abc import Callable
from typing import Any, TypeVar, cast

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from apps.account.application import interface_services

from .permissions import GeneralPermission, TradingPermission
from .serializers import (
    AccountProfileSerializer,
    AccountProfileUpdateSerializer,
    AssetMetadataSerializer,
    MacroSizingConfigSerializer,
    MacroSizingConfigUpdateSerializer,
    TradingCostCalculationSerializer,
    TradingCostConfigCreateSerializer,
    TradingCostConfigSerializer,
)

ViewMethod = TypeVar("ViewMethod", bound=Callable[..., Any])
typed_action = cast(
    Callable[..., Callable[[ViewMethod], ViewMethod]],
    action,
)


def _request_user_id(request: Request) -> int:
    """Return a valid authenticated user id."""

    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise PermissionDenied("用户身份无效")
    return user_id


class AccountProfileView(APIView):
    """
    账户配置 API

    - GET /api/account/profile/ - 获取账户配置
    - PUT /api/account/profile/ - 更新账户配置
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request: Request) -> Response:
        """获取当前用户的账户配置"""
        profile = interface_services.get_api_profile(_request_user_id(request))
        serializer = AccountProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request: Request) -> Response:
        """更新当前用户的账户配置"""
        unknown_fields = set(request.data) - {
            "display_name",
            "risk_tolerance",
            "email",
        }
        if unknown_fields:
            raise ValidationError(
                {"detail": f"不支持的字段: {', '.join(sorted(unknown_fields))}"}
            )
        serializer = AccountProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile_data = dict(serializer.validated_data)
        email = profile_data.pop("email", None)
        profile = interface_services.update_api_profile(
            _request_user_id(request),
            profile_data=profile_data,
            email=email,
        )
        return Response(AccountProfileUpdateSerializer(profile).data)


class MacroSizingConfigView(APIView):
    """
    宏观仓位系数配置 API

    - GET /api/account/macro-sizing-config/ - 读取当前生效配置
    - PATCH /api/account/macro-sizing-config/ - 创建新的生效版本
    - PUT /api/account/macro-sizing-config/ - 创建新的生效版本
    """

    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "GET":
            return [IsAuthenticated(), GeneralPermission()]
        return [IsAuthenticated(), IsAdminUser()]

    def get(self, request: Request) -> Response:
        payload = interface_services.get_macro_sizing_config_payload()
        return Response(MacroSizingConfigSerializer(payload).data)

    def put(self, request: Request) -> Response:
        serializer = MacroSizingConfigUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = interface_services.save_macro_sizing_config_payload(
                validated_data=serializer.validated_data
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(MacroSizingConfigSerializer(payload).data)

    def patch(self, request: Request) -> Response:
        serializer = MacroSizingConfigUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            payload = interface_services.save_macro_sizing_config_payload(
                validated_data=serializer.validated_data
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(MacroSizingConfigSerializer(payload).data)


class AssetMetadataViewSet(viewsets.ReadOnlyModelViewSet[Any]):
    """
    资产元数据 API ViewSet (只读)

    - GET /api/account/assets/ - 获取资产列表
    - GET /api/account/assets/{id}/ - 获取资产详情
    - GET /api/account/assets/by-class/{asset_class}/ - 按类别查询
    """

    serializer_class = AssetMetadataSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> Any:
        """Return the asset metadata queryset via application service."""

        return interface_services.get_asset_metadata_queryset()

    @typed_action(
        detail=False,
        methods=["get"],
        url_path="by-class/(?P<asset_class>[^/]+)",
    )
    def by_class(
        self,
        request: Request,
        asset_class: str | None = None,
    ) -> Response:
        """
        按资产类别查询

        GET /api/account/assets/by-class/{asset_class}/
        """
        assets = self.get_queryset().filter(asset_class=asset_class)
        serializer = AssetMetadataSerializer(assets, many=True)
        return Response({"success": True, "count": assets.count(), "data": serializer.data})


class AccountHealthView(APIView):
    """Account 服务健康检查"""

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request: Request) -> Response:
        """检查 Account 服务健康状态"""
        return Response(
            interface_services.get_account_health_payload(_request_user_id(request))
        )


class UserSearchView(APIView):
    """
    用户搜索 API

    用于协作页面添加观察员时的用户搜索

    - GET /api/account/users/search/?q=xxx - 搜索用户
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request: Request) -> Response:
        """
        搜索用户

        支持按用户名或显示名称搜索
        排除当前用户和已授权的用户
        """
        unknown_params = set(request.query_params) - {"q"}
        if unknown_params:
            raise ValidationError(
                {"detail": f"不支持的查询参数: {', '.join(sorted(unknown_params))}"}
            )
        query = request.query_params.get("q", "").strip()

        if not query or len(query) < 2:
            return Response({"success": True, "results": []})
        if len(query) > 100:
            raise ValidationError({"q": "搜索词不能超过 100 个字符"})

        return Response(
            {
                "success": True,
                "results": interface_services.search_observer_candidates(
                    owner_user_id=_request_user_id(request),
                    query=query,
                ),
            }
        )


class TradingCostConfigViewSet(viewsets.ModelViewSet[Any]):
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

    def get_queryset(self) -> Any:
        """只返回当前用户投资组合的费率配置"""
        return interface_services.get_trading_cost_config_queryset(
            _request_user_id(self.request)
        )

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        if self.action in ["create", "update", "partial_update"]:
            return TradingCostConfigCreateSerializer
        return TradingCostConfigSerializer

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """创建时验证投资组合归属"""
        portfolio = serializer.validated_data["portfolio"]
        user_id = _request_user_id(self.request)
        if portfolio.user_id != user_id:
            raise PermissionDenied("无权为此投资组合配置费率")
        serializer.instance = interface_services.save_api_trading_cost_config(
            actor_user_id=user_id,
            portfolio_id=portfolio.id,
            validated_data={
                "commission_rate": serializer.validated_data["commission_rate"],
                "min_commission": serializer.validated_data["min_commission"],
                "stamp_duty_rate": serializer.validated_data["stamp_duty_rate"],
                "transfer_fee_rate": serializer.validated_data["transfer_fee_rate"],
                "is_active": serializer.validated_data.get("is_active", True),
            },
        )

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        """更新时禁止越权修改配置归属"""
        instance = serializer.instance
        if instance is None:
            raise RuntimeError("交易费用配置更新缺少持久化对象")
        portfolio = serializer.validated_data.get("portfolio", instance.portfolio)
        user_id = _request_user_id(self.request)
        if portfolio.user_id != user_id:
            raise PermissionDenied("无权修改此投资组合的费率")
        serializer.instance = interface_services.save_api_trading_cost_config(
            actor_user_id=user_id,
            portfolio_id=portfolio.id,
            validated_data={
                "commission_rate": serializer.validated_data.get(
                    "commission_rate", instance.commission_rate
                ),
                "min_commission": serializer.validated_data.get(
                    "min_commission", instance.min_commission
                ),
                "stamp_duty_rate": serializer.validated_data.get(
                    "stamp_duty_rate", instance.stamp_duty_rate
                ),
                "transfer_fee_rate": serializer.validated_data.get(
                    "transfer_fee_rate", instance.transfer_fee_rate
                ),
                "is_active": serializer.validated_data.get(
                    "is_active", instance.is_active
                ),
            },
        )

    @typed_action(detail=True, methods=["post"])
    def calculate(self, request: Request, pk: str | None = None) -> Response:
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

        if action_type == "sell":
            cost = config.calculate_sell_cost(amount, is_shanghai)
        else:
            cost = config.calculate_buy_cost(amount, is_shanghai)

        response_data: dict[str, Any] = dict(cost)
        response_data["action"] = action_type
        response_data["amount"] = amount
        response_data["is_shanghai"] = is_shanghai
        response_data["cost_ratio"] = round(cost["total"] / amount * 100, 4)

        return Response({"success": True, "data": response_data})
