"""Readiness helpers for personal investment account evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.account.application.query_services import get_application_user_by_id
from apps.simulated_trading.application.query_services import (
    list_active_account_targets,
    list_dashboard_account_payloads,
)
from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
)

DEFAULT_READINESS_INITIAL_CAPITAL = Decimal("1000000.00")


@dataclass(frozen=True)
class AccountReadinessRepairRequest:
    """Request to ensure users have at least one decision-useful account."""

    user_id: int | None = None
    account_id: int | None = None
    initial_capital: Decimal = DEFAULT_READINESS_INITIAL_CAPITAL
    dry_run: bool = True


@dataclass(frozen=True)
class AccountReadinessRepairResult:
    """Outcome of checking or repairing one user's account readiness."""

    user_id: int
    status: str
    decision_ready_account_ids: list[int]
    zero_equity_account_ids: list[int]
    zero_equity_status: str
    created_account_id: int | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "status": self.status,
            "decision_ready_account_ids": self.decision_ready_account_ids,
            "zero_equity_account_ids": self.zero_equity_account_ids,
            "zero_equity_status": self.zero_equity_status,
            "created_account_id": self.created_account_id,
            "message": self.message,
        }


def repair_personal_account_readiness(
    request: AccountReadinessRepairRequest,
) -> dict[str, Any]:
    """Ensure target users have a positive-equity account for readiness runs."""

    user_ids = _resolve_target_user_ids(
        user_id=request.user_id,
        account_id=request.account_id,
    )
    results = [
        _repair_user_account_readiness(user_id=user_id, request=request) for user_id in user_ids
    ]
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    return {
        "status": _rollup_status([result.status for result in results]),
        "dry_run": request.dry_run,
        "initial_capital": str(request.initial_capital),
        "target_count": len(user_ids),
        "status_counts": status_counts,
        "results": [result.to_dict() for result in results],
    }


def _resolve_target_user_ids(*, user_id: int | None, account_id: int | None) -> list[int]:
    if user_id is not None:
        return [int(user_id)]

    user_ids: set[int] = set()
    for target in list_active_account_targets():
        if account_id is not None and int(target["account_id"]) != int(account_id):
            continue
        user_ids.add(int(target["user_id"]))
    return sorted(user_ids)


def _repair_user_account_readiness(
    *,
    user_id: int,
    request: AccountReadinessRepairRequest,
) -> AccountReadinessRepairResult:
    accounts = [
        dict(account)
        for account in list_dashboard_account_payloads(user_id)
        if request.account_id is None or int(account.get("id") or 0) == int(request.account_id)
    ]
    decision_ready_ids = [
        int(account["id"])
        for account in accounts
        if bool(account.get("is_active")) and _float_or_zero(account.get("total_value")) > 0
    ]
    zero_equity_ids = [
        int(account["id"])
        for account in accounts
        if bool(account.get("is_active")) and _float_or_zero(account.get("total_value")) <= 0
    ]
    if decision_ready_ids:
        return AccountReadinessRepairResult(
            user_id=user_id,
            status="ok",
            decision_ready_account_ids=decision_ready_ids,
            zero_equity_account_ids=zero_equity_ids,
            zero_equity_status=_zero_equity_status(
                decision_ready_ids=decision_ready_ids,
                zero_equity_ids=zero_equity_ids,
            ),
            message="decision_ready_account_exists",
        )

    user = get_application_user_by_id(user_id)
    if user is None:
        return AccountReadinessRepairResult(
            user_id=user_id,
            status="error",
            decision_ready_account_ids=[],
            zero_equity_account_ids=zero_equity_ids,
            zero_equity_status=_zero_equity_status(
                decision_ready_ids=[],
                zero_equity_ids=zero_equity_ids,
            ),
            message="user_not_found",
        )

    if request.dry_run:
        return AccountReadinessRepairResult(
            user_id=user_id,
            status="would_create",
            decision_ready_account_ids=[],
            zero_equity_account_ids=zero_equity_ids,
            zero_equity_status=_zero_equity_status(
                decision_ready_ids=[],
                zero_equity_ids=zero_equity_ids,
            ),
            message="would_create_default_simulated_account",
        )

    created = get_simulated_account_repository().create_account_model_for_user(
        user=user,
        account_name=_default_simulated_account_name(user),
        account_type="simulated",
        initial_capital=request.initial_capital,
    )
    return AccountReadinessRepairResult(
        user_id=user_id,
        status="created",
        decision_ready_account_ids=[int(created.id)],
        zero_equity_account_ids=zero_equity_ids,
        zero_equity_status=_zero_equity_status(
            decision_ready_ids=[int(created.id)],
            zero_equity_ids=zero_equity_ids,
        ),
        created_account_id=int(created.id),
        message="created_default_simulated_account",
    )


def _default_simulated_account_name(user: Any) -> str:
    username = str(getattr(user, "username", "") or f"user_{getattr(user, 'id', '')}").strip()
    return f"{username}_投研验收模拟仓"


def _rollup_status(statuses: list[str]) -> str:
    if any(status == "error" for status in statuses):
        return "error"
    if any(status in {"created", "would_create"} for status in statuses):
        return "action_required" if "would_create" in statuses else "repaired"
    if statuses and all(status == "ok" for status in statuses):
        return "ok"
    return "skipped"


def _zero_equity_status(
    *,
    decision_ready_ids: list[int],
    zero_equity_ids: list[int],
) -> str:
    if not zero_equity_ids:
        return "none"
    if decision_ready_ids:
        return "non_blocking_placeholder"
    return "blocking_no_positive_equity"


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
