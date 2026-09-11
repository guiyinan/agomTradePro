"""Shared typed helpers for simulated trading interface views."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, cast

from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.simulated_trading.application import interface_services as simulated_interface_services
from apps.simulated_trading.domain.entities import SimulatedAccount


class AccountModelProtocol(Protocol):
    """Minimal persisted account contract needed by the HTTP interface."""

    id: int


def _get_owned_account_or_response(
    request: Request, account_id: int, action: str = "访问"
) -> AccountModelProtocol | Response:
    """Return the caller-owned account or a standard error response."""

    result = simulated_interface_services.get_account_access(
        user=request.user,
        account_id=account_id,
        action=action,
    )
    if not result.allowed:
        return Response(
            {"success": False, "error": result.error},
            status=result.status_code,
        )

    return cast(AccountModelProtocol, result.account)


def _delete_account_with_summary(
    account: AccountModelProtocol,
) -> dict[str, Any]:
    """Delete an account and return its cascade summary."""

    return simulated_interface_services.delete_account_with_summary(account.id) or {}


def _parse_iso_date(raw_value: str, *, field_name: str) -> date:
    """Parse an ISO date parameter from a query string or request body."""

    try:
        return date.fromisoformat(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是 YYYY-MM-DD 格式日期") from exc


def _parse_positive_int(raw_value: str | int | None, *, field_name: str, default: int) -> int:
    """Parse a positive integer parameter used by list endpoints."""

    if raw_value is None or raw_value == "":
        return default

    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数") from exc

    if value <= 0:
        raise ValueError(f"{field_name} 必须大于 0")

    return value


def _authenticated_user_id(request: Request) -> int:
    """Return a persisted authenticated user ID or fail closed."""

    user_id = getattr(request.user, "id", None)
    if user_id is None:
        raise NotAuthenticated("请先登录后再操作账户")
    return int(user_id)


def _account_payload(account: SimulatedAccount, *, newly_created: bool = False) -> dict[str, Any]:
    """Serialize canonical account fields shared by public endpoints."""

    created_at = getattr(account, "created_at", None)
    return {
        "account_id": account.account_id,
        "account_name": account.account_name,
        "account_type": account.account_type.value,
        "initial_capital": str(account.initial_capital),
        "current_cash": str(account.current_cash),
        "current_market_value": str(account.current_market_value),
        "total_value": str(account.total_value),
        "total_return": None if newly_created else account.total_return,
        "annual_return": None if newly_created else account.annual_return,
        "max_drawdown": None if newly_created else account.max_drawdown,
        "sharpe_ratio": None if newly_created else account.sharpe_ratio,
        "win_rate": None if newly_created else account.win_rate,
        "max_position_pct": account.max_position_pct,
        "stop_loss_pct": account.stop_loss_pct,
        "commission_rate": account.commission_rate,
        "slippage_rate": account.slippage_rate,
        "total_trades": account.total_trades,
        "winning_trades": account.winning_trades,
        "is_active": account.is_active,
        "auto_trading_enabled": account.auto_trading_enabled,
        "start_date": account.start_date.isoformat(),
        "last_trade_date": (
            None
            if newly_created or account.last_trade_date is None
            else account.last_trade_date.isoformat()
        ),
        "created_at": (None if newly_created or created_at is None else created_at.isoformat()),
    }
