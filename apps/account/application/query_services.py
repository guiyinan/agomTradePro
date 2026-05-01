"""Application-level query helpers for cross-app account access."""

from __future__ import annotations

from typing import Any

from apps.account.application.repository_provider import (
    get_account_interface_repository,
    get_account_position_repository,
    get_portfolio_snapshot_repository,
)


def list_global_investment_rule_payloads() -> list[dict[str, Any]]:
    """Return active global investment rule payloads for dashboard hints."""

    return get_account_interface_repository().list_global_investment_rule_payloads()


def get_portfolio_snapshot_performance_data(portfolio_id: int) -> list[dict[str, Any]]:
    """Return chart-ready historical portfolio snapshots."""

    rows = get_portfolio_snapshot_repository().list_performance_rows(portfolio_id)
    if not rows:
        return []

    base_value = float(rows[0]["total_value"] or 0.0) or 1.0
    return [
        {
            "date": row["snapshot_date"].isoformat(),
            "portfolio_value": float(row["total_value"]),
            "return_pct": round(((float(row["total_value"]) - base_value) / base_value) * 100, 2),
            "cash_balance": float(row["cash_balance"]),
            "invested_value": float(row["invested_value"]),
            "position_count": int(row["position_count"]),
        }
        for row in rows
    ]


def get_position_detail_payload(user_id: int, asset_code: str) -> dict[str, Any] | None:
    """Return one active position payload from the account domain."""

    position = get_account_position_repository().get_user_position_by_asset_code(
        user_id=user_id,
        asset_code=asset_code,
    )
    if position is None:
        return None

    return {
        "id": position.id,
        "asset_code": position.asset_code,
        "asset_name": "",
        "quantity": float(position.shares),
        "avg_cost": float(position.avg_cost),
        "current_price": float(position.current_price),
        "market_value": float(position.market_value),
        "unrealized_pnl": float(position.unrealized_pnl),
        "unrealized_pnl_pct": position.unrealized_pnl_pct,
        "opened_at": position.opened_at,
        "asset_class": getattr(position.asset_class, "value", position.asset_class),
        "region": getattr(position.region, "value", position.region),
    }
