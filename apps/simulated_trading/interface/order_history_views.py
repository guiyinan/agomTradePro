"""Read-only authenticated endpoints for retained simulated orders and fills."""

from __future__ import annotations

import logging
from typing import Protocol, cast

from django.db import DatabaseError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.order_history import (
    OrderFillHistoryPage,
    OrderHistoryFill,
    OrderHistoryOrder,
    OrderHistoryPage,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus
from apps.simulated_trading.order_history_composition import (
    build_read_order_history_use_case,
)

from .order_history_serializers import (
    OrderFillsResponseSerializer,
    OrderHistoryQuerySerializer,
    OrderHistoryResponseSerializer,
)
from .sdk_contract_views import typed_extend_schema

logger = logging.getLogger(__name__)

_ORDER_QUERY_FIELDS = frozenset(("limit", "cursor"))
_RECEIPT_SCOPE_NOTE = "本页仅列已留存且完成单条核对的成交回执；空列表不能证明从未成交。"


class _AuthenticatedActor(Protocol):
    """The identity fields the history interface reads from the request principal."""

    id: int | None
    is_authenticated: bool
    is_active: bool


class SimulatedOrderHistoryAPIView(APIView):
    """List every reservation state for the authenticated simulated-account owner."""

    permission_classes = [IsAuthenticated]

    @typed_extend_schema(
        summary="读取本人模拟订单历史",
        description="只读订单预留快照，不触发撮合、成交或资源释放。",
        parameters=[
            OpenApiParameter("account_id", OpenApiTypes.INT, OpenApiParameter.PATH),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("cursor", OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
        responses={200: OrderHistoryResponseSerializer},
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Return an owner-filtered order page and two distinct read timestamps."""

        actor_id = _request_actor_id(request)
        if isinstance(actor_id, Response):
            return actor_id
        if not _only_query_fields(request, _ORDER_QUERY_FIELDS):
            return _input_error("仅允许 limit 和 cursor 分页参数")
        query = OrderHistoryQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return _input_error("订单历史分页参数无效")
        values = query.validated_data
        try:
            page = build_read_order_history_use_case().read_orders(
                account_id=account_id,
                user_id=actor_id,
                limit=cast(int, values.get("limit", 50)),
                cursor=cast(str | None, values.get("cursor")),
            )
        except SimulatedTradeAccountScopeUnavailable:
            return _not_found()
        except SimulatedTradeExecutionInputError as error:
            return _input_error(error.message, code=error.code)
        except SimulatedTradeExecutionBlocked as error:
            return _blocked(error)
        except DatabaseError:
            logger.exception("Order history read database failure")
            return _database_unavailable()
        payload = _orders_payload(page)
        return Response(payload, status=status.HTTP_200_OK)


class SimulatedOrderFillHistoryAPIView(APIView):
    """List only persisted receipts whose exact Reservation/Receipt/Trade rows verify."""

    permission_classes = [IsAuthenticated]

    @typed_extend_schema(
        summary="读取本人订单的原成交回执",
        description=(
            "仅校验已持久化的单条回执；不读取撮合来源或日历，不调用成交应用，"
            "也不宣称完整费用资源链已验证。"
        ),
        parameters=[
            OpenApiParameter("account_id", OpenApiTypes.INT, OpenApiParameter.PATH),
            OpenApiParameter("order_id", OpenApiTypes.INT, OpenApiParameter.PATH),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("cursor", OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
        responses={200: OrderFillsResponseSerializer},
    )
    def get(self, request: Request, account_id: int, order_id: int) -> Response:
        """Read exact fill receipts by public order number without source access."""

        actor_id = _request_actor_id(request)
        if isinstance(actor_id, Response):
            return actor_id
        if not _only_query_fields(request, _ORDER_QUERY_FIELDS):
            return _input_error("仅允许 limit 和 cursor 分页参数")
        query = OrderHistoryQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return _input_error("成交回执分页参数无效")
        values = query.validated_data
        try:
            page = build_read_order_history_use_case().read_fills(
                account_id=account_id,
                user_id=actor_id,
                order_id=order_id,
                limit=cast(int, values.get("limit", 50)),
                cursor=cast(str | None, values.get("cursor")),
            )
        except SimulatedTradeAccountScopeUnavailable:
            return _not_found()
        except SimulatedTradeExecutionInputError as error:
            return _input_error(error.message, code=error.code)
        except SimulatedTradeExecutionBlocked as error:
            return _blocked(error)
        except DatabaseError:
            logger.exception("Order fill history read database failure")
            return _database_unavailable()
        payload = _fills_payload(page)
        return Response(payload, status=status.HTTP_200_OK)


def _request_actor_id(request: Request) -> int | Response:
    """Require the exact authenticated active principal without staff substitution."""

    actor = cast(_AuthenticatedActor, request.user)
    if actor.is_authenticated is not True:
        return Response(
            {"success": False, "error": "请先登录", "code": "NOT_AUTHENTICATED"},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if type(actor.id) is not int or actor.id <= 0:
        return _input_error("当前用户身份不可验证", status_code=status.HTTP_401_UNAUTHORIZED)
    if actor.is_active is not True:
        return Response(
            {"success": False, "error": "当前用户不可用", "code": "ACTOR_INACTIVE"},
            status=status.HTTP_403_FORBIDDEN,
        )
    return actor.id


def _only_query_fields(request: Request, allowed: frozenset[str]) -> bool:
    """Reject caller-supplied owner IDs, cutoff clocks, and unknown query keys."""

    return set(request.query_params.keys()).issubset(allowed)


def _orders_payload(page: OrderHistoryPage) -> dict[str, object]:
    """Build the stable whitelisted orders response with exact Decimal strings."""

    return {
        "success": True,
        "account_id": page.account_id,
        "orders": [_order_payload(item) for item in page.orders],
        "has_more": page.has_more,
        "next_cursor": page.next_cursor,
        "membership_cutoff": page.membership_cutoff.isoformat(),
        "read_at": page.read_at.isoformat(),
    }


def _order_payload(item: OrderHistoryOrder) -> dict[str, object]:
    """Render only the public reservation columns."""

    return {
        "order_id": item.order_id,
        "asset_code": item.asset_code,
        "asset_name": item.asset_name,
        "side": _side_value(item.side),
        "status": _status_value(item.status),
        "quantity": str(item.quantity),
        "filled_quantity": str(item.filled_quantity),
        "limit_price": str(item.limit_price),
        "remaining_cash": str(item.remaining_cash),
        "remaining_shares": str(item.remaining_shares),
        "reserved_at": item.reserved_at.isoformat(),
    }


def _fills_payload(page: OrderFillHistoryPage) -> dict[str, object]:
    """Build the receipt-only response without implying chain or execution status."""

    return {
        "success": True,
        "account_id": page.account_id,
        "order_id": page.order_id,
        "fills": [_fill_payload(item) for item in page.fills],
        "has_more": page.has_more,
        "next_cursor": page.next_cursor,
        "membership_cutoff": page.membership_cutoff.isoformat(),
        "read_at": page.read_at.isoformat(),
        "receipt_scope_note": _RECEIPT_SCOPE_NOTE,
    }


def _fill_payload(item: OrderHistoryFill) -> dict[str, object]:
    """Render one verified receipt and preserve the explicit timing basis."""

    return {
        "receipt_id": item.receipt_id,
        "trade_id": item.trade_id,
        "order_id": item.order_id,
        "fill_sequence": item.fill_sequence,
        "asset_code": item.asset_code,
        "side": _side_value(item.side),
        "quantity": str(item.quantity),
        "price": str(item.price),
        "occurred_at": item.occurred_at.isoformat(),
        "recorded_at": item.recorded_at.isoformat(),
        "observation_basis": item.observation_basis,
        "verification_status": item.verification_status,
    }


def _side_value(side: SimulatedTradeSide) -> str:
    """Return one validated side string."""

    return side.value


def _status_value(value: OrderReservationStatus) -> str:
    """Return one validated reservation lifecycle state."""

    return value.value


def _input_error(
    message: str,
    *,
    code: str = "ORDER_HISTORY_INPUT_INVALID",
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> Response:
    """Return a stable input response without exposing query internals."""

    return Response(
        {"success": False, "error": message, "code": code},
        status=status_code,
    )


def _not_found() -> Response:
    """Hide foreign order existence behind one owner-scope response."""

    return Response(
        {"success": False, "error": "未找到本人模拟订单", "code": "ORDER_HISTORY_NOT_FOUND"},
        status=status.HTTP_404_NOT_FOUND,
    )


def _blocked(error: SimulatedTradeExecutionBlocked) -> Response:
    """Return a conflict without disclosing stored source or seal contents."""

    return Response(
        {
            "success": False,
            "error": "订单历史无法精确核对",
            "code": error.code,
        },
        status=status.HTTP_409_CONFLICT,
    )


def _database_unavailable() -> Response:
    """Return a stable service-unavailable response for history storage failures."""

    return Response(
        {"success": False, "error": "订单历史暂不可用", "code": "ORDER_HISTORY_UNAVAILABLE"},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


__all__ = ("SimulatedOrderFillHistoryAPIView", "SimulatedOrderHistoryAPIView")
