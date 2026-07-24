"""DRF API Views for Asset Classification and Multi-Currency Support."""

import re
from collections.abc import Callable
from typing import Any, TypeVar, cast

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
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

ViewMethod = TypeVar("ViewMethod", bound=Callable[..., Any])
typed_action = cast(
    Callable[..., Callable[[ViewMethod], ViewMethod]],
    action,
)
CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


def _request_user_id(request: Request) -> int:
    """Return one valid authenticated user id."""

    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise PermissionDenied("用户身份无效")
    return user_id


def _normalize_currency_code(value: str | None, *, field_name: str) -> str:
    """Normalize and validate one currency code from a URL path."""

    normalized = str(value or "").strip().upper()
    if not CURRENCY_CODE_PATTERN.fullmatch(normalized):
        raise ValidationError({field_name: "币种代码格式无效"})
    return normalized


# ==================== Asset Category ViewSet ====================


class AssetCategoryViewSet(viewsets.ModelViewSet[Any]):
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

    def get_queryset(self) -> Any:
        """Return active asset categories through the application layer."""

        return get_asset_category_queryset()

    def get_permissions(self) -> list[BasePermission]:
        """只有管理员可以创建/更新/删除分类"""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """Create asset categories through the application layer."""

        serializer.instance = create_asset_category(validated_data=serializer.validated_data)

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        """Update asset categories through the application layer."""

        try:
            serializer.instance = update_asset_category(
                category_id=self.get_object().id,
                validated_data=serializer.validated_data,
            )
        except ValueError as exc:
            raise ValidationError({"parent": str(exc)}) from exc

    def perform_destroy(self, instance: Any) -> None:
        """Delete asset categories through the application layer."""

        delete_asset_category(category_id=instance.id)

    @typed_action(detail=False, methods=['get'])
    def roots(self, request: Request) -> Response:
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

    @typed_action(detail=False, methods=['get'])
    def tree(self, request: Request) -> Response:
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

    @typed_action(detail=True, methods=['get'])
    def children(self, request: Request, pk: str | None = None) -> Response:
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

class CurrencyViewSet(viewsets.ReadOnlyModelViewSet[Any]):
    """
    币种 API ViewSet (只读)

    - GET /api/account/currencies/ - 获取币种列表
    - GET /api/account/currencies/{id}/ - 获取币种详情
    - GET /api/account/currencies/base/ - 获取基准货币
    """

    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> Any:
        """Return active currencies through the application layer."""

        return get_currency_queryset()

    @typed_action(detail=False, methods=['get'])
    def base(self, request: Request) -> Response:
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

class ExchangeRateViewSet(viewsets.ModelViewSet[Any]):
    """
    汇率 API ViewSet

    提供以下接口:
    - GET /api/account/exchange-rates/ - 获取汇率列表
    - POST /api/account/exchange-rates/ - 创建汇率
    - GET /api/account/exchange-rates/latest/ - 获取最新汇率
    - POST /api/account/exchange-rates/convert/ - 货币转换
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> Any:
        """Return exchange rates through the application layer."""

        return get_exchange_rate_queryset()

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        """根据操作选择 serializer"""
        if self.action == 'create':
            return ExchangeRateCreateSerializer
        return ExchangeRateSerializer

    def get_permissions(self) -> list[BasePermission]:
        """只有管理员可以创建/更新/删除汇率"""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """Create exchange rates through the application layer."""

        serializer.instance = create_exchange_rate(validated_data=serializer.validated_data)

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        """Update exchange rates through the application layer."""

        serializer.instance = update_exchange_rate(
            exchange_rate_id=self.get_object().id,
            validated_data=serializer.validated_data,
        )

    def perform_destroy(self, instance: Any) -> None:
        """Delete exchange rates through the application layer."""

        delete_exchange_rate(exchange_rate_id=instance.id)

    @typed_action(
        detail=False,
        methods=['get'],
        url_path='latest/(?P<from_code>[^/]+)/(?P<to_code>[^/]+)',
    )
    def latest(
        self,
        request: Request,
        from_code: str | None = None,
        to_code: str | None = None,
    ) -> Response:
        """
        获取最新汇率

        GET /api/account/exchange-rates/latest/{from_code}/{to_code}/
        """
        normalized_from = _normalize_currency_code(
            from_code,
            field_name="from_code",
        )
        normalized_to = _normalize_currency_code(
            to_code,
            field_name="to_code",
        )
        rate = get_latest_exchange_rate(
            from_code=normalized_from,
            to_code=normalized_to,
        )
        if not rate:
            return Response({
                'success': False,
                'error': (
                    f'No exchange rate found for '
                    f'{normalized_from} -> {normalized_to}'
                ),
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = ExchangeRateSerializer(rate)
        return Response(serializer.data)

    @typed_action(detail=False, methods=['post'])
    def convert(self, request: Request) -> Response:
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

    def get(self, request: Request, portfolio_id: int) -> Response:
        """
        获取投资组合的资产配置分析

        支持按资产分类和币种进行配置分析
        """
        unknown_params = set(request.query_params) - {"dimension"}
        if unknown_params:
            raise ValidationError(
                {"detail": f"不支持的查询参数: {', '.join(sorted(unknown_params))}"}
            )
        dimension = request.query_params.get('dimension', 'category')
        if dimension not in ("category", "currency"):
            raise ValidationError(
                {"dimension": "必须为 category 或 currency"}
            )
        if portfolio_id <= 0:
            raise ValidationError({"portfolio_id": "必须是正整数"})
        try:
            payload = get_portfolio_allocation_payload(
                portfolio_id=portfolio_id,
                user_id=_request_user_id(request),
                dimension=dimension,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
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
        response_payload: dict[str, Any] = {
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


