"""Read-only portfolio API views for simulated trading."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application import interface_services as simulated_interface_services
from apps.simulated_trading.application.use_cases import GetAccountPerformanceUseCase

from ._view_helpers import (
    _account_payload,
    _get_owned_account_or_response,
    _parse_iso_date,
    _parse_positive_int,
)
from .serializers import (
    PerformanceResponseSerializer,
    PositionListResponseSerializer,
    TradeListResponseSerializer,
)

ViewMethodT = TypeVar("ViewMethodT", bound=Callable[..., Any])


class ExtendSchemaProtocol(Protocol):
    """Typed façade for drf-spectacular's decorator factory."""

    def __call__(self, *args: Any, **kwargs: Any) -> Callable[[ViewMethodT], ViewMethodT]: ...


typed_extend_schema = cast(ExtendSchemaProtocol, extend_schema)


class PositionListAPIView(APIView):
    """持仓列表 API。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.account_repo = simulated_interface_services.get_account_repository()
        self.position_repo = simulated_interface_services.get_position_repository()

    @typed_extend_schema(
        summary="获取账户持仓列表",
        description="获取指定账户的所有持仓",
        responses={200: PositionListResponseSerializer},
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Return all positions belonging to one visible account."""

        account_model = _get_owned_account_or_response(request, account_id, action="查看")
        if isinstance(account_model, Response):
            return account_model

        account = self.account_repo.get_by_id(account_id)
        if not account:
            return Response(
                {"success": False, "error": f"账户不存在: {account_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        positions = self.position_repo.get_by_account(account_id)
        position_list = [
            {
                "position_id": getattr(pos, "position_id", None),
                "account_id": pos.account_id,
                "asset_code": pos.asset_code,
                "asset_name": pos.asset_name,
                "asset_type": pos.asset_type,
                "quantity": pos.quantity,
                "available_quantity": pos.available_quantity,
                "avg_cost": str(pos.avg_cost),
                "total_cost": str(pos.total_cost),
                "current_price": str(pos.current_price),
                "market_value": str(pos.market_value),
                "unrealized_pnl": str(pos.unrealized_pnl),
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "first_buy_date": pos.first_buy_date.isoformat(),
                "last_update_date": pos.last_update_date.isoformat(),
                "signal_id": pos.signal_id,
                "entry_reason": pos.entry_reason,
            }
            for pos in positions
        ]
        return Response(
            {
                "success": True,
                "account_id": account_id,
                "account_name": account.account_name,
                "total_positions": len(position_list),
                "total_market_value": str(account.current_market_value),
                "positions": position_list,
            }
        )


class TradeListAPIView(APIView):
    """交易记录列表 API。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.account_repo = simulated_interface_services.get_account_repository()
        self.trade_repo = simulated_interface_services.get_trade_repository()

    @typed_extend_schema(
        summary="获取账户交易记录",
        description="获取指定账户的交易记录（支持过滤）",
        parameters=[
            OpenApiParameter(
                name="start_date", type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                name="end_date", type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                name="asset_code", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(name="action", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
        ],
        responses={200: TradeListResponseSerializer},
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Return filtered trade records and aggregate counts."""

        account_model = _get_owned_account_or_response(request, account_id, action="查看")
        if isinstance(account_model, Response):
            return account_model

        account = self.account_repo.get_by_id(account_id)
        if not account:
            return Response(
                {"success": False, "error": f"账户不存在: {account_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        all_trades = self.trade_repo.get_by_account(account_id)
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        asset_code = request.query_params.get("asset_code")
        action = request.query_params.get("action")
        try:
            limit = _parse_positive_int(
                request.query_params.get("limit"), field_name="limit", default=100
            )
            parsed_start_date = (
                _parse_iso_date(start_date, field_name="start_date") if start_date else None
            )
            parsed_end_date = _parse_iso_date(end_date, field_name="end_date") if end_date else None
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
            return Response(
                {"success": False, "error": "start_date 不能晚于 end_date"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        filtered_trades = []
        for trade in all_trades:
            if parsed_start_date and trade.execution_date < parsed_start_date:
                continue
            if parsed_end_date and trade.execution_date > parsed_end_date:
                continue
            if asset_code and trade.asset_code != asset_code:
                continue
            if action and trade.action.value != action:
                continue
            filtered_trades.append(trade)

        buy_count = sum(1 for trade in filtered_trades if trade.action.value == "buy")
        sell_count = sum(1 for trade in filtered_trades if trade.action.value == "sell")
        total_pnl = sum(trade.realized_pnl or 0 for trade in filtered_trades)
        trade_list = [
            {
                "trade_id": trade.trade_id,
                "account_id": trade.account_id,
                "asset_code": trade.asset_code,
                "asset_name": trade.asset_name,
                "asset_type": trade.asset_type,
                "action": trade.action.value,
                "quantity": trade.quantity,
                "price": str(trade.price),
                "amount": str(trade.amount),
                "commission": str(trade.commission),
                "slippage": str(trade.slippage),
                "total_cost": str(trade.total_cost),
                "realized_pnl": (
                    str(trade.realized_pnl) if trade.realized_pnl is not None else None
                ),
                "realized_pnl_pct": trade.realized_pnl_pct,
                "reason": trade.reason,
                "signal_id": trade.signal_id,
                "order_date": trade.order_date.isoformat(),
                "execution_date": trade.execution_date.isoformat(),
                "execution_time": trade.execution_time.isoformat(),
                "status": trade.status.value,
            }
            for trade in filtered_trades[:limit]
        ]
        return Response(
            {
                "success": True,
                "account_id": account_id,
                "account_name": account.account_name,
                "total_trades": len(filtered_trades),
                "total_buy_count": buy_count,
                "total_sell_count": sell_count,
                "total_realized_pnl": str(total_pnl),
                "trades": trade_list,
            }
        )


class PerformanceAPIView(APIView):
    """绩效分析 API。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.account_repo = simulated_interface_services.get_account_repository()
        self.position_repo = simulated_interface_services.get_position_repository()
        self.trade_repo = simulated_interface_services.get_trade_repository()

    @typed_extend_schema(
        summary="获取账户绩效",
        description="获取账户的完整绩效分析",
        responses={200: PerformanceResponseSerializer},
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Return the account performance summary."""

        account_model = _get_owned_account_or_response(request, account_id, action="查看")
        if isinstance(account_model, Response):
            return account_model

        use_case = GetAccountPerformanceUseCase(
            self.account_repo, self.position_repo, self.trade_repo
        )
        try:
            result = use_case.execute(account_id)
            return Response(
                {
                    "success": True,
                    "account": _account_payload(result["account"]),
                    "total_positions": result["total_positions"],
                    "total_trades": result["total_trades"],
                    "winning_trades": result["winning_trades"],
                    "win_rate": result["win_rate"],
                    "performance": result["performance"],
                }
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )


__all__ = [
    "PerformanceAPIView",
    "PositionListAPIView",
    "TradeListAPIView",
]
