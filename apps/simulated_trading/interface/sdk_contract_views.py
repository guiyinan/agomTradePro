"""Dedicated simulated-trading views required by the public SDK contract."""

import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Protocol, TypeVar, cast

from django.db import DatabaseError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionResultUnknown,
)
from apps.simulated_trading.application.manual_trade_execution import (
    ManualSimulatedTradeRequest,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_manual_trade_use_case,
)
from core.exceptions import (
    BusinessLogicError,
    DuplicateResourceError,
    InvalidInputError,
    MissingConfigError,
)

from ._view_helpers import _authenticated_user_id
from .serializers import (
    ClosePositionErrorResponseSerializer,
    ClosePositionRequestSerializer,
    ClosePositionResponseSerializer,
    CloseTradeReceiptResponseSerializer,
    ManualTradeIdempotencyKeySerializer,
    ResetAccountRequestSerializer,
    TradeResponseSerializer,
)

logger = logging.getLogger(__name__)

ViewMethodT = TypeVar("ViewMethodT", bound=Callable[..., Any])


class ExtendSchemaProtocol(Protocol):
    """Typed façade for drf-spectacular's decorator factory."""

    def __call__(self, *args: Any, **kwargs: Any) -> Callable[[ViewMethodT], ViewMethodT]: ...


typed_extend_schema = cast(ExtendSchemaProtocol, extend_schema)

_ACCESS_ERROR_CODES = {
    status.HTTP_401_UNAUTHORIZED: "authentication_required",
    status.HTTP_403_FORBIDDEN: "simulated_account_access_denied",
    status.HTTP_404_NOT_FOUND: "simulated_account_not_found",
}
_SERVICE_EXCEPTIONS = (
    DatabaseError,
    ArithmeticError,
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
)


def _account_access_denial(
    request: Request,
    account_id: int,
    *,
    action: str,
) -> Response | None:
    if isinstance(account_id, bool) or account_id <= 0:
        return Response(
            {"success": False, "error": "simulated_account_id_invalid"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    access = interface_services.get_account_access(
        user=request.user,
        account_id=account_id,
        action=action,
    )
    if access.allowed:
        return None
    status_code = access.status_code
    if not isinstance(status_code, int) or status_code not in _ACCESS_ERROR_CODES:
        status_code = status.HTTP_403_FORBIDDEN
    return Response(
        {"success": False, "error": _ACCESS_ERROR_CODES[status_code]},
        status=status_code,
    )


class PositionCloseAPIView(APIView):
    """Close shares through the exact current-reference simulated ledger."""

    @typed_extend_schema(
        summary="模拟持仓平仓",
        description=(
            "提交明确股数、价格和幂等键的模拟 SELL。成功响应包含持久交易及完整回执；"
            "不代表券商成交。"
        ),
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description="同一平仓请求重试时必须复用的稳定幂等键。",
            )
        ],
        request=ClosePositionRequestSerializer,
        responses={
            200: ClosePositionResponseSerializer,
            401: ClosePositionErrorResponseSerializer,
            400: ClosePositionErrorResponseSerializer,
            403: ClosePositionErrorResponseSerializer,
            404: ClosePositionErrorResponseSerializer,
            409: ClosePositionErrorResponseSerializer,
            422: ClosePositionErrorResponseSerializer,
            503: ClosePositionErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Validate the frozen close intent and delegate it to the manual UOW."""

        denial = _account_access_denial(request, account_id, action="操作")
        if denial is not None:
            return denial

        key_serializer = ManualTradeIdempotencyKeySerializer(
            data={"request_key": request.headers.get("Idempotency-Key", "")}
        )
        request_serializer = ClosePositionRequestSerializer(data=request.data)
        if not key_serializer.is_valid() or not request_serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": "平仓请求无效。",
                    "code": "SIMULATED_TRADE_INPUT_INVALID",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request_serializer.validated_data
        try:
            manual_request = ManualSimulatedTradeRequest(
                account_id=account_id,
                user_id=_authenticated_user_id(request),
                idempotency_key=cast(str, key_serializer.validated_data["request_key"]),
                asset_code=cast(str, data["asset_code"]),
                asset_name=cast(str, data["asset_code"]),
                asset_type="equity",
                side=SimulatedTradeSide.SELL,
                quantity=Decimal(cast(int, data["close_shares"])),
                price=cast(Decimal, data["close_price"]),
                reason=cast(str, data["reason"]),
                signal_id=None,
            )
            result = build_current_reference_manual_trade_use_case().execute(manual_request)
        except SimulatedTradeExecutionResultUnknown as error:
            logger.error(
                "Simulated close readback is unknown; code=%s exception_type=%s",
                error.code,
                type(error).__name__,
            )
            return Response(
                {
                    "success": False,
                    "error": "平仓结果暂无法确认，请使用相同请求和幂等键重试。",
                    "code": error.code,
                    "effects_indeterminate": True,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except DuplicateResourceError as error:
            return Response(
                {
                    "success": False,
                    "error": "该幂等键已绑定到不同的平仓请求。",
                    "code": error.code,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except (InvalidInputError, MissingConfigError) as error:
            return Response(
                {
                    "success": False,
                    "error": "平仓请求或当前证券配置无效。",
                    "code": error.code,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except BusinessLogicError as error:
            return Response(
                {
                    "success": False,
                    "error": "当前账本状态不允许平仓。",
                    "code": error.code,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except DatabaseError as error:
            logger.error(
                "Simulated close database outcome is uncertain; exception_type=%s",
                type(error).__name__,
            )
            return Response(
                {
                    "success": False,
                    "error": "平仓结果暂无法确认，请使用相同请求和幂等键重试。",
                    "code": "SIMULATED_TRADE_EXECUTION_UNAVAILABLE",
                    "effects_indeterminate": True,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ValueError:
            return Response(
                {
                    "success": False,
                    "error": "平仓请求无效。",
                    "code": "SIMULATED_TRADE_INPUT_INVALID",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        trade = result.trade
        receipt = result.receipt
        is_sell = trade.action.value == "sell"
        realized_pnl_known = (
            is_sell
            and trade.cost_basis_known is True
            and trade.fee_amounts_known is True
            and trade.realized_pnl is not None
        )
        realized_pnl_pct_known = realized_pnl_known and trade.realized_pnl_pct is not None
        trade_payload: dict[str, Any] = {
            "trade_id": trade.trade_id,
            "account_id": trade.account_id,
            "asset_code": trade.asset_code,
            "asset_name": trade.asset_name,
            "asset_type": trade.asset_type,
            "action": trade.action.value,
            "quantity": int(trade.quantity),
            "price": str(trade.price),
            "amount": str(trade.amount),
            "commission": str(trade.commission),
            "slippage": str(trade.slippage),
            "total_cost": str(trade.total_cost),
            "fee_amounts_known": trade.fee_amounts_known,
            "fee_amounts_status": trade.fee_amounts_status,
            "cost_basis_known": trade.cost_basis_known,
            "cost_basis_status": trade.cost_basis_status,
            "realized_pnl_known": realized_pnl_known,
            "realized_pnl_status": "known" if realized_pnl_known else "unknown",
            "realized_pnl_pct_known": realized_pnl_pct_known,
            "realized_pnl": str(trade.realized_pnl) if realized_pnl_known else None,
            "realized_pnl_pct": trade.realized_pnl_pct if realized_pnl_pct_known else None,
            "reason": trade.reason,
            "signal_id": trade.signal_id,
            "order_date": trade.order_date,
            "execution_date": trade.execution_date,
            "execution_time": trade.execution_time,
            "status": trade.status.value,
        }
        receipt_payload: dict[str, Any] = {
            "trade_id": receipt.trade_id,
            "account_id": receipt.account_id,
            "idempotency_key": receipt.idempotency_key,
            "request_payload_hash": receipt.request_payload_hash,
            "side": receipt.side.value,
            "asset_code": receipt.asset_code,
            "quantity": receipt.quantity,
            "price": receipt.price,
            "amount": receipt.amount,
            "commission": receipt.commission,
            "transfer_fee": receipt.transfer_fee,
            "stamp_duty": receipt.stamp_duty,
            "slippage": receipt.slippage,
            "total_cost": receipt.total_cost,
            "settlement_status": receipt.settlement_status,
            "settlement_release_date": receipt.settlement_release_date,
            "replayed": receipt.replayed,
        }
        trade_data = TradeResponseSerializer(instance=trade_payload).data
        receipt_data = CloseTradeReceiptResponseSerializer(instance=receipt_payload).data
        return Response(
            {
                "success": True,
                "trade": trade_data,
                "receipt": receipt_data,
                "replayed": receipt.replayed,
            },
            status=status.HTTP_200_OK,
        )


class AccountResetAPIView(APIView):
    """Reset one account ledger while retaining account configuration."""

    def post(self, request: Request, account_id: int) -> Response:
        """Validate and execute one owned-account ledger reset."""

        denial = _account_access_denial(request, account_id, action="重置")
        if denial is not None:
            return denial

        serializer = ResetAccountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            summary = interface_services.reset_account_with_summary(
                account_id=account_id,
                new_initial_capital=serializer.validated_data.get("new_initial_capital"),
            )
        except _SERVICE_EXCEPTIONS as exc:
            logger.warning(
                "Simulated account reset failed; exception_type=%s",
                type(exc).__name__,
            )
            return Response(
                {"success": False, "error": "simulated_account_reset_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if summary is None:
            return Response(
                {"success": False, "error": "simulated_account_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, **summary})
