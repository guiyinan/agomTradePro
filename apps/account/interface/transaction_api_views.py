"""Account transaction and capital flow API views."""

from dataclasses import asdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from django.core.files.uploadedfile import UploadedFile
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import (
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
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

MAX_BROKER_IMPORT_FILE_BYTES = 10 * 1024 * 1024
MAX_TUI_BROKER_IMPORT_TEXT_BYTES = 2 * 1024 * 1024
ALLOWED_BROKER_IMPORT_SUFFIXES = {".csv", ".xlsx", ".xls"}
MAX_TRANSACTION_NOTIONAL = Decimal("999999999999999999.99")
NOTIONAL_QUANTUM = Decimal("0.01")


def _authenticated_user_id(request: Request) -> int:
    """Return the persisted user ID guaranteed by the permission boundary."""
    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise NotAuthenticated("Authenticated user has no persisted ID")
    return user_id


class TransactionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[Any],
):
    """
    交易记录 API ViewSet

    提供以下接口:
    - GET /api/account/transactions/ - 获取交易列表
    - POST /api/account/transactions/ - 创建交易记录
    - GET /api/account/transactions/{id}/ - 获取交易详情
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self) -> Any:
        """只返回当前用户投资组合的交易"""
        return get_user_transaction_queryset(_authenticated_user_id(self.request))

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        """根据操作选择 serializer"""
        if self.action == "create":
            return cast(
                type[serializers.BaseSerializer[Any]],
                TransactionCreateSerializer,
            )
        return cast(type[serializers.BaseSerializer[Any]], TransactionSerializer)

    def perform_create(self, serializer: serializers.BaseSerializer[Any]) -> None:
        """创建时验证持仓归属"""
        user_id = _authenticated_user_id(self.request)
        portfolio = serializer.validated_data.get("portfolio")
        position = serializer.validated_data.get("position")
        portfolio_id = getattr(portfolio, "id", None)
        if isinstance(portfolio_id, bool) or not isinstance(portfolio_id, int):
            raise PermissionDenied("无权为此投资组合创建交易记录")
        if position and getattr(position.portfolio, "user_id", None) != user_id:
            raise PermissionDenied("无权为此持仓创建交易记录")
        if get_user_portfolio(user_id=user_id, portfolio_id=portfolio_id) is None:
            raise PermissionDenied("无权为此投资组合创建交易记录")
        if position and getattr(position, "portfolio_id", None) != portfolio_id:
            raise ValidationError({"position": "持仓不属于该投资组合"})
        asset_code = serializer.validated_data.get("asset_code")
        if position and getattr(position, "asset_code", None) != asset_code:
            raise ValidationError({"asset_code": "资产代码与关联持仓不一致"})

        # 计算成交金额
        shares = serializer.validated_data["shares"]
        price = serializer.validated_data["price"]
        notional = (Decimal(str(shares)) * price).quantize(
            NOTIONAL_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        if not notional.is_finite() or notional > MAX_TRANSACTION_NOTIONAL:
            raise ValidationError({"non_field_errors": "成交金额超出允许范围"})

        serializer.save(notional=notional)


class BrokerTradeImportSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate manual broker trade import requests."""

    portfolio_id = serializers.IntegerField(min_value=1)
    broker_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="manual",
        max_length=64,
        trim_whitespace=True,
    )
    file = serializers.FileField()

    def validate_file(self, value: UploadedFile) -> UploadedFile:
        """Reject unsupported or unbounded broker files before reading them."""
        raw_filename = value.name
        if not isinstance(raw_filename, str) or not raw_filename:
            raise serializers.ValidationError("导入文件名无效")
        filename = raw_filename.lower()
        if not any(filename.endswith(suffix) for suffix in ALLOWED_BROKER_IMPORT_SUFFIXES):
            raise serializers.ValidationError("仅支持 CSV、XLSX 或 XLS 文件")
        if value.size is None or value.size > MAX_BROKER_IMPORT_FILE_BYTES:
            raise serializers.ValidationError("导入文件不能超过 10 MiB")
        return value


class BrokerTradeTuiImportSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate UTF-8 CSV text submitted by the TUI file field."""

    portfolio_id = serializers.IntegerField(min_value=1)
    broker_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="manual",
        max_length=64,
        trim_whitespace=True,
    )
    file = serializers.CharField(
        allow_blank=False,
        trim_whitespace=False,
        max_length=MAX_TUI_BROKER_IMPORT_TEXT_BYTES,
    )

    def validate_file(self, value: str) -> str:
        """Reject text whose encoded payload exceeds the runtime file budget."""

        if len(value.encode("utf-8")) > MAX_TUI_BROKER_IMPORT_TEXT_BYTES:
            raise serializers.ValidationError("CSV 文件不能超过 2 MiB")
        return value


class _BrokerTradeTuiImportBaseView(APIView):
    """Shared TUI boundary for previewing or confirming UTF-8 CSV imports."""

    permission_classes = [IsAuthenticated, TradingPermission]

    preview_only = True

    def post(self, request: Request) -> Response:
        """Run the owner-scoped manual trade import use case."""

        serializer = BrokerTradeTuiImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        use_case = ManualTradeImportUseCase()
        operation = use_case.preview if self.preview_only else use_case.confirm
        try:
            result = operation(
                user_id=_authenticated_user_id(request),
                portfolio_id=data["portfolio_id"],
                broker_name=data.get("broker_name") or "manual",
                filename="tui-manual-trades.csv",
                content=data["file"].encode("utf-8"),
            )
        except LookupError as exc:
            raise PermissionDenied("无权导入该投资组合的券商成交") from exc
        except (TypeError, ValueError) as exc:
            raise ValidationError("CSV 文件格式或内容无效") from exc
        return Response(
            asdict(result),
            status=status.HTTP_200_OK if self.preview_only else status.HTTP_201_CREATED,
        )


class BrokerTradeTuiImportPreviewView(_BrokerTradeTuiImportBaseView):
    """Preview a UTF-8 CSV manual trade file submitted by the TUI."""


class BrokerTradeTuiImportConfirmView(_BrokerTradeTuiImportBaseView):
    """Confirm a UTF-8 CSV manual trade import submitted by the TUI."""

    preview_only = False


class BrokerTradeImportPreviewView(APIView):
    """Preview CSV/XLSX broker trades before importing."""

    permission_classes = [IsAuthenticated, TradingPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request) -> Response:
        serializer = BrokerTradeImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = cast(UploadedFile, serializer.validated_data["file"])
        filename = uploaded_file.name
        if not isinstance(filename, str):
            raise ValidationError("导入文件名无效")
        try:
            result = ManualTradeImportUseCase().preview(
                user_id=_authenticated_user_id(request),
                portfolio_id=serializer.validated_data["portfolio_id"],
                broker_name=serializer.validated_data.get("broker_name") or "manual",
                filename=filename,
                content=uploaded_file.read(),
            )
        except LookupError as exc:
            raise PermissionDenied("无权导入该投资组合的券商成交") from exc
        except (TypeError, ValueError) as exc:
            raise ValidationError("导入文件格式或内容无效") from exc
        return Response(asdict(result), status=status.HTTP_200_OK)


class BrokerTradeImportConfirmView(APIView):
    """Import CSV/XLSX broker trades and sync account positions."""

    permission_classes = [IsAuthenticated, TradingPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request) -> Response:
        serializer = BrokerTradeImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = cast(UploadedFile, serializer.validated_data["file"])
        filename = uploaded_file.name
        if not isinstance(filename, str):
            raise ValidationError("导入文件名无效")
        try:
            result = ManualTradeImportUseCase().confirm(
                user_id=_authenticated_user_id(request),
                portfolio_id=serializer.validated_data["portfolio_id"],
                broker_name=serializer.validated_data.get("broker_name") or "manual",
                filename=filename,
                content=uploaded_file.read(),
            )
        except LookupError as exc:
            raise PermissionDenied("无权导入该投资组合的券商成交") from exc
        except (TypeError, ValueError) as exc:
            raise ValidationError("导入文件格式或内容无效") from exc
        return Response(asdict(result), status=status.HTTP_201_CREATED)


class CapitalFlowViewSet(
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[Any],
):
    """
    资金流水 API ViewSet

    提供以下接口:
    - GET /api/account/capital-flows/ - 获取资金流水列表
    - POST /api/account/capital-flows/ - 创建资金流水
    - GET /api/account/capital-flows/{id}/ - 获取流水详情
    - DELETE /api/account/capital-flows/{id}/ - 删除流水
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self) -> Any:
        """只返回当前用户投资组合的资金流水"""
        return get_user_capital_flow_queryset(_authenticated_user_id(self.request))

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        """根据操作选择 serializer"""
        if self.action == "create":
            return cast(
                type[serializers.BaseSerializer[Any]],
                CapitalFlowCreateSerializer,
            )
        return cast(type[serializers.BaseSerializer[Any]], CapitalFlowSerializer)

    def perform_create(self, serializer: serializers.BaseSerializer[Any]) -> None:
        """创建时验证投资组合归属"""
        portfolio_id = serializer.validated_data.get("portfolio")
        if isinstance(portfolio_id, bool) or not isinstance(portfolio_id, int):
            raise ValidationError({"portfolio": "投资组合 ID 格式无效"})
        user_id = _authenticated_user_id(self.request)
        portfolio = get_user_portfolio(
            user_id=user_id,
            portfolio_id=portfolio_id,
        )
        if portfolio is None:
            raise NotFound()
        serializer.save(portfolio=portfolio, user=self.request.user)
