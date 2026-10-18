"""simulated_trading runtime capability handlers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, cast

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_simulated_trading_read_daily_inspection_list(
    account_id: int,
    limit: int = 20,
    inspection_date: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    if limit < 1:
        raise ValueError("limit must be greater than zero.")

    parsed_date = date.fromisoformat(inspection_date) if inspection_date else None
    client = AgomTradeProClient()
    response = client.simulated_trading.list_daily_inspections(
        account_id=account_id,
        limit=limit,
        inspection_date=parsed_date,
    )
    reports = response.get("reports", []) if isinstance(response, dict) else response
    return {
        "account_id": account_id,
        "reports": reports,
        "total_count": len(reports),
        "query": {
            "limit": limit,
            "inspection_date": inspection_date,
        },
    }


def _fallback_execute_simulated_trade(
    account_id: int,
    asset_code: str,
    side: str,
    quantity: float,
    price: float | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.simulated_trading.execute_trade(account_id, asset_code, side, quantity, price)


def _fallback_close_simulated_position(
    account_id: int,
    asset_code: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.simulated_trading.close_position(account_id, asset_code)


def _fallback_reset_simulated_account(
    account_id: int,
    new_initial_capital: float | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.simulated_trading.reset_account(account_id, new_initial_capital)


def _fallback_delete_simulated_account(
    account_id: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.simulated_trading.delete_account(account_id)


def _fallback_batch_delete_simulated_accounts(
    account_ids: list[int],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.simulated_trading.batch_delete_accounts(account_ids)


def _fallback_create_simulated_account(
    account_name: str,
    initial_capital: float,
    max_position_pct: float = 20.0,
    stop_loss_pct: float | None = 10.0,
    commission_rate: float = 0.0003,
    slippage_rate: float = 0.001,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Forward a governed creation identity to the canonical API unchanged."""

    if idempotency_key is None:
        raise ValueError("idempotency_key is required for account creation")
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.simulated_trading.create_account(
        name=account_name,
        initial_capital=initial_capital,
        start_date=None,
        account_type="simulated",
        max_position_pct=max_position_pct,
        stop_loss_pct=stop_loss_pct,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        idempotency_key=idempotency_key,
    )


def _fallback_run_simulated_auto_trading(
    trade_date: str | None = None,
    account_ids: list[int] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    parsed_date = date.fromisoformat(trade_date) if trade_date else None
    return client.simulated_trading.run_auto_trading(
        trade_date=parsed_date,
        account_ids=account_ids,
    )


def _fallback_run_simulated_daily_inspection(
    account_id: int,
    strategy_id: int | None = None,
    inspection_date: str | None = None,
    auto_create_proposal: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    parsed_date = date.fromisoformat(inspection_date) if inspection_date else None
    return client.simulated_trading.run_daily_inspection(
        account_id=account_id,
        strategy_id=strategy_id,
        inspection_date=parsed_date,
        auto_create_proposal=auto_create_proposal,
    )


def _internal_handler_trading_submit_simulated_order(
    account_id: int,
    asset_code: str,
    side: str,
    quantity: float,
    price: float | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    normalized_side = str(side or "").strip().lower()
    normalized_asset_code = str(asset_code or "").strip()

    if preview_only:
        account = client.simulated_trading.get_account(account_id)
        positions = client.simulated_trading.get_positions(
            account_id=account_id,
            asset_code=normalized_asset_code or None,
        )
        position = positions[0] if positions else {}
        total_value = (
            account.get("total_value")
            or account.get("market_value")
            or account.get("current_value")
        )
        available_cash = (
            account.get("available_cash") or account.get("cash") or account.get("available_amount")
        )
        current_quantity = (
            position.get("quantity") or position.get("shares") or position.get("position") or 0
        )
        average_cost = position.get("avg_cost") or position.get("average_cost")
        return {
            "success": True,
            "preview_only": True,
            "account_id": account_id,
            "asset_code": normalized_asset_code or None,
            "side": normalized_side or None,
            "quantity": quantity,
            "price": price,
            "account_summary": {
                "account_name": account.get("name") or account.get("account_name"),
                "status": account.get("status"),
                "account_type": account.get("account_type"),
                "total_value": total_value,
                "available_cash": available_cash,
            },
            "position_summary": {
                "matched_position_count": len(positions),
                "current_quantity": current_quantity,
                "average_cost": average_cost,
            },
            "trade_summary": {
                "asset_code": normalized_asset_code or None,
                "side": normalized_side or None,
                "quantity": quantity,
                "price": price,
            },
            "message": (
                "Preview generated. Confirm to execute the simulated trading order "
                "against the selected account."
            ),
        }

    return cast(
        dict[str, Any],
        _call_registered_tool(
            "execute_simulated_trade",
            {
                "account_id": account_id,
                "asset_code": normalized_asset_code,
                "side": normalized_side,
                "quantity": quantity,
                "price": price,
            },
        ),
    )


def _internal_handler_trading_close_simulated_position(
    account_id: int,
    asset_code: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    normalized_asset_code = str(asset_code or "").strip()

    if preview_only:
        account = client.simulated_trading.get_account(account_id)
        positions = client.simulated_trading.get_positions(
            account_id=account_id,
            asset_code=normalized_asset_code or None,
        )
        position = positions[0] if positions else {}
        current_quantity = (
            position.get("quantity") or position.get("shares") or position.get("position") or 0
        )
        average_cost = position.get("avg_cost") or position.get("average_cost")
        return {
            "success": True,
            "preview_only": True,
            "account_id": account_id,
            "asset_code": normalized_asset_code or None,
            "account_summary": {
                "account_name": account.get("name") or account.get("account_name"),
                "status": account.get("status"),
                "account_type": account.get("account_type"),
            },
            "position_summary": {
                "matched_position_count": len(positions),
                "current_quantity": current_quantity,
                "average_cost": average_cost,
            },
            "target_status": "closed",
            "message": (
                "Preview generated. Confirm to close the simulated position from the "
                "selected account."
            ),
        }

    return cast(
        dict[str, Any],
        _call_registered_tool(
            "close_simulated_position",
            {
                "account_id": account_id,
                "asset_code": normalized_asset_code,
            },
        ),
    )


def _internal_handler_trading_reset_simulated_account(
    account_id: int,
    new_initial_capital: float | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        account = client.simulated_trading.get_account(account_id)
        current_initial_capital = (
            account.get("initial_capital")
            or account.get("starting_capital")
            or account.get("principal")
        )
        total_value = (
            account.get("total_value")
            or account.get("market_value")
            or account.get("current_value")
        )
        return {
            "success": True,
            "preview_only": True,
            "account_id": account_id,
            "account_summary": {
                "account_name": account.get("name") or account.get("account_name"),
                "status": account.get("status"),
                "account_type": account.get("account_type"),
                "initial_capital": current_initial_capital,
                "total_value": total_value,
            },
            "reset_summary": {
                "current_initial_capital": current_initial_capital,
                "new_initial_capital": new_initial_capital,
            },
            "message": (
                "Preview generated. Confirm to reset the simulated account and replace "
                "its current capital baseline."
            ),
        }

    return cast(
        dict[str, Any],
        _call_registered_tool(
            "reset_simulated_account",
            {
                "account_id": account_id,
                "new_initial_capital": new_initial_capital,
            },
        ),
    )


def _internal_handler_trading_delete_simulated_account(
    account_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        account = client.simulated_trading.get_account(account_id)
        return {
            "success": True,
            "preview_only": True,
            "account_id": account_id,
            "account_summary": {
                "account_name": account.get("name") or account.get("account_name"),
                "account_type": account.get("account_type"),
                "status": account.get("status"),
                "is_active": account.get("is_active"),
                "initial_capital": account.get("initial_capital"),
                "current_cash": account.get("current_cash") or account.get("cash"),
                "total_value": account.get("total_value") or account.get("market_value"),
            },
            "target_status": "deleted",
            "message": (
                "Preview generated. Confirm to delete the selected simulated trading account."
            ),
        }

    return cast(
        dict[str, Any],
        _call_registered_tool(
            "delete_simulated_account",
            {
                "account_id": account_id,
            },
        ),
    )


def _internal_handler_trading_delete_simulated_account_batch(
    account_ids: list[int],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient
    from agomtradepro.exceptions import AgomTradeProAPIError

    client = AgomTradeProClient()
    normalized_account_ids = list(account_ids)

    if preview_only:
        sample_accounts: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for account_id in normalized_account_ids:
            try:
                account = client.simulated_trading.get_account(account_id)
            except AgomTradeProAPIError as exc:
                error_message = exc.message
                if isinstance(exc.response, dict):
                    error_message = (
                        exc.response.get("error") or exc.response.get("detail") or error_message
                    )
                failure_summary = {
                    "account_id": account_id,
                    "error": error_message,
                }
                if exc.status_code is not None:
                    failure_summary["status_code"] = exc.status_code
                failed.append(failure_summary)
                continue

            if len(sample_accounts) < 10:
                sample_accounts.append(
                    {
                        "account_id": account.get("id") or account.get("account_id") or account_id,
                        "account_name": account.get("name") or account.get("account_name"),
                        "account_type": account.get("account_type"),
                        "status": account.get("status"),
                        "is_active": account.get("is_active"),
                        "initial_capital": account.get("initial_capital"),
                        "current_cash": account.get("current_cash") or account.get("cash"),
                        "total_value": account.get("total_value") or account.get("market_value"),
                    }
                )

        deletable_count = len(normalized_account_ids) - len(failed)
        partial_failure_risk = len(failed) > 0
        return {
            "success": True,
            "preview_only": True,
            "account_ids": normalized_account_ids,
            "delete_summary": {
                "requested_count": len(normalized_account_ids),
                "deletable_count": deletable_count,
                "failed_count": len(failed),
                "sample_accounts": sample_accounts,
            },
            "failed": failed,
            "partial_failure_risk": partial_failure_risk,
            "target_status": "deleted",
            "message": (
                "Preview generated. Confirm to batch delete the resolved simulated trading "
                "accounts. Some requested accounts may still fail if they are missing or "
                "not accessible."
                if partial_failure_risk
                else "Preview generated. Confirm to batch delete the resolved simulated trading accounts."
            ),
        }

    return cast(
        dict[str, Any],
        _call_registered_tool(
            "batch_delete_simulated_accounts",
            {
                "account_ids": normalized_account_ids,
            },
        ),
    )


def _internal_handler_trading_create_simulated_account(
    account_name: str,
    initial_capital: float,
    max_position_pct: float = 20.0,
    stop_loss_pct: float | None = 10.0,
    commission_rate: float = 0.0003,
    slippage_rate: float = 0.001,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Preview creation or commit it with the caller's stable request identity."""
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        existing_accounts = client.simulated_trading.list_accounts(
            status="active",
            account_type="simulated",
            limit=100,
        )
        matching_name_count = 0
        for account in existing_accounts:
            if not isinstance(account, dict):
                continue
            existing_account_name = account.get("name") or account.get("account_name")
            if existing_account_name == account_name:
                matching_name_count += 1

        return {
            "success": True,
            "preview_only": True,
            "create_summary": {
                "account_name": account_name,
                "account_type": "simulated",
                "initial_capital": initial_capital,
                "max_position_pct": max_position_pct,
                "stop_loss_pct": stop_loss_pct,
                "commission_rate": commission_rate,
                "slippage_rate": slippage_rate,
                "matching_active_name_count": matching_name_count,
            },
            "message": (
                "Preview generated. Confirm to create the simulated trading account "
                "with the requested risk settings."
            ),
        }

    return _fallback_create_simulated_account(
        account_name=account_name,
        initial_capital=initial_capital,
        max_position_pct=max_position_pct,
        stop_loss_pct=stop_loss_pct,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        idempotency_key=idempotency_key,
    )


_MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE = 10_000


def _normalize_simulated_auto_trading_account_ids(account_ids: object) -> list[int] | None:
    """Validate an optional ordered account ID list at the MCP boundary."""

    if account_ids is None:
        return None
    if type(account_ids) is not list:
        raise ValueError("account_ids must be a list of positive integers or omitted.")
    if len(account_ids) > _MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE:
        raise ValueError("account_ids exceeds the supported simulated account scope size.")
    normalized: list[int] = []
    seen: set[int] = set()
    for account_id in account_ids:
        if type(account_id) is not int or account_id <= 0:
            raise ValueError("account_ids must contain only positive integers.")
        if account_id in seen:
            raise ValueError("account_ids must not contain duplicates.")
        seen.add(account_id)
        normalized.append(account_id)
    return normalized


def _validate_simulated_auto_trading_account(
    account: object,
    *,
    expected_account_id: int | None,
    require_auto_trading: bool,
) -> dict[str, Any]:
    """Validate an account record and return its safe preview summary."""

    if type(account) is not dict:
        raise ValueError("The account service returned a malformed account record.")
    account_id = account.get("account_id")
    account_name = account.get("account_name")
    account_type = account.get("account_type")
    is_active = account.get("is_active")
    auto_enabled = account.get("auto_trading_enabled")
    if type(account_id) is not int or account_id <= 0:
        raise ValueError("The account service returned an invalid account ID.")
    if expected_account_id is not None and account_id != expected_account_id:
        raise ValueError("The account service returned a different account than requested.")
    if type(account_name) is not str or not account_name.strip():
        raise ValueError("The account service returned an invalid account name.")
    if account_type != "simulated" or is_active is not True:
        raise ValueError("The requested account is not an active simulated account.")
    if type(auto_enabled) is not bool:
        raise ValueError("The account service did not confirm auto-trading eligibility.")
    if require_auto_trading and not auto_enabled:
        raise ValueError("The requested account is not enabled for auto-trading.")
    return {
        "account_id": account_id,
        "account_name": account_name,
        "account_type": account_type,
        "is_active": is_active,
        "auto_trading_enabled": auto_enabled,
    }


def _simulated_auto_trading_scope_digest(account_ids: list[int]) -> str:
    """Hash the ordered canonical JSON representation of resolved IDs."""

    canonical = json.dumps(account_ids, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _internal_handler_trading_start_simulated_auto_trading(
    trade_date: str | None = None,
    account_ids: list[int] | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Preview or submit an owner-scoped simulated auto-trading request."""

    normalized = _normalize_simulated_auto_trading_account_ids(account_ids)
    if not preview_only and normalized is None:
        raise ValueError("A confirmed request requires frozen account IDs.")

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    if preview_only:
        summaries: list[dict[str, Any]] = []
        source_count = 0
        if normalized is None:
            envelope = client.simulated_trading.list_accounts_envelope(
                status="active",
                account_type="simulated",
                limit=_MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE,
            )
            if type(envelope) is not dict or set(envelope) != {"success", "count", "accounts"}:
                raise ValueError(
                    "The account service returned an incomplete account list envelope."
                )
            count, accounts = envelope.get("count"), envelope.get("accounts")
            if envelope.get("success") is not True:
                raise ValueError("The account service could not resolve the default scope.")
            if type(count) is not int or count < 0:
                raise ValueError("The account service returned an invalid account count.")
            if type(accounts) is not list or len(accounts) != count:
                raise ValueError("The account service returned an incomplete account list.")
            source_count = count
            seen: set[int] = set()
            for row in accounts:
                summary = _validate_simulated_auto_trading_account(
                    row, expected_account_id=None, require_auto_trading=False
                )
                account_id = cast(int, summary["account_id"])
                if account_id in seen:
                    raise ValueError("The account service returned duplicate account IDs.")
                seen.add(account_id)
                if summary["auto_trading_enabled"] is True:
                    summaries.append(summary)
            resolved = [cast(int, row["account_id"]) for row in summaries]
            scope_mode = "default"
        elif normalized:
            for account_id in normalized:
                row = client.simulated_trading.get_account(account_id)
                summaries.append(
                    _validate_simulated_auto_trading_account(
                        row, expected_account_id=account_id, require_auto_trading=True
                    )
                )
            resolved = list(normalized)
            source_count = len(summaries)
            scope_mode = "explicit"
        else:
            resolved = []
            scope_mode = "empty"

        if len(resolved) > _MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE:
            raise ValueError("The resolved simulated account scope exceeds the supported size.")

        scope_summary: dict[str, Any] = {
            "scope_mode": scope_mode,
            "requested_account_count": None if normalized is None else len(normalized),
            "source_account_count": source_count,
            "resolved_account_count": len(resolved),
            "resolved_account_ids_sha256": _simulated_auto_trading_scope_digest(resolved),
            "sample_accounts": summaries[:10],
        }
        return {
            "success": True,
            "preview_only": True,
            "trade_date": trade_date,
            "account_ids": normalized,
            "resolved_account_ids": list(resolved),
            "account_scope_summary": scope_summary,
            "message": (
                "Preview generated. Confirm to trigger simulated auto-trading for the "
                "resolved account scope."
            ),
        }

    if normalized is None:
        raise ValueError("A confirmed request requires frozen account IDs.")

    return cast(
        dict[str, Any],
        _call_registered_tool(
            "run_simulated_auto_trading",
            {"trade_date": trade_date, "account_ids": list(normalized)},
        ),
    )


def _internal_handler_trading_run_simulated_daily_inspection(
    account_id: int,
    strategy_id: int | None = None,
    inspection_date: str | None = None,
    auto_create_proposal: bool = False,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        account = client.simulated_trading.get_account(account_id)
        return {
            "success": True,
            "preview_only": True,
            "account_id": account_id,
            "strategy_id": strategy_id,
            "inspection_date": inspection_date,
            "auto_create_proposal": auto_create_proposal,
            "account_summary": {
                "account_name": account.get("name") or account.get("account_name"),
                "status": account.get("status"),
                "account_type": account.get("account_type"),
            },
            "inspection_scope_summary": {
                "strategy_id": strategy_id,
                "inspection_date": inspection_date,
                "auto_create_proposal": auto_create_proposal,
            },
            "message": (
                "Preview generated. Confirm to run simulated daily inspection for the "
                "selected account."
            ),
        }

    return cast(
        dict[str, Any],
        _call_registered_tool(
            "run_simulated_daily_inspection",
            {
                "account_id": account_id,
                "strategy_id": strategy_id,
                "inspection_date": inspection_date,
                "auto_create_proposal": auto_create_proposal,
            },
        ),
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "simulated_trading_read_daily_inspection_list": _fallback_simulated_trading_read_daily_inspection_list,
    "execute_simulated_trade": _fallback_execute_simulated_trade,
    "close_simulated_position": _fallback_close_simulated_position,
    "reset_simulated_account": _fallback_reset_simulated_account,
    "delete_simulated_account": _fallback_delete_simulated_account,
    "batch_delete_simulated_accounts": _fallback_batch_delete_simulated_accounts,
    "create_simulated_account": _fallback_create_simulated_account,
    "run_simulated_auto_trading": _fallback_run_simulated_auto_trading,
    "run_simulated_daily_inspection": _fallback_run_simulated_daily_inspection,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "trading_submit_simulated_order": _internal_handler_trading_submit_simulated_order,
    "trading_close_simulated_position": _internal_handler_trading_close_simulated_position,
    "trading_reset_simulated_account": _internal_handler_trading_reset_simulated_account,
    "trading_delete_simulated_account": _internal_handler_trading_delete_simulated_account,
    "trading_delete_simulated_account_batch": _internal_handler_trading_delete_simulated_account_batch,
    "trading_create_simulated_account": _internal_handler_trading_create_simulated_account,
    "trading_start_simulated_auto_trading": _internal_handler_trading_start_simulated_auto_trading,
    "trading_run_simulated_daily_inspection": _internal_handler_trading_run_simulated_daily_inspection,
}
