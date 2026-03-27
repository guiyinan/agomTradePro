"""
AgomTradePro MCP Tools - Account 账户管理工具

提供账户管理相关的 MCP 工具。
"""

import csv
from datetime import datetime
import io
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def _extract_results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return results
    if isinstance(payload, list):
        return payload
    return []


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _to_float(value: Any, field_name: str) -> float:
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field_name} 不能为空")
    try:
        return float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} 必须是数字")


def _normalize_position_input(row: dict[str, Any]) -> dict[str, Any]:
    asset_code = str(row.get("asset_code", "")).strip()
    if not asset_code:
        raise ValueError("asset_code 不能为空")

    shares = _to_float(row.get("shares"), "shares")
    avg_cost = _to_float(row.get("avg_cost"), "avg_cost")
    if shares <= 0:
        raise ValueError("shares 必须大于 0")
    if avg_cost <= 0:
        raise ValueError("avg_cost 必须大于 0")

    current_price_raw = row.get("current_price")
    current_price = None
    if current_price_raw not in (None, ""):
        current_price = _to_float(current_price_raw, "current_price")
        if current_price <= 0:
            raise ValueError("current_price 必须大于 0")

    result: dict[str, Any] = {
        "asset_code": asset_code,
        "shares": shares,
        "avg_cost": avg_cost,
        "current_price": current_price,
        "asset_class": str(row.get("asset_class") or "equity"),
        "region": str(row.get("region") or "CN"),
        "cross_border": str(row.get("cross_border") or "domestic"),
        "source": str(row.get("source") or "manual"),
        "is_closed": _parse_bool(row.get("is_closed"), default=False),
    }

    if row.get("category") not in (None, ""):
        result["category"] = row.get("category")
    if row.get("currency") not in (None, ""):
        result["currency"] = row.get("currency")
    if row.get("source_id") not in (None, ""):
        try:
            result["source_id"] = int(row.get("source_id"))
        except (ValueError, TypeError):
            raise ValueError("source_id 必须是整数")

    return result


def _list_endpoint_rows(
    client: AgomTradeProClient,
    endpoint: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    page = 1
    rows: list[dict[str, Any]] = []
    while len(rows) < limit:
        params = {"limit": min(200, limit), "page": page}
        payload = client.get(endpoint, params=params)
        batch = _extract_results(payload)
        if not batch:
            break
        rows.extend(batch)
        if not isinstance(payload, dict) or not payload.get("next"):
            break
        page += 1
    return rows[:limit]


def _normalize_transaction_input(row: dict[str, Any]) -> dict[str, Any]:
    action = str(row.get("action", "")).strip().lower()
    if action not in {"buy", "sell"}:
        raise ValueError("action 必须是 buy 或 sell")

    asset_code = str(row.get("asset_code", "")).strip()
    if not asset_code:
        raise ValueError("asset_code 不能为空")

    shares = _to_float(row.get("shares"), "shares")
    price = _to_float(row.get("price"), "price")
    if shares <= 0:
        raise ValueError("shares 必须大于 0")
    if price <= 0:
        raise ValueError("price 必须大于 0")

    traded_at = row.get("traded_at")
    if traded_at in (None, ""):
        traded_at = datetime.now().isoformat(timespec="seconds")

    result: dict[str, Any] = {
        "action": action,
        "asset_code": asset_code,
        "shares": shares,
        "price": price,
        "traded_at": traded_at,
        "notes": str(row.get("notes") or ""),
    }
    if row.get("commission") not in (None, ""):
        result["commission"] = _to_float(row.get("commission"), "commission")
    return result


def _normalize_capital_flow_input(row: dict[str, Any]) -> dict[str, Any]:
    flow_type = str(row.get("flow_type", "")).strip()
    if not flow_type:
        raise ValueError("flow_type 不能为空")

    amount = _to_float(row.get("amount"), "amount")
    if amount <= 0:
        raise ValueError("amount 必须大于 0")

    flow_date = row.get("flow_date")
    if flow_date in (None, ""):
        flow_date = datetime.now().date().isoformat()

    return {
        "flow_type": flow_type,
        "amount": amount,
        "flow_date": flow_date,
        "notes": str(row.get("notes") or ""),
    }


def register_account_tools(server: FastMCP) -> None:
    """注册 Account 相关的 MCP 工具"""

    @server.tool()
    def list_portfolios(limit: int = 50) -> list[dict[str, Any]]:
        """
        获取投资组合列表

        Args:
            limit: 返回数量限制

        Returns:
            投资组合列表

        Example:
            >>> portfolios = list_portfolios()
        """
        client = AgomTradeProClient()
        payload = client.get("api/account/portfolios/", params={"limit": limit})
        rows = _extract_results(payload)
        return [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "total_value": r.get("total_value"),
                "cash": r.get("cash"),
                "base_currency": r.get("base_currency"),
                "is_active": r.get("is_active"),
            }
            for r in rows
        ]

    @server.tool()
    def get_portfolio(portfolio_id: int) -> dict[str, Any]:
        """
        获取投资组合详情

        Args:
            portfolio_id: 组合 ID

        Returns:
            投资组合详情

        Example:
            >>> portfolio = get_portfolio(1)
        """
        client = AgomTradeProClient()
        portfolio = client.get(f"api/account/portfolios/{portfolio_id}/")
        pos_payload = client.get("api/account/positions/", params={"portfolio_id": portfolio_id, "limit": 200})
        pos_rows = [r for r in _extract_results(pos_payload) if not r.get("is_closed")]

        return {
            "id": portfolio.get("id"),
            "name": portfolio.get("name"),
            "total_value": portfolio.get("total_value"),
            "cash": portfolio.get("cash"),
            "base_currency": portfolio.get("base_currency"),
            "is_active": portfolio.get("is_active"),
            "positions": [
                {
                    "id": p.get("id"),
                    "asset_code": p.get("asset_code"),
                    "shares": p.get("shares"),
                    "avg_cost": p.get("avg_cost"),
                    "current_price": p.get("current_price"),
                    "market_value": p.get("market_value"),
                    "unrealized_pnl": p.get("unrealized_pnl"),
                }
                for p in pos_rows
            ],
        }

    @server.tool()
    def get_positions(
        portfolio_id: int | None = None,
        asset_code: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取持仓列表

        Args:
            portfolio_id: 组合 ID 过滤（可选）
            asset_code: 资产代码过滤（可选）
            limit: 返回数量限制

        Returns:
            持仓列表

        Example:
            >>> positions = get_positions(portfolio_id=1)
        """
        client = AgomTradeProClient()
        params: dict[str, Any] = {"limit": limit}
        if portfolio_id is not None:
            params["portfolio_id"] = portfolio_id
        if asset_code:
            params["asset_code"] = asset_code

        payload = client.get("api/account/positions/", params=params)
        rows = _extract_results(payload)
        return [
            {
                "id": p.get("id"),
                "portfolio": p.get("portfolio"),
                "asset_code": p.get("asset_code"),
                "shares": p.get("shares"),
                "avg_cost": p.get("avg_cost"),
                "current_price": p.get("current_price"),
                "market_value": p.get("market_value"),
                "unrealized_pnl": p.get("unrealized_pnl"),
                "is_closed": p.get("is_closed"),
            }
            for p in rows
        ]

    @server.tool()
    def create_position(
        portfolio_id: int,
        asset_code: str,
        quantity: float,
        price: float,
    ) -> dict[str, Any]:
        """
        创建持仓

        Args:
            portfolio_id: 组合 ID
            asset_code: 资产代码
            quantity: 数量
            price: 成交价格

        Returns:
            创建的持仓

        Example:
            >>> position = create_position(
            ...     portfolio_id=1,
            ...     asset_code="000001.SH",
            ...     quantity=1000,
            ...     price=10.5
            ... )
        """
        client = AgomTradeProClient()
        payload = {
            "portfolio": portfolio_id,
            "asset_code": asset_code,
            "shares": quantity,
            "avg_cost": price,
            "current_price": price,
            "source": "manual",
            "asset_class": "equity",
            "region": "CN",
            "cross_border": "domestic",
        }
        created = client.post("api/account/positions/", json=payload)
        return {
            "id": created.get("id"),
            "portfolio": created.get("portfolio"),
            "asset_code": created.get("asset_code"),
            "shares": created.get("shares"),
            "avg_cost": created.get("avg_cost"),
            "current_price": created.get("current_price"),
            "market_value": created.get("market_value"),
            "unrealized_pnl": created.get("unrealized_pnl"),
        }

    @server.tool()
    def get_positions_detailed(
        portfolio_id: int | None = None,
        include_closed: bool = False,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """
        获取持仓明细（含 position id，便于后续更新/导出）

        Args:
            portfolio_id: 组合 ID 过滤（可选）
            include_closed: 是否包含已平仓记录
            limit: 最大返回条数

        Returns:
            持仓明细列表
        """
        client = AgomTradeProClient()
        page = 1
        collected: list[dict[str, Any]] = []

        while len(collected) < limit:
            params: dict[str, Any] = {"limit": min(200, limit), "page": page}
            if portfolio_id is not None:
                params["portfolio_id"] = portfolio_id

            payload = client.get("api/account/positions/", params=params)
            rows = _extract_results(payload)
            if not rows:
                break

            if not include_closed:
                rows = [r for r in rows if not r.get("is_closed")]

            collected.extend(rows)

            if not isinstance(payload, dict) or not payload.get("next"):
                break
            page += 1

        return collected[:limit]

    @server.tool()
    def export_positions_json(
        portfolio_id: int,
        include_closed: bool = False,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """
        导出持仓（JSON）
        """
        rows = get_positions_detailed(
            portfolio_id=portfolio_id,
            include_closed=include_closed,
            limit=limit,
        )
        return {
            "portfolio_id": portfolio_id,
            "count": len(rows),
            "positions": rows,
        }

    @server.tool()
    def export_positions_csv(
        portfolio_id: int,
        include_closed: bool = False,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """
        导出持仓（CSV 文本）
        """
        rows = get_positions_detailed(
            portfolio_id=portfolio_id,
            include_closed=include_closed,
            limit=limit,
        )

        columns = [
            "id",
            "portfolio",
            "asset_code",
            "asset_class",
            "region",
            "cross_border",
            "shares",
            "avg_cost",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "source",
            "source_id",
            "is_closed",
        ]

        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in columns})

        return {
            "portfolio_id": portfolio_id,
            "count": len(rows),
            "csv": out.getvalue(),
        }

    @server.tool()
    def import_positions_json(
        portfolio_id: int,
        positions: list[dict[str, Any]],
        mode: str = "upsert",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """
        批量导入持仓（JSON）

        Args:
            portfolio_id: 目标组合 ID
            positions: 持仓数组
            mode: upsert|replace
            dry_run: true 时只预演不写入
        """
        if mode not in {"upsert", "replace"}:
            return {"success": False, "error": "mode 仅支持 upsert 或 replace"}

        client = AgomTradeProClient()
        existing = get_positions_detailed(portfolio_id=portfolio_id, include_closed=False, limit=5000)
        existing_by_code = {str(r.get("asset_code")).strip(): r for r in existing if r.get("asset_code")}

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
                except Exception as exc:  # noqa: BLE001
                    runtime_errors.append({
                        "operation": "create",
                        "asset_code": row.get("asset_code"),
                        "error": str(exc),
                    })

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
                except Exception as exc:  # noqa: BLE001
                    runtime_errors.append({
                        "operation": "update",
                        "id": item.get("id"),
                        "asset_code": item.get("asset_code"),
                        "error": str(exc),
                    })

            for row in to_close:
                try:
                    client.post(f"api/account/positions/{row['id']}/close/", json={})
                except Exception as exc:  # noqa: BLE001
                    runtime_errors.append({
                        "operation": "close",
                        "id": row.get("id"),
                        "asset_code": row.get("asset_code"),
                        "error": str(exc),
                    })

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

    @server.tool()
    def import_positions_csv(
        portfolio_id: int,
        csv_text: str,
        mode: str = "upsert",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """
        批量导入持仓（CSV 文本）

        CSV 列名建议:
        asset_code,shares,avg_cost,current_price,asset_class,region,cross_border,category,currency,source,source_id,is_closed
        """
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        rows = [dict(r) for r in reader]
        return import_positions_json(
            portfolio_id=portfolio_id,
            positions=rows,
            mode=mode,
            dry_run=dry_run,
        )

    @server.tool()
    def get_transactions_detailed(
        portfolio_id: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """
        获取交易明细（含 transaction id）
        """
        client = AgomTradeProClient()
        rows = _list_endpoint_rows(client, "api/account/transactions/", limit=limit)
        if portfolio_id is not None:
            rows = [r for r in rows if r.get("portfolio") == portfolio_id]
        return rows[:limit]

    @server.tool()
    def export_transactions_json(
        portfolio_id: int,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """
        导出交易记录（JSON）
        """
        rows = get_transactions_detailed(portfolio_id=portfolio_id, limit=limit)
        return {
            "portfolio_id": portfolio_id,
            "count": len(rows),
            "transactions": rows,
        }

    @server.tool()
    def export_transactions_csv(
        portfolio_id: int,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """
        导出交易记录（CSV 文本）
        """
        rows = get_transactions_detailed(portfolio_id=portfolio_id, limit=limit)
        columns = [
            "id",
            "portfolio",
            "position",
            "action",
            "asset_code",
            "shares",
            "price",
            "notional",
            "commission",
            "traded_at",
            "notes",
        ]
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in columns})
        return {
            "portfolio_id": portfolio_id,
            "count": len(rows),
            "csv": out.getvalue(),
        }

    @server.tool()
    def import_transactions_json(
        portfolio_id: int,
        transactions: list[dict[str, Any]],
        mode: str = "append",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """
        批量导入交易记录（JSON）

        Args:
            mode: append|replace
        """
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

        existing = get_transactions_detailed(portfolio_id=portfolio_id, limit=5000)
        delete_count = len(existing) if mode == "replace" else 0

        runtime_errors: list[dict[str, Any]] = []

        if not dry_run:
            if mode == "replace":
                for row in existing:
                    try:
                        client.delete(f"api/account/transactions/{row['id']}/")
                    except Exception as exc:  # noqa: BLE001
                        runtime_errors.append({
                            "operation": "delete",
                            "id": row.get("id"),
                            "error": str(exc),
                        })

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
                except Exception as exc:  # noqa: BLE001
                    runtime_errors.append({
                        "operation": "create",
                        "asset_code": row.get("asset_code"),
                        "error": str(exc),
                    })

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

    @server.tool()
    def import_transactions_csv(
        portfolio_id: int,
        csv_text: str,
        mode: str = "append",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """
        批量导入交易记录（CSV 文本）
        """
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        rows = [dict(r) for r in reader]
        return import_transactions_json(
            portfolio_id=portfolio_id,
            transactions=rows,
            mode=mode,
            dry_run=dry_run,
        )

    @server.tool()
    def get_capital_flows_detailed(
        portfolio_id: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """
        获取资金流水明细（含 flow id）
        """
        client = AgomTradeProClient()
        rows = _list_endpoint_rows(client, "api/account/capital-flows/", limit=limit)
        if portfolio_id is not None:
            rows = [r for r in rows if r.get("portfolio") == portfolio_id]
        return rows[:limit]

    @server.tool()
    def export_capital_flows_json(
        portfolio_id: int,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """
        导出资金流水（JSON）
        """
        rows = get_capital_flows_detailed(portfolio_id=portfolio_id, limit=limit)
        return {
            "portfolio_id": portfolio_id,
            "count": len(rows),
            "capital_flows": rows,
        }

    @server.tool()
    def export_capital_flows_csv(
        portfolio_id: int,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """
        导出资金流水（CSV 文本）
        """
        rows = get_capital_flows_detailed(portfolio_id=portfolio_id, limit=limit)
        columns = [
            "id",
            "portfolio",
            "flow_type",
            "amount",
            "flow_date",
            "notes",
            "created_at",
        ]
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in columns})
        return {
            "portfolio_id": portfolio_id,
            "count": len(rows),
            "csv": out.getvalue(),
        }

    @server.tool()
    def import_capital_flows_json(
        portfolio_id: int,
        capital_flows: list[dict[str, Any]],
        mode: str = "append",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """
        批量导入资金流水（JSON）

        Args:
            mode: append|replace
        """
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

        existing = get_capital_flows_detailed(portfolio_id=portfolio_id, limit=5000)
        delete_count = len(existing) if mode == "replace" else 0

        runtime_errors: list[dict[str, Any]] = []

        if not dry_run:
            if mode == "replace":
                for row in existing:
                    try:
                        client.delete(f"api/account/capital-flows/{row['id']}/")
                    except Exception as exc:  # noqa: BLE001
                        runtime_errors.append({
                            "operation": "delete",
                            "id": row.get("id"),
                            "error": str(exc),
                        })

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
                except Exception as exc:  # noqa: BLE001
                    runtime_errors.append({
                        "operation": "create",
                        "flow_type": row.get("flow_type"),
                        "error": str(exc),
                    })

        return {
            "success": len(errors) == 0 and len(runtime_errors) == 0,
            "portfolio_id": portfolio_id,
            "mode": mode,
            "dry_run": dry_run,
            "summary": {
                "input_rows": len(capital_flows),
                "valid_rows": len(normalized),
                "delete_count": delete_count,
                "create_count": len(normalized),
                "error_count": len(errors) + len(runtime_errors),
            },
            "errors": errors + runtime_errors,
        }

    @server.tool()
    def import_capital_flows_csv(
        portfolio_id: int,
        csv_text: str,
        mode: str = "append",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """
        批量导入资金流水（CSV 文本）
        """
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        rows = [dict(r) for r in reader]
        return import_capital_flows_json(
            portfolio_id=portfolio_id,
            capital_flows=rows,
            mode=mode,
            dry_run=dry_run,
        )

    @server.tool()
    def get_portfolio_statistics(portfolio_id: int) -> dict[str, Any]:
        """
        获取组合统计摘要
        """
        client = AgomTradeProClient()
        return client.get(f"api/account/portfolios/{portfolio_id}/statistics/")

    @server.tool()
    def export_account_bundle_json(
        portfolio_id: int,
        include_closed_positions: bool = False,
        positions_limit: int = 2000,
        transactions_limit: int = 5000,
        capital_flows_limit: int = 5000,
    ) -> dict[str, Any]:
        """
        一键导出账户数据包（JSON）

        包含：portfolio、statistics、positions、transactions、capital_flows。
        """
        client = AgomTradeProClient()
        portfolio = client.get(f"api/account/portfolios/{portfolio_id}/")
        statistics = get_portfolio_statistics(portfolio_id=portfolio_id)
        positions = get_positions_detailed(
            portfolio_id=portfolio_id,
            include_closed=include_closed_positions,
            limit=positions_limit,
        )
        transactions = get_transactions_detailed(
            portfolio_id=portfolio_id,
            limit=transactions_limit,
        )
        capital_flows = get_capital_flows_detailed(
            portfolio_id=portfolio_id,
            limit=capital_flows_limit,
        )

        return {
            "schema_version": "agomtradepro-account-bundle-v1",
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "portfolio_id": portfolio_id,
            "portfolio": portfolio,
            "statistics": statistics,
            "positions": positions,
            "transactions": transactions,
            "capital_flows": capital_flows,
            "counts": {
                "positions": len(positions),
                "transactions": len(transactions),
                "capital_flows": len(capital_flows),
            },
        }

    # ==================== Trading Cost Config ====================

    @server.tool()
    def get_trading_cost_configs(
        portfolio_id: int,
    ) -> list[dict[str, Any]]:
        """
        获取投资组合的交易费率配置

        Args:
            portfolio_id: 投资组合 ID

        Returns:
            费率配置列表
        """
        client = AgomTradeProClient()
        payload = client.get(
            "api/account/trading-cost-configs/",
            params={"limit": 100},
        )
        rows = _extract_results(payload)
        return [
            r for r in rows
            if r.get("portfolio") == portfolio_id
        ]

    @server.tool()
    def create_trading_cost_config(
        portfolio_id: int,
        commission_rate: float = 0.00025,
        min_commission: float = 5.0,
        stamp_duty_rate: float = 0.001,
        transfer_fee_rate: float = 0.00002,
    ) -> dict[str, Any]:
        """
        为投资组合创建交易费率配置

        Args:
            portfolio_id: 投资组合 ID
            commission_rate: 佣金率（默认万2.5，如 0.00025）
            min_commission: 最低佣金（元，默认5）
            stamp_duty_rate: 印花税率（默认千1，如 0.001，卖出时收取）
            transfer_fee_rate: 过户费率（默认万0.2，如 0.00002，沪市股票双向收取）

        Returns:
            创建的费率配置
        """
        client = AgomTradeProClient()
        return client.post(
            "api/account/trading-cost-configs/",
            json={
                "portfolio": portfolio_id,
                "commission_rate": commission_rate,
                "min_commission": min_commission,
                "stamp_duty_rate": stamp_duty_rate,
                "transfer_fee_rate": transfer_fee_rate,
            },
        )

    @server.tool()
    def update_trading_cost_config(
        config_id: int,
        commission_rate: float | None = None,
        min_commission: float | None = None,
        stamp_duty_rate: float | None = None,
        transfer_fee_rate: float | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        """
        更新交易费率配置

        Args:
            config_id: 费率配置 ID
            commission_rate: 佣金率（如 0.0001 表示万1）
            min_commission: 最低佣金（元）
            stamp_duty_rate: 印花税率（如 0.001 表示千1）
            transfer_fee_rate: 过户费率
            is_active: 是否启用

        Returns:
            更新后的费率配置
        """
        client = AgomTradeProClient()
        data: dict[str, Any] = {}
        if commission_rate is not None:
            data["commission_rate"] = commission_rate
        if min_commission is not None:
            data["min_commission"] = min_commission
        if stamp_duty_rate is not None:
            data["stamp_duty_rate"] = stamp_duty_rate
        if transfer_fee_rate is not None:
            data["transfer_fee_rate"] = transfer_fee_rate
        if is_active is not None:
            data["is_active"] = is_active
        return client.patch(
            f"api/account/trading-cost-configs/{config_id}/",
            json=data,
        )

    @server.tool()
    def calculate_trading_cost(
        config_id: int,
        action: str,
        amount: float,
        is_shanghai: bool = False,
    ) -> dict[str, Any]:
        """
        计算交易费用（基于已配置的费率）

        Args:
            config_id: 费率配置 ID
            action: 交易方向（buy 或 sell）
            amount: 成交金额（元）
            is_shanghai: 是否上海市场（影响过户费）

        Returns:
            费用明细：commission（佣金）、stamp_duty（印花税）、transfer_fee（过户费）、total（总费用）、cost_ratio（费用占比%）
        """
        client = AgomTradeProClient()
        result = client.post(
            f"api/account/trading-cost-configs/{config_id}/calculate/",
            json={
                "action": action,
                "amount": amount,
                "is_shanghai": is_shanghai,
            },
        )
        return result.get("data", result)

    def export_account_bundle_csv(
        portfolio_id: int,
        include_closed_positions: bool = False,
        positions_limit: int = 2000,
        transactions_limit: int = 5000,
        capital_flows_limit: int = 5000,
    ) -> dict[str, Any]:
        """
        一键导出账户数据包（CSV 文本）

        返回多个 CSV 文本块，便于 CLI 落地到本地文件。
        """
        positions_pack = export_positions_csv(
            portfolio_id=portfolio_id,
            include_closed=include_closed_positions,
            limit=positions_limit,
        )
        transactions_pack = export_transactions_csv(
            portfolio_id=portfolio_id,
            limit=transactions_limit,
        )
        capital_flows_pack = export_capital_flows_csv(
            portfolio_id=portfolio_id,
            limit=capital_flows_limit,
        )
        stats = get_portfolio_statistics(portfolio_id=portfolio_id)

        stats_csv_io = io.StringIO()
        stats_writer = csv.writer(stats_csv_io)
        stats_writer.writerow(["metric", "value"])
        for key, value in stats.items():
            stats_writer.writerow([key, value])

        return {
            "schema_version": "agomtradepro-account-bundle-v1",
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "portfolio_id": portfolio_id,
            "counts": {
                "positions": positions_pack.get("count", 0),
                "transactions": transactions_pack.get("count", 0),
                "capital_flows": capital_flows_pack.get("count", 0),
            },
            "statistics_csv": stats_csv_io.getvalue(),
            "positions_csv": positions_pack.get("csv", ""),
            "transactions_csv": transactions_pack.get("csv", ""),
            "capital_flows_csv": capital_flows_pack.get("csv", ""),
        }
