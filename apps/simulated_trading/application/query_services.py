"""Application-level query helpers for cross-app simulated trading access."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.simulated_trading.application.ports import DailyNetValueRecord
from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
    get_simulated_daily_net_value_repository,
    get_simulated_position_repository,
)


def get_position_snapshots(account_id: int | str) -> list[dict[str, Any]]:
    """Return lightweight position snapshots for account-level planning."""
    try:
        resolved_account_id = int(account_id)
    except ValueError as exc:
        raise ValueError("account_id must be an integer") from exc
    snapshots: list[dict[str, Any]] = (
        get_simulated_position_repository().get_position_snapshots(
            account_id=resolved_account_id
        )
    )
    return snapshots


def list_held_asset_codes() -> list[str]:
    """Return distinct asset codes held in simulated-trading positions."""

    asset_codes: list[str] = get_simulated_position_repository().list_held_asset_codes()
    return asset_codes


def list_active_account_models_for_user(user_id: int) -> list[Any]:
    """Return active account rows for UI contexts that rely on model display helpers."""
    accounts: list[Any] = (
        get_simulated_account_repository().get_active_account_models_for_user(user_id)
    )
    return accounts


def list_active_account_targets() -> list[dict[str, Any]]:
    """Return active account/user id pairs for scheduled application jobs."""

    targets: list[dict[str, Any]] = (
        get_simulated_account_repository().list_active_account_targets()
    )
    return targets


def get_user_account_totals(user_id: int) -> dict[str, float] | None:
    """Return aggregated totals across one user's simulated accounts."""

    accounts = get_simulated_account_repository().get_by_user(user_id)
    if not accounts:
        return None

    total_assets = sum(float(account.total_value or 0.0) for account in accounts)
    initial_capital = sum(float(account.initial_capital or 0.0) for account in accounts)
    cash_balance = sum(float(account.current_cash or 0.0) for account in accounts)
    invested_value = sum(float(account.current_market_value or 0.0) for account in accounts)
    total_return = total_assets - initial_capital
    total_return_pct = (total_return / initial_capital * 100) if initial_capital else 0.0
    invested_ratio = (invested_value / total_assets) if total_assets else 0.0

    return {
        "total_assets": total_assets,
        "initial_capital": initial_capital,
        "cash_balance": cash_balance,
        "invested_value": invested_value,
        "invested_ratio": invested_ratio,
        "total_return": total_return,
        "total_return_pct": total_return_pct,
    }


def list_dashboard_account_payloads(user_id: int) -> list[dict[str, Any]]:
    """Return dashboard account cards from simulated-trading entities."""

    accounts = get_simulated_account_repository().get_by_user(user_id)
    ordered_accounts = sorted(
        accounts,
        key=lambda account: (
            _normalize_account_type(getattr(account, "account_type", "")),
            -float(getattr(account, "total_value", 0.0) or 0.0),
        ),
    )
    return [
        {
            "id": account.account_id,
            "name": account.account_name,
            "type_code": _normalize_account_type(account.account_type),
            "type_label": _account_type_label(account.account_type),
            "total_value": float(account.total_value or 0.0),
            "cash": float(account.current_cash or 0.0),
            "market_value": float(account.current_market_value or 0.0),
            "total_return": float(account.total_return or 0.0),
            "is_active": bool(account.is_active),
        }
        for account in ordered_accounts
    ]


def list_user_position_payloads(
    *,
    user_id: int,
    account_id: int | None = None,
    include_account_meta: bool = False,
) -> list[dict[str, Any]]:
    """Return serialized position payloads for dashboard reads."""

    account_repo = get_simulated_account_repository()
    position_repo = get_simulated_position_repository()
    accounts = account_repo.get_by_user(user_id)
    if account_id is not None:
        accounts = [account for account in accounts if int(account.account_id) == int(account_id)]

    account_name_map = {int(account.account_id): account.account_name for account in accounts}
    payloads: list[dict[str, Any]] = []
    for account in accounts:
        for position in position_repo.get_by_account(account.account_id):
            payload: dict[str, Any] = {
                "id": None,
                "asset_code": position.asset_code,
                "asset_name": position.asset_name,
                "asset_class": position.asset_type,
                "asset_class_display": _asset_type_label(position.asset_type),
                "region": "CN",
                "region_display": "中国",
                "shares": float(position.quantity),
                "avg_cost": float(position.avg_cost),
                "current_price": float(position.current_price),
                "market_value": float(position.market_value),
                "unrealized_pnl": float(position.unrealized_pnl),
                "unrealized_pnl_pct": position.unrealized_pnl_pct,
                "opened_at": position.first_buy_date.strftime("%Y-%m-%d")
                if position.first_buy_date
                else "",
                "signal_id": position.signal_id,
                "invalidation_description": position.invalidation_description or "",
                "is_invalidated": bool(position.is_invalidated),
                "invalidation_reason": position.invalidation_reason or "",
            }
            if include_account_meta:
                payload["account_id"] = account.account_id
                payload["account_name"] = account_name_map.get(int(account.account_id), "")
            payloads.append(payload)

    payloads.sort(key=lambda row: (-float(row.get("market_value", 0.0) or 0.0), row["asset_code"]))
    return payloads


def get_account_execution_projection(
    *,
    user_id: int,
    account_id: int,
) -> dict[str, Any] | None:
    """Return the authoritative account/position inputs required by live risk checks.

    This application facade intentionally hides ORM models from broker execution and
    gives cross-app callers a stable, read-only projection.
    """

    account_repo = get_simulated_account_repository()
    position_repo = get_simulated_position_repository()
    account = next(
        (
            item
            for item in account_repo.get_by_user(user_id)
            if int(item.account_id) == int(account_id)
        ),
        None,
    )
    if account is None:
        return None
    positions = [
        {
            "asset_code": position.asset_code,
            "quantity": float(position.quantity or 0),
            # The unified ledger does not currently expose a separate frozen
            # quantity, so this is an account projection, not a broker fact.
            "available_quantity": float(position.quantity or 0),
            "current_price": float(position.current_price or 0),
            "market_value": float(position.market_value or 0),
        }
        for position in position_repo.get_by_account(account.account_id)
    ]
    return {
        "account_id": int(account.account_id),
        "user_id": int(user_id),
        "account_type": _normalize_account_type(account.account_type),
        "is_active": bool(account.is_active),
        "total_asset": float(account.total_value or 0),
        "cash_available": float(account.current_cash or 0),
        "total_position_value": float(account.current_market_value or 0),
        "positions": positions,
    }


def get_user_performance_payload(
    *,
    user_id: int,
    account_id: int | None,
    days: int,
) -> list[dict[str, Any]]:
    """Return serialized performance history from simulated daily net values."""

    if days <= 0:
        return []

    account_repo = get_simulated_account_repository()
    daily_repo = get_simulated_daily_net_value_repository()
    end_date = date.today()
    start_date = end_date - timedelta(days=max(days - 1, 0))

    if account_id is not None:
        owned_account = next(
            (account for account in account_repo.get_by_user(user_id) if int(account.account_id) == int(account_id)),
            None,
        )
        if owned_account is None:
            return []
        records = daily_repo.list_daily_records(
            int(account_id),
            start_date=start_date,
            end_date=end_date,
        )
        return [_serialize_daily_record(record) for record in records]

    accounts = account_repo.get_by_user(user_id)
    if not accounts:
        return []

    daily_totals: dict[date, dict[str, float]] = {}
    for account in accounts:
        records = daily_repo.list_daily_records(
            int(account.account_id),
            start_date=start_date,
            end_date=end_date,
        )
        for record in records:
            record_date = record["record_date"]
            bucket = daily_totals.setdefault(
                record_date,
                {
                    "net_value": 0.0,
                    "cash": 0.0,
                    "market_value": 0.0,
                    "positions_count": 0.0,
                },
            )
            bucket["net_value"] += float(record.get("net_value") or 0.0)
            bucket["cash"] += float(record.get("cash") or 0.0)
            bucket["market_value"] += float(record.get("market_value") or 0.0)
            bucket["positions_count"] += float(record.get("positions_count") or 0.0)

    if not daily_totals:
        return []

    total_initial = sum(float(account.initial_capital or 0.0) for account in accounts)
    if total_initial <= 0:
        total_initial = next(iter(daily_totals.values()))["net_value"] if daily_totals else 1.0

    rows: list[dict[str, Any]] = []
    for record_date in sorted(daily_totals.keys()):
        bucket = daily_totals[record_date]
        return_pct = (
            ((bucket["net_value"] - total_initial) / total_initial) * 100 if total_initial else 0.0
        )
        rows.append(
            {
                "date": record_date.isoformat(),
                "portfolio_value": bucket["net_value"],
                "return_pct": round(return_pct, 2),
                "cash_balance": bucket["cash"],
                "invested_value": bucket["market_value"],
                "position_count": int(bucket["positions_count"]),
            }
        )
    return rows


def _serialize_daily_record(record: DailyNetValueRecord) -> dict[str, Any]:
    """Normalize one daily net-value record for dashboard consumers."""

    return {
        "date": record["record_date"].isoformat(),
        "portfolio_value": float(record.get("net_value") or 0.0),
        "return_pct": round(float(record.get("cumulative_return") or 0.0), 2),
        "cash_balance": float(record.get("cash") or 0.0),
        "invested_value": float(record.get("market_value") or 0.0),
        "position_count": int(record.get("positions_count") or 0),
    }


def _normalize_account_type(account_type: object) -> str:
    value = getattr(account_type, "value", account_type)
    return str(value or "simulated")


def _account_type_label(account_type: object) -> str:
    return "实仓" if _normalize_account_type(account_type) == "real" else "模拟仓"


def _asset_type_label(asset_type: str) -> str:
    return {
        "equity": "股票",
        "fund": "基金",
        "bond": "债券",
    }.get(str(asset_type or "").lower(), str(asset_type or "其他"))
