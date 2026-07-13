"""account runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_get_macro_sizing_config() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.account.get_macro_sizing_config()


def _fallback_account_read_account_list(
    active_only: bool = True,
    account_type: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    accounts = client.account.list_accounts(
        account_type=account_type,
        active_only=active_only,
    )
    return {
        "accounts": accounts,
        "total_count": len(accounts),
        "query": {
            "active_only": active_only,
            "account_type": account_type,
        },
    }


def _fallback_account_read_account_detail(account_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return {
        "account_id": account_id,
        "account": client.account.get_account(account_id),
    }


def _fallback_account_read_account_positions(account_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    positions = client.account.get_account_positions(account_id)
    return {
        "account_id": account_id,
        "positions": positions,
        "total_count": len(positions),
    }


def _fallback_account_read_account_performance(
    account_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if bool(start_date) != bool(end_date):
        raise ValueError("start_date and end_date must be provided together.")

    client = AgomTradeProClient()
    performance = client.account.get_account_performance(
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
    )
    mode = "date_range" if start_date and end_date else "basic"
    return {
        "account_id": account_id,
        "mode": mode,
        "query": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "performance": performance,
    }


def _fallback_get_positions(
    portfolio_id: int | None = None,
    asset_code: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    positions = client.account.get_positions(
        portfolio_id=portfolio_id,
        asset_code=asset_code,
        limit=limit,
    )
    rows = [
        {
            "asset_code": position.asset_code,
            "quantity": position.quantity,
            "avg_cost": position.avg_cost,
            "current_price": position.current_price,
            "market_value": position.market_value,
            "profit_loss": position.profit_loss,
        }
        for position in positions
    ]
    return {
        "positions": rows,
        "total_count": len(rows),
    }


def _fallback_account_read_portfolio_catalog(limit: int = 50) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    rows = client.account.list_portfolio_records(limit=limit)
    portfolios = [
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "total_value": row.get("total_value"),
            "cash": row.get("cash"),
            "base_currency": row.get("base_currency"),
            "is_active": row.get("is_active"),
        }
        for row in rows
    ]
    return {"portfolios": portfolios, "total_count": len(portfolios)}


def _fallback_account_read_portfolio_detail(portfolio_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    portfolio = client.account.get_portfolio_record(portfolio_id)
    positions = client.account.list_position_records(
        portfolio_id=portfolio_id,
        include_closed=False,
        limit=200,
    )
    return {"portfolio": portfolio, "positions": positions}


def _fallback_account_read_position_records(
    portfolio_id: int | None = None,
    include_closed: bool = False,
    limit: int = 500,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    positions = client.account.list_position_records(
        portfolio_id=portfolio_id,
        include_closed=include_closed,
        limit=limit,
    )
    return {"positions": positions, "total_count": len(positions)}


def _fallback_account_read_transaction_records(
    portfolio_id: int | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    transactions = client.account.list_transaction_records(
        portfolio_id=portfolio_id,
        limit=limit,
    )
    return {"transactions": transactions, "total_count": len(transactions)}


def _fallback_account_read_capital_flow_records(
    portfolio_id: int | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    capital_flows = client.account.list_capital_flow_records(
        portfolio_id=portfolio_id,
        limit=limit,
    )
    return {"capital_flows": capital_flows, "total_count": len(capital_flows)}


def _fallback_get_portfolio_statistics(portfolio_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.account.get_portfolio_statistics(portfolio_id)


def _fallback_get_trading_cost_configs(
    portfolio_id: int,
    limit: int = 100,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    configs = client.account.get_trading_cost_configs(limit=limit)
    filtered = [config for config in configs if config.get("portfolio") == portfolio_id]
    return {
        "portfolio_id": portfolio_id,
        "configs": filtered,
        "total_count": len(filtered),
    }


def _fallback_calculate_trading_cost(
    config_id: int,
    action: str,
    amount: float,
    is_shanghai: bool = False,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.account.calculate_trading_cost(
        config_id=config_id,
        action=action,
        amount=amount,
        is_shanghai=is_shanghai,
    )


def _fallback_import_positions_json(
    portfolio_id: int,
    positions: list[dict[str, Any]],
    mode: str = "upsert",
    dry_run: bool = True,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient
    from agomtradepro_mcp.tools.account_tools import _list_endpoint_rows, _normalize_position_input

    if mode not in {"upsert", "replace"}:
        return {"success": False, "error": "mode 仅支持 upsert 或 replace"}

    client = AgomTradeProClient()
    existing = _list_endpoint_rows(client, "api/account/positions/", limit=5000)
    existing = [
        row
        for row in existing
        if row.get("portfolio") == portfolio_id and not bool(row.get("is_closed"))
    ]
    existing_by_code = {
        str(row.get("asset_code", "")).strip(): row for row in existing if row.get("asset_code")
    }

    normalized: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(positions, start=1):
        try:
            row = _normalize_position_input(raw)
            normalized[row["asset_code"]] = row
        except ValueError as exc:
            errors.append({"row": idx, "error": str(exc), "raw": raw})

    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    to_close: list[dict[str, Any]] = []

    for asset_code, row in normalized.items():
        existing_row = existing_by_code.get(asset_code)
        if existing_row:
            to_update.append({"id": existing_row["id"], "asset_code": asset_code, "data": row})
        else:
            to_create.append(row)

    if mode == "replace":
        imported_codes = set(normalized.keys())
        for row in existing:
            code = str(row.get("asset_code", "")).strip()
            if code and code not in imported_codes:
                to_close.append(row)

    runtime_errors: list[dict[str, Any]] = []

    if not dry_run:
        for row in to_create:
            payload = {
                "portfolio": portfolio_id,
                "asset_code": row["asset_code"],
                "asset_class": row["asset_class"],
                "region": row["region"],
                "cross_border": row["cross_border"],
                "shares": row["shares"],
                "avg_cost": row["avg_cost"],
                "source": row["source"],
            }
            if row.get("current_price") is not None:
                payload["current_price"] = row["current_price"]
            if "category" in row:
                payload["category"] = row["category"]
            if "currency" in row:
                payload["currency"] = row["currency"]
            if "source_id" in row:
                payload["source_id"] = row["source_id"]
            try:
                client.post("api/account/positions/", json=payload)
            except Exception as exc:
                runtime_errors.append(
                    {
                        "operation": "create",
                        "asset_code": row.get("asset_code"),
                        "error": str(exc),
                    }
                )

        for item in to_update:
            payload = {
                "shares": item["data"]["shares"],
                "avg_cost": item["data"]["avg_cost"],
                "is_closed": item["data"]["is_closed"],
            }
            if item["data"].get("current_price") is not None:
                payload["current_price"] = item["data"]["current_price"]
            try:
                client.patch(f"api/account/positions/{item['id']}/", json=payload)
            except Exception as exc:
                runtime_errors.append(
                    {
                        "operation": "update",
                        "id": item.get("id"),
                        "asset_code": item.get("asset_code"),
                        "error": str(exc),
                    }
                )

        for row in to_close:
            try:
                client.post(f"api/account/positions/{row['id']}/close/", json={})
            except Exception as exc:
                runtime_errors.append(
                    {
                        "operation": "close",
                        "id": row.get("id"),
                        "asset_code": row.get("asset_code"),
                        "error": str(exc),
                    }
                )

    return {
        "success": len(errors) == 0 and len(runtime_errors) == 0,
        "portfolio_id": portfolio_id,
        "mode": mode,
        "dry_run": dry_run,
        "summary": {
            "input_rows": len(positions),
            "valid_rows": len(normalized),
            "create_count": len(to_create),
            "update_count": len(to_update),
            "close_count": len(to_close),
            "error_count": len(errors) + len(runtime_errors),
        },
        "errors": errors + runtime_errors,
    }


def _fallback_import_transactions_json(
    portfolio_id: int,
    transactions: list[dict[str, Any]],
    mode: str = "append",
    dry_run: bool = True,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient
    from agomtradepro_mcp.tools.account_tools import (
        _list_endpoint_rows,
        _normalize_transaction_input,
    )

    if mode not in {"append", "replace"}:
        return {"success": False, "error": "mode 仅支持 append 或 replace"}

    client = AgomTradeProClient()
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(transactions, start=1):
        try:
            normalized.append(_normalize_transaction_input(raw))
        except ValueError as exc:
            errors.append({"row": idx, "error": str(exc), "raw": raw})

    existing = _list_endpoint_rows(client, "api/account/transactions/", limit=5000)
    existing = [row for row in existing if row.get("portfolio") == portfolio_id]
    delete_count = len(existing) if mode == "replace" else 0

    runtime_errors: list[dict[str, Any]] = []

    if not dry_run:
        if mode == "replace":
            for row in existing:
                try:
                    client.delete(f"api/account/transactions/{row['id']}/")
                except Exception as exc:
                    runtime_errors.append(
                        {
                            "operation": "delete",
                            "id": row.get("id"),
                            "error": str(exc),
                        }
                    )

        for row in normalized:
            payload = {
                "portfolio": portfolio_id,
                "action": row["action"],
                "asset_code": row["asset_code"],
                "shares": row["shares"],
                "price": row["price"],
                "traded_at": row["traded_at"],
                "notes": row["notes"],
            }
            if "commission" in row:
                payload["commission"] = row["commission"]
            try:
                client.post("api/account/transactions/", json=payload)
            except Exception as exc:
                runtime_errors.append(
                    {
                        "operation": "create",
                        "asset_code": row.get("asset_code"),
                        "error": str(exc),
                    }
                )

    return {
        "success": len(errors) == 0 and len(runtime_errors) == 0,
        "portfolio_id": portfolio_id,
        "mode": mode,
        "dry_run": dry_run,
        "summary": {
            "input_rows": len(transactions),
            "valid_rows": len(normalized),
            "delete_count": delete_count,
            "create_count": len(normalized),
            "error_count": len(errors) + len(runtime_errors),
        },
        "errors": errors + runtime_errors,
    }


def _fallback_import_capital_flows_json(
    portfolio_id: int,
    capital_flows: list[dict[str, Any]],
    mode: str = "append",
    dry_run: bool = True,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient
    from agomtradepro_mcp.tools.account_tools import (
        _list_endpoint_rows,
        _normalize_capital_flow_input,
    )

    if mode not in {"append", "replace"}:
        return {"success": False, "error": "mode 仅支持 append 或 replace"}

    client = AgomTradeProClient()
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(capital_flows, start=1):
        try:
            normalized.append(_normalize_capital_flow_input(raw))
        except ValueError as exc:
            errors.append({"row": idx, "error": str(exc), "raw": raw})

    existing = _list_endpoint_rows(client, "api/account/capital-flows/", limit=5000)
    existing = [row for row in existing if row.get("portfolio") == portfolio_id]

    runtime_errors: list[dict[str, Any]] = []

    if not dry_run:
        if mode == "replace":
            for row in existing:
                try:
                    client.delete(f"api/account/capital-flows/{row['id']}/")
                except Exception as exc:
                    runtime_errors.append(
                        {
                            "operation": "delete",
                            "id": row.get("id"),
                            "error": str(exc),
                        }
                    )

        for row in normalized:
            payload = {
                "portfolio": portfolio_id,
                "flow_type": row["flow_type"],
                "amount": row["amount"],
                "flow_date": row["flow_date"],
                "notes": row["notes"],
            }
            try:
                client.post("api/account/capital-flows/", json=payload)
            except Exception as exc:
                runtime_errors.append(
                    {
                        "operation": "create",
                        "flow_type": row.get("flow_type"),
                        "error": str(exc),
                    }
                )

    return {
        "success": len(errors) == 0 and len(runtime_errors) == 0,
        "portfolio_id": portfolio_id,
        "mode": mode,
        "dry_run": dry_run,
        "summary": {
            "input_rows": len(capital_flows),
            "valid_rows": len(normalized),
            "delete_count": len(existing) if mode == "replace" else 0,
            "create_count": len(normalized),
            "error_count": len(errors) + len(runtime_errors),
        },
        "errors": errors + runtime_errors,
    }


def _fallback_create_trading_cost_config(
    portfolio_id: int,
    commission_rate: float = 0.00025,
    min_commission: float = 5.0,
    stamp_duty_rate: float = 0.001,
    transfer_fee_rate: float = 0.00002,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.account.create_trading_cost_config(
        portfolio_id=portfolio_id,
        commission_rate=commission_rate,
        min_commission=min_commission,
        stamp_duty_rate=stamp_duty_rate,
        transfer_fee_rate=transfer_fee_rate,
    )


def _fallback_update_trading_cost_config(
    config_id: int,
    commission_rate: float | None = None,
    min_commission: float | None = None,
    stamp_duty_rate: float | None = None,
    transfer_fee_rate: float | None = None,
    is_active: bool | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.account.update_trading_cost_config(
        config_id=config_id,
        commission_rate=commission_rate,
        min_commission=min_commission,
        stamp_duty_rate=stamp_duty_rate,
        transfer_fee_rate=transfer_fee_rate,
        is_active=is_active,
    )


def _internal_handler_account_create_trading_cost_config(
    portfolio_id: int,
    commission_rate: float = 0.00025,
    min_commission: float = 5.0,
    stamp_duty_rate: float = 0.001,
    transfer_fee_rate: float = 0.00002,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        portfolio = client.account.get_portfolio(portfolio_id)
        return {
            "success": True,
            "preview_only": True,
            "portfolio_id": portfolio_id,
            "portfolio_summary": {
                "name": getattr(portfolio, "name", None),
                "total_value": getattr(portfolio, "total_value", None),
                "cash": getattr(portfolio, "cash", None),
            },
            "trading_cost_summary": {
                "commission_rate": commission_rate,
                "min_commission": min_commission,
                "stamp_duty_rate": stamp_duty_rate,
                "transfer_fee_rate": transfer_fee_rate,
            },
            "message": (
                "Preview generated. Confirm to create the trading cost config for the "
                "selected portfolio."
            ),
        }

    return _call_registered_tool(
        "create_trading_cost_config",
        {
            "portfolio_id": portfolio_id,
            "commission_rate": commission_rate,
            "min_commission": min_commission,
            "stamp_duty_rate": stamp_duty_rate,
            "transfer_fee_rate": transfer_fee_rate,
        },
    )


def _internal_handler_account_create_position(
    portfolio_id: int,
    asset_code: str,
    quantity: float,
    price: float,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    import math

    from agomtradepro import AgomTradeProClient

    normalized_portfolio_id = int(portfolio_id)
    if normalized_portfolio_id <= 0:
        raise ValueError("portfolio_id must be a positive integer")

    normalized_asset_code = str(asset_code).strip()
    if not normalized_asset_code:
        raise ValueError("asset_code is required")
    if len(normalized_asset_code) > 20:
        raise ValueError("asset_code must be at most 20 characters")

    normalized_quantity = float(quantity)
    normalized_price = float(price)
    if not math.isfinite(normalized_quantity) or normalized_quantity <= 0:
        raise ValueError("quantity must be a finite number greater than zero")
    if not math.isfinite(normalized_price) or normalized_price <= 0:
        raise ValueError("price must be a finite number greater than zero")

    client = AgomTradeProClient()
    if preview_only:
        matching_positions = client.account.get_positions(
            portfolio_id=normalized_portfolio_id,
            asset_code=normalized_asset_code,
            limit=100,
        )
        existing_quantity = sum(
            float(getattr(position, "quantity", 0.0)) for position in matching_positions
        )
        existing_cost = sum(
            float(getattr(position, "quantity", 0.0)) * float(getattr(position, "avg_cost", 0.0))
            for position in matching_positions
        )
        resulting_quantity = existing_quantity + normalized_quantity
        resulting_avg_cost = (
            existing_cost + normalized_quantity * normalized_price
        ) / resulting_quantity
        return {
            "success": True,
            "preview_only": True,
            "summary": {
                "portfolio_id": normalized_portfolio_id,
                "asset_code": normalized_asset_code,
                "operation": "increase" if matching_positions else "create",
                "matching_position_count": len(matching_positions),
                "existing_quantity": existing_quantity,
                "added_quantity": normalized_quantity,
                "resulting_quantity": resulting_quantity,
                "execution_price": normalized_price,
                "resulting_avg_cost": resulting_avg_cost,
                "resulting_market_value_at_execution_price": (
                    resulting_quantity * normalized_price
                ),
                "will_record_buy_ledger_entry": True,
                "will_execute_external_broker_order": False,
            },
            "message": (
                "Preview generated. Confirm to update the authenticated owner's portfolio "
                "ledger and record a buy-side ledger entry; no external broker order is sent."
            ),
        }

    position = client.account.create_position(
        portfolio_id=normalized_portfolio_id,
        asset_code=normalized_asset_code,
        quantity=normalized_quantity,
        price=normalized_price,
    )
    return {
        "asset_code": str(getattr(position, "asset_code", normalized_asset_code)),
        "quantity": float(getattr(position, "quantity", 0.0)),
        "avg_cost": float(getattr(position, "avg_cost", 0.0)),
        "current_price": float(getattr(position, "current_price", 0.0)),
        "market_value": float(getattr(position, "market_value", 0.0)),
        "profit_loss": float(getattr(position, "profit_loss", 0.0)),
    }


def _internal_handler_account_import_broker_trades(
    portfolio_id: int,
    trades: list[dict[str, Any]],
    broker_name: str = "manual",
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_portfolio_id = int(portfolio_id)
    if normalized_portfolio_id <= 0:
        raise ValueError("portfolio_id must be a positive integer")

    normalized_broker_name = str(broker_name or "manual").strip() or "manual"
    if len(normalized_broker_name) > 64:
        raise ValueError("broker_name must be at most 64 characters")
    if not isinstance(trades, list) or not trades:
        raise ValueError("trades must contain at least one structured trade")
    if len(trades) > 500:
        raise ValueError("trades must contain at most 500 rows")

    allowed_fields = {
        "traded_at",
        "action",
        "asset_code",
        "shares",
        "price",
        "commission",
        "stamp_duty",
        "transfer_fee",
        "external_trade_id",
        "notes",
    }
    required_fields = {"traded_at", "action", "asset_code", "shares", "price"}
    normalized_trades: list[dict[str, Any]] = []
    for index, trade in enumerate(trades, start=1):
        if not isinstance(trade, dict):
            raise ValueError(f"trades[{index}] must be an object")
        unknown_fields = sorted(set(trade) - allowed_fields)
        if unknown_fields:
            raise ValueError(
                f"trades[{index}] contains unsupported fields: {', '.join(unknown_fields)}"
            )
        missing_fields = sorted(
            field for field in required_fields if trade.get(field) in (None, "")
        )
        if missing_fields:
            raise ValueError(
                f"trades[{index}] is missing required fields: {', '.join(missing_fields)}"
            )
        normalized_trades.append(dict(trade))

    client = AgomTradeProClient()
    if preview_only:
        preview = client.account.preview_broker_trades(
            portfolio_id=normalized_portfolio_id,
            trades=normalized_trades,
            broker_name=normalized_broker_name,
        )
        if not isinstance(preview, dict):
            raise ValueError("broker trade preview returned an invalid response")
        valid_rows = int(preview.get("valid_rows", 0))
        duplicate_rows = int(preview.get("duplicate_rows", 0))
        error_rows = int(preview.get("error_rows", 0))
        if min(valid_rows, duplicate_rows, error_rows) < 0:
            raise ValueError("broker trade preview returned invalid row counts")
        importable_rows = max(valid_rows - duplicate_rows, 0)
        if importable_rows == 0:
            raise ValueError("broker trade preview has no importable rows")
        return {
            **preview,
            "preview_only": True,
            "summary": {
                "portfolio_id": normalized_portfolio_id,
                "broker_name": normalized_broker_name,
                "input_rows": len(normalized_trades),
                "valid_rows": valid_rows,
                "duplicate_rows": duplicate_rows,
                "error_rows": error_rows,
                "expected_import_rows": importable_rows,
                "will_create_real_account_mapping_if_missing": True,
                "will_write_import_batch": True,
                "will_write_transaction_records": True,
                "will_update_unified_positions": True,
                "will_update_legacy_position_projection": True,
                "will_record_unified_buy_or_sell_trades": True,
                "will_match_recommendations_and_execution_links": True,
                "may_partially_commit_valid_rows": True,
                "will_execute_external_broker_order": False,
            },
            "message": (
                "Preview generated. Confirm to import the non-duplicate rows into the "
                "authenticated owner's ledgers and recommendation audit trail. "
                "No external broker order is sent."
            ),
        }

    result = client.account.import_broker_trades(
        portfolio_id=normalized_portfolio_id,
        trades=normalized_trades,
        broker_name=normalized_broker_name,
    )
    if not isinstance(result, dict):
        raise ValueError("broker trade import returned an invalid response")
    return result


def _internal_handler_account_create_unified_account(
    account_name: str,
    account_type: str,
    initial_capital: float,
    max_position_pct: float = 20.0,
    stop_loss_pct: float | None = None,
    commission_rate: float = 0.0003,
    slippage_rate: float = 0.001,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_name = str(account_name).strip()
    if not normalized_name:
        raise ValueError("account_name is required")
    if len(normalized_name) > 100:
        raise ValueError("account_name must be at most 100 characters")

    normalized_type = str(account_type).strip().lower()
    if normalized_type not in {"real", "simulated"}:
        raise ValueError("account_type must be real or simulated")

    normalized_initial_capital = float(initial_capital)
    if normalized_initial_capital < 1000:
        raise ValueError("initial_capital must be at least 1000")
    if not 1.0 <= float(max_position_pct) <= 100.0:
        raise ValueError("max_position_pct must be between 1 and 100")
    if stop_loss_pct is not None and not 0.0 <= float(stop_loss_pct) <= 50.0:
        raise ValueError("stop_loss_pct must be between 0 and 50")
    if not 0.0 <= float(commission_rate) <= 0.01:
        raise ValueError("commission_rate must be between 0 and 0.01")
    if not 0.0 <= float(slippage_rate) <= 0.01:
        raise ValueError("slippage_rate must be between 0 and 0.01")

    client = AgomTradeProClient()
    if preview_only:
        accounts = client.account.list_accounts(
            account_type=normalized_type,
            active_only=False,
            limit=100,
        )
        same_name_accounts = [
            account
            for account in accounts
            if isinstance(account, dict)
            and str(account.get("account_name") or account.get("name") or "").strip()
            == normalized_name
        ]
        if same_name_accounts:
            raise ValueError(
                f"account_name already exists for the authenticated user: {normalized_name}"
            )
        return {
            "success": True,
            "preview_only": True,
            "summary": {
                "account_name": normalized_name,
                "account_type": normalized_type,
                "initial_capital": normalized_initial_capital,
                "max_position_pct": float(max_position_pct),
                "stop_loss_pct": (float(stop_loss_pct) if stop_loss_pct is not None else None),
                "commission_rate": float(commission_rate),
                "slippage_rate": float(slippage_rate),
                "auto_trading_enabled": normalized_type == "simulated",
                "matching_name_count": 0,
                "will_create_account": True,
                "will_execute_trade": False,
            },
            "message": (
                "Preview generated. Confirm to create the authenticated user's unified "
                "account; this operation does not execute a trade."
            ),
        }

    return client.account.create_account(
        name=normalized_name,
        initial_capital=normalized_initial_capital,
        account_type=normalized_type,
        max_position_pct=float(max_position_pct),
        stop_loss_pct=float(stop_loss_pct) if stop_loss_pct is not None else None,
        commission_rate=float(commission_rate),
        slippage_rate=float(slippage_rate),
    )


def _internal_handler_account_update_trading_cost_config(
    config_id: int,
    commission_rate: float | None = None,
    min_commission: float | None = None,
    stamp_duty_rate: float | None = None,
    transfer_fee_rate: float | None = None,
    is_active: bool | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    updates = {
        key: value
        for key, value in {
            "commission_rate": commission_rate,
            "min_commission": min_commission,
            "stamp_duty_rate": stamp_duty_rate,
            "transfer_fee_rate": transfer_fee_rate,
            "is_active": is_active,
        }.items()
        if value is not None
    }

    if preview_only:
        config = client.account.get_trading_cost_config(config_id)
        return {
            "success": True,
            "preview_only": True,
            "config_id": config_id,
            "trading_cost_config_summary": {
                "portfolio": config.get("portfolio"),
                "commission_rate": config.get("commission_rate"),
                "min_commission": config.get("min_commission"),
                "stamp_duty_rate": config.get("stamp_duty_rate"),
                "transfer_fee_rate": config.get("transfer_fee_rate"),
                "is_active": config.get("is_active"),
            },
            "update_summary": {
                "field_count": len(updates),
                "fields": sorted(updates),
            },
            "message": ("Preview generated. Confirm to update the selected trading cost config."),
        }

    return _call_registered_tool(
        "update_trading_cost_config",
        {
            "config_id": config_id,
            "commission_rate": commission_rate,
            "min_commission": min_commission,
            "stamp_duty_rate": stamp_duty_rate,
            "transfer_fee_rate": transfer_fee_rate,
            "is_active": is_active,
        },
    )


def _internal_handler_account_update_macro_sizing_config(
    warning_factor: float | None = None,
    regime_tiers_json: list[dict[str, Any]] | None = None,
    pulse_tiers_json: list[dict[str, Any]] | None = None,
    drawdown_tiers_json: list[dict[str, Any]] | None = None,
    market_temperature_cold_factor: float | None = None,
    market_temperature_warm_factor: float | None = None,
    market_temperature_hot_factor: float | None = None,
    market_temperature_overheat_factor: float | None = None,
    market_temperature_extreme_factor: float | None = None,
    block_new_position_on_extreme: bool | None = None,
    description: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    updates = {
        key: value
        for key, value in {
            "warning_factor": warning_factor,
            "regime_tiers_json": regime_tiers_json,
            "pulse_tiers_json": pulse_tiers_json,
            "drawdown_tiers_json": drawdown_tiers_json,
            "market_temperature_cold_factor": market_temperature_cold_factor,
            "market_temperature_warm_factor": market_temperature_warm_factor,
            "market_temperature_hot_factor": market_temperature_hot_factor,
            "market_temperature_overheat_factor": market_temperature_overheat_factor,
            "market_temperature_extreme_factor": market_temperature_extreme_factor,
            "block_new_position_on_extreme": block_new_position_on_extreme,
            "description": description,
        }.items()
        if value is not None
    }
    if not updates:
        raise ValueError("At least one macro sizing config field must be provided")

    if preview_only:
        current = client.account.get_macro_sizing_config()
        return {
            "success": True,
            "preview_only": True,
            "current_config_summary": {
                "version": current.get("version"),
                "is_active": current.get("is_active"),
                "warning_factor": current.get("warning_factor"),
                "market_temperature_hot_factor": current.get("market_temperature_hot_factor"),
                "market_temperature_overheat_factor": current.get(
                    "market_temperature_overheat_factor"
                ),
                "market_temperature_extreme_factor": current.get(
                    "market_temperature_extreme_factor"
                ),
                "block_new_position_on_extreme": current.get("block_new_position_on_extreme"),
                "description": current.get("description"),
            },
            "update_summary": {
                "field_count": len(updates),
                "fields": sorted(updates),
                "changes": updates,
                "expected_next_version": (
                    int(current["version"]) + 1 if isinstance(current.get("version"), int) else None
                ),
            },
            "message": (
                "Preview generated. Confirm to create and activate a new macro sizing "
                "configuration version."
            ),
        }

    return client.account.update_macro_sizing_config(updates, partial=True)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_macro_sizing_config": _fallback_get_macro_sizing_config,
    "account_read_account_list": _fallback_account_read_account_list,
    "account_read_account_detail": _fallback_account_read_account_detail,
    "account_read_account_positions": _fallback_account_read_account_positions,
    "account_read_account_performance": _fallback_account_read_account_performance,
    "get_positions": _fallback_get_positions,
    "account_read_portfolio_catalog": _fallback_account_read_portfolio_catalog,
    "account_read_portfolio_detail": _fallback_account_read_portfolio_detail,
    "account_read_position_records": _fallback_account_read_position_records,
    "account_read_transaction_records": _fallback_account_read_transaction_records,
    "account_read_capital_flow_records": _fallback_account_read_capital_flow_records,
    "get_portfolio_statistics": _fallback_get_portfolio_statistics,
    "get_trading_cost_configs": _fallback_get_trading_cost_configs,
    "calculate_trading_cost": _fallback_calculate_trading_cost,
    "import_positions_json": _fallback_import_positions_json,
    "import_transactions_json": _fallback_import_transactions_json,
    "import_capital_flows_json": _fallback_import_capital_flows_json,
    "create_trading_cost_config": _fallback_create_trading_cost_config,
    "update_trading_cost_config": _fallback_update_trading_cost_config,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "account_create_position": _internal_handler_account_create_position,
    "account_import_broker_trades": _internal_handler_account_import_broker_trades,
    "account_create_unified_account": _internal_handler_account_create_unified_account,
    "account_create_trading_cost_config": _internal_handler_account_create_trading_cost_config,
    "account_update_trading_cost_config": _internal_handler_account_update_trading_cost_config,
    "account_update_macro_sizing_config": _internal_handler_account_update_macro_sizing_config,
}
