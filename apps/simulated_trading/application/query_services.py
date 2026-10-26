"""Application-level query helpers for cross-app simulated trading access."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, TypedDict

from apps.simulated_trading.application.ports import DailyNetValueRecord
from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
    get_simulated_daily_net_value_repository,
    get_simulated_position_repository,
)
from apps.simulated_trading.domain.entities import AccountType
from shared.numeric import safe_float


class AccountBindingIdentity(TypedDict):
    """Exact owner-scoped identity and eligibility needed to bind a real account."""

    owner_user_id: int
    account_id: int
    account_type: str
    is_active: bool


def get_position_snapshots(account_id: int | str) -> list[dict[str, Any]]:
    """Return lightweight position snapshots for account-level planning."""
    try:
        resolved_account_id = int(account_id)
    except ValueError as exc:
        raise ValueError("account_id must be an integer") from exc
    snapshots: list[dict[str, Any]] = get_simulated_position_repository().get_position_snapshots(
        account_id=resolved_account_id
    )
    return snapshots


def list_held_asset_codes() -> list[str]:
    """Return distinct asset codes held in simulated-trading positions."""

    asset_codes: list[str] = get_simulated_position_repository().list_held_asset_codes()
    return asset_codes


def list_active_account_models_for_user(user_id: int) -> list[Any]:
    """Return active account rows for UI contexts that rely on model display helpers."""
    accounts: list[Any] = get_simulated_account_repository().get_active_account_models_for_user(
        user_id
    )
    return accounts


def list_active_account_targets() -> list[dict[str, Any]]:
    """Return active account/user id pairs for scheduled application jobs."""

    targets: list[dict[str, Any]] = get_simulated_account_repository().list_active_account_targets()
    return targets


def get_user_account_totals(
    user_id: int,
) -> dict[str, float | None | bool | str] | None:
    """Return aggregated totals across one user's simulated accounts."""

    accounts = get_simulated_account_repository().get_by_user(user_id)
    if not accounts:
        return None

    cash_known = all(account.cash_known is True for account in accounts)
    cash_statuses = {
        (
            account.cash_reconciliation_status.value
            if account.cash_reconciliation_status is not None
            else "unverified"
        )
        for account in accounts
    }
    cash_status = (
        "quantity_only"
        if "quantity_only" in cash_statuses
        else "unverified" if not cash_known else "simulated_ledger"
    )
    total_asset_values = [safe_float(account.total_value) for account in accounts]
    initial_capital_values = [safe_float(account.initial_capital) for account in accounts]
    cash_values = [safe_float(account.current_cash) for account in accounts]
    invested_values = [safe_float(account.current_market_value) for account in accounts]
    original_returns = [safe_float(account.total_return) for account in accounts]
    position_repo = get_simulated_position_repository()
    valuation_known = all(
        position.valuation_known is True
        for account in accounts
        for position in position_repo.get_by_account(account.account_id)
        if position.quantity > 0
    )
    total_assets_known = all(value is not None for value in total_asset_values)
    initial_capital_known = all(value is not None for value in initial_capital_values)
    cash_values_known = all(value is not None for value in cash_values)
    invested_values_known = all(value is not None for value in invested_values)
    initial_capital = (
        sum(value for value in initial_capital_values if value is not None)
        if initial_capital_known
        else None
    )
    total_assets = (
        sum(value for value in total_asset_values if value is not None)
        if total_assets_known
        else None
    )
    cash_balance = (
        sum(value for value in cash_values if value is not None)
        if cash_known and cash_values_known
        else None
    )
    invested_value = (
        sum(value for value in invested_values if value is not None)
        if valuation_known and invested_values_known
        else None
    )
    performance_reason_code = (
        "ACCOUNT_CASH_UNKNOWN"
        if not cash_known or not cash_values_known
        else (
            "POSITION_VALUATION_UNKNOWN"
            if not valuation_known or not invested_values_known
            else (
                "INITIAL_CAPITAL_UNKNOWN"
                if not initial_capital_known or initial_capital is None or initial_capital <= 0
                else "ACCOUNT_VALUE_UNKNOWN" if total_assets is None else None
            )
        )
    )
    effective_performance_known = performance_reason_code is None
    total_return = (
        total_assets - initial_capital
        if effective_performance_known and total_assets is not None and initial_capital is not None
        else None
    )
    total_return_pct = (
        total_return / initial_capital * 100
        if total_return is not None and initial_capital is not None and initial_capital > 0
        else None
    )
    invested_ratio = (
        invested_value / total_assets
        if invested_value is not None and total_assets is not None and total_assets > 0
        else None
    )
    original_total_return = (
        sum(value for value in original_returns if value is not None)
        if all(value is not None for value in original_returns)
        else None
    )
    original_total_return_pct = (
        original_total_return / initial_capital * 100
        if original_total_return is not None and initial_capital is not None and initial_capital > 0
        else None
    )

    return {
        "total_assets": (
            total_assets if total_assets_known and valuation_known and cash_known else None
        ),
        "initial_capital": initial_capital,
        "cash_balance": cash_balance,
        "invested_value": invested_value,
        "invested_ratio": (
            invested_ratio
            if valuation_known and invested_values_known and cash_known and total_assets_known
            else None
        ),
        "total_return": total_return,
        "total_return_pct": total_return_pct,
        "original_total_return": original_total_return,
        "original_total_return_pct": original_total_return_pct,
        "performance_reason_code": performance_reason_code,
        "cash_known": cash_known,
        "cash_reconciliation_status": cash_status,
    }


def list_dashboard_account_payloads(user_id: int) -> list[dict[str, Any]]:
    """Return current account cards and label the stored return as an original snapshot."""

    accounts = get_simulated_account_repository().get_by_user(user_id)
    valuation_by_account = {
        account.account_id: all(
            position.valuation_known is True
            for position in get_simulated_position_repository().get_by_account(account.account_id)
            if position.quantity > 0
        )
        for account in accounts
    }
    ordered_accounts = sorted(
        accounts,
        key=lambda account: (
            _normalize_account_type(getattr(account, "account_type", "")),
            -float(getattr(account, "total_value", 0.0) or 0.0) if account.cash_known else 0.0,
        ),
    )
    return [
        {
            "id": account.account_id,
            "name": account.account_name,
            "type_code": _normalize_account_type(account.account_type),
            "type_label": _account_type_label(account.account_type),
            "total_value": _known_account_total_value(
                account,
                valuation_known=valuation_by_account[account.account_id],
            ),
            "cash": safe_float(account.current_cash) if account.cash_known is True else None,
            "market_value": (
                safe_float(account.current_market_value)
                if valuation_by_account[account.account_id]
                else None
            ),
            "total_return": _effective_account_total_return(
                account,
                valuation_known=valuation_by_account[account.account_id],
            ),
            "original_total_return": safe_float(account.total_return),
            "performance_metrics_known": _effective_account_total_return(
                account,
                valuation_known=valuation_by_account[account.account_id],
            )
            is not None,
            "performance_reason_code": _account_total_return_reason(
                account,
                valuation_known=valuation_by_account[account.account_id],
            ),
            "cash_known": account.cash_known,
            "cash_reconciliation_status": (
                account.cash_reconciliation_status.value
                if account.cash_reconciliation_status is not None
                else "unverified"
            ),
            "valuation_known": valuation_by_account[account.account_id],
            "valuation_status": (
                "unconfirmed" if valuation_by_account[account.account_id] else "unknown"
            ),
            "blocking_reason_codes": [
                *(
                    []
                    if valuation_by_account[account.account_id]
                    else ["POSITION_VALUATION_UNKNOWN"]
                ),
                *([] if account.cash_known else ["ACCOUNT_CASH_UNKNOWN"]),
                *(
                    ["INITIAL_CAPITAL_UNKNOWN"]
                    if _account_total_return_reason(
                        account,
                        valuation_known=valuation_by_account[account.account_id],
                    )
                    == "INITIAL_CAPITAL_UNKNOWN"
                    else []
                ),
            ],
            "is_active": bool(account.is_active),
        }
        for account in ordered_accounts
    ]


def _known_account_total_value(account: Any, *, valuation_known: bool) -> float | None:
    """Return current account value only when cash and position values are known."""

    if account.cash_known is not True or not valuation_known:
        return None
    return safe_float(account.total_value)


def _effective_account_total_return(account: Any, *, valuation_known: bool) -> float | None:
    """Recompute return from corrected current equity instead of a stale cache."""

    total_value = _known_account_total_value(account, valuation_known=valuation_known)
    initial_capital = safe_float(account.initial_capital)
    if total_value is None or initial_capital is None or initial_capital <= 0:
        return None
    return total_value - initial_capital


def _account_total_return_reason(account: Any, *, valuation_known: bool) -> str | None:
    """Explain why the effective account return is unavailable."""

    if account.cash_known is not True:
        return "ACCOUNT_CASH_UNKNOWN"
    if not valuation_known:
        return "POSITION_VALUATION_UNKNOWN"
    initial_capital = safe_float(account.initial_capital)
    if initial_capital is None or initial_capital <= 0:
        return "INITIAL_CAPITAL_UNKNOWN"
    if safe_float(account.total_value) is None:
        return "ACCOUNT_VALUE_UNKNOWN"
    return None


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
                "cost_basis_known": position.cost_basis_known,
                "cost_basis_status": position.cost_basis_status,
                "current_price": (
                    float(position.current_price) if position.valuation_known else None
                ),
                "market_value": float(position.market_value) if position.valuation_known else None,
                "unrealized_pnl": (
                    float(position.unrealized_pnl)
                    if position.valuation_known and position.cost_basis_known is True
                    else None
                ),
                "unrealized_pnl_pct": (
                    position.unrealized_pnl_pct
                    if position.valuation_known and position.cost_basis_known is True
                    else None
                ),
                "valuation_known": position.valuation_known,
                "valuation_status": "unconfirmed" if position.valuation_known else "unknown",
                "opened_at": (
                    position.first_buy_date.strftime("%Y-%m-%d") if position.first_buy_date else ""
                ),
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
    """Return the scoped account projection required by live risk checks.

    This application facade intentionally hides ORM models from broker execution and
    gives cross-app callers a stable, read-only projection. Position quantities use
    the persisted available balance; missing or inconsistent balances make the
    complete projection unavailable. This ledger projection is not broker settlement
    or reservation evidence.
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
    if account.cash_known is not True:
        return None
    positions: list[dict[str, Any]] = []
    for position in position_repo.get_by_account(account.account_id):
        if position.available_quantity_known is not True:
            return None
        if position.valuation_known is not True:
            return None
        quantity = _execution_projection_quantity(position.quantity)
        available_quantity = _execution_projection_quantity(
            getattr(position, "available_quantity", None)
        )
        if quantity is None or available_quantity is None or available_quantity > quantity:
            return None
        positions.append(
            {
                "asset_code": position.asset_code,
                "quantity": float(quantity),
                "available_quantity": float(available_quantity),
                "current_price": float(position.current_price or 0),
                "market_value": float(position.market_value or 0),
                "cost_basis_known": position.cost_basis_known,
                "cost_basis_status": position.cost_basis_status,
                "cost_basis_usable_for_decision": position.cost_basis_known is True,
            }
        )
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


def get_account_binding_identity(
    *,
    owner_user_id: int,
    account_id: int,
) -> AccountBindingIdentity | None:
    """Read exact owner, account type, and active eligibility without financial data."""

    if type(owner_user_id) is not int or owner_user_id <= 0:
        return None
    if type(account_id) is not int or account_id <= 0:
        return None

    account = next(
        (
            item
            for item in get_simulated_account_repository().get_by_user(owner_user_id)
            if type(item.account_id) is int and item.account_id == account_id
        ),
        None,
    )
    if account is None:
        return None
    if type(account.account_type) is not AccountType or type(account.is_active) is not bool:
        return None

    return {
        "owner_user_id": owner_user_id,
        "account_id": account.account_id,
        "account_type": account.account_type.value,
        "is_active": account.is_active,
    }


def _execution_projection_quantity(value: object) -> Decimal | None:
    """Return one finite, nonnegative ledger quantity or mark it unavailable."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        quantity = Decimal(str(value))
        numeric_value = float(quantity)
    except (InvalidOperation, OverflowError, TypeError, ValueError):
        return None
    if (
        not quantity.is_finite()
        or quantity < 0
        or not isfinite(numeric_value)
        or Decimal(str(numeric_value)) != quantity
    ):
        return None
    return quantity


class PerformanceHistoryRow(TypedDict):
    """Stored and effective daily account values; returns are percentage points."""

    date: str
    portfolio_value: float | None
    return_pct: float | None
    cash_balance: float | None
    invested_value: float
    position_count: int
    original_portfolio_value: float | None
    original_return_pct: float | None
    performance_known: bool
    performance_reason_code: str | None


def get_user_performance_payload(
    *,
    user_id: int,
    account_id: int | None,
    days: int | None,
) -> list[PerformanceHistoryRow]:
    """Return serialized performance history from simulated daily net values."""

    if days is not None and days <= 0:
        return []

    account_repo = get_simulated_account_repository()
    daily_repo = get_simulated_daily_net_value_repository()
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1) if days is not None else None

    if account_id is not None:
        owned_account = next(
            (
                account
                for account in account_repo.get_by_user(user_id)
                if int(account.account_id) == int(account_id)
            ),
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
    daily_initial: dict[date, float] = {}
    unknown_basis_dates: set[date] = set()
    unknown_correction_dates: set[date] = set()
    unknown_cash_dates: set[date] = set()
    unknown_original_dates: set[date] = set()
    for account in accounts:
        initial_capital = safe_float(account.initial_capital)
        records = daily_repo.list_daily_records(
            int(account.account_id),
            start_date=start_date,
            end_date=end_date,
        )
        for record in records:
            record_date = record["record_date"]
            coverage_known = record.get("correction_coverage_known") is True
            if not coverage_known:
                unknown_correction_dates.add(record_date)
            # A later account must not contribute capital to earlier observations.
            # Normal capital resets atomically delete that account's old history.
            if initial_capital is None or initial_capital <= 0:
                unknown_basis_dates.add(record_date)
            else:
                daily_initial[record_date] = daily_initial.get(record_date, 0.0) + initial_capital
            bucket = daily_totals.setdefault(
                record_date,
                {
                    "net_value": 0.0,
                    "original_net_value": 0.0,
                    "cash": 0.0,
                    "market_value": 0.0,
                    "positions_count": 0.0,
                },
            )
            effective_value = safe_float(record.get("net_value"))
            original_value = safe_float(record.get("original_net_value", record.get("net_value")))
            cash = safe_float(record.get("cash"))
            market_value = safe_float(record.get("market_value"))
            positions_count = safe_float(record.get("positions_count"))
            if effective_value is None:
                unknown_correction_dates.add(record_date)
            else:
                bucket["net_value"] += effective_value
            if cash is None:
                unknown_cash_dates.add(record_date)
            else:
                bucket["cash"] += cash
            if original_value is None:
                unknown_original_dates.add(record_date)
            else:
                bucket["original_net_value"] += original_value
            if market_value is not None:
                bucket["market_value"] += market_value
            if positions_count is not None:
                bucket["positions_count"] += positions_count

    if not daily_totals:
        return []

    rows: list[PerformanceHistoryRow] = []
    for record_date in sorted(daily_totals.keys()):
        bucket = daily_totals[record_date]
        total_initial = daily_initial.get(record_date, 0.0)
        correction_known = record_date not in unknown_correction_dates
        original_known = record_date not in unknown_original_dates
        return_pct = (
            round(((bucket["net_value"] - total_initial) / total_initial) * 100, 2)
            if correction_known and total_initial > 0 and record_date not in unknown_basis_dates
            else None
        )
        original_return_pct = (
            round(((bucket["original_net_value"] - total_initial) / total_initial) * 100, 2)
            if original_known and total_initial > 0 and record_date not in unknown_basis_dates
            else None
        )
        reason_code = (
            "FEE_CORRECTION_COVERAGE_UNKNOWN"
            if not correction_known
            else (
                "INITIAL_CAPITAL_UNKNOWN"
                if record_date in unknown_basis_dates or total_initial <= 0
                else None
            )
        )
        rows.append(
            {
                "date": record_date.isoformat(),
                "portfolio_value": bucket["net_value"] if correction_known else None,
                "return_pct": return_pct,
                "cash_balance": (
                    bucket["cash"]
                    if correction_known and record_date not in unknown_cash_dates
                    else None
                ),
                "invested_value": bucket["market_value"],
                "position_count": int(bucket["positions_count"]),
                "original_portfolio_value": (
                    bucket["original_net_value"] if original_known else None
                ),
                "original_return_pct": original_return_pct,
                "performance_known": return_pct is not None,
                "performance_reason_code": reason_code,
            }
        )
    return rows


def _serialize_daily_record(record: DailyNetValueRecord) -> PerformanceHistoryRow:
    """Serialize effective values only when the correction prefix is covered."""

    correction_known = record["correction_coverage_known"] is True
    effective_value = safe_float(record["net_value"]) if correction_known else None
    effective_return = safe_float(record["cumulative_return"]) if correction_known else None
    reason_code = record.get("effective_metrics_reason_code")
    if not correction_known:
        reason_code = "FEE_CORRECTION_COVERAGE_UNKNOWN"
    elif effective_return is None:
        reason_code = reason_code or "PERFORMANCE_METRIC_VALUE_UNKNOWN"
    original_value = safe_float(record.get("original_net_value", record["net_value"]))
    original_return = safe_float(
        record.get("original_cumulative_return", record["cumulative_return"])
    )

    return {
        "date": record["record_date"].isoformat(),
        "portfolio_value": effective_value,
        "return_pct": round(effective_return, 2) if effective_return is not None else None,
        "cash_balance": safe_float(record["cash"]) if correction_known else None,
        "invested_value": safe_float(record["market_value"], default=0.0),
        "position_count": int(record.get("positions_count") or 0),
        "original_portfolio_value": original_value,
        "original_return_pct": round(original_return, 2) if original_return is not None else None,
        "performance_known": effective_return is not None and effective_value is not None,
        "performance_reason_code": reason_code,
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
