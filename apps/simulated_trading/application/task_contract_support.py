"""Pure task-boundary validation and normalized result construction helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol, TypeVar

from apps.simulated_trading.application.auto_trading_outcome_reporting import (
    auto_trading_count_units,
)
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingBatchOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
    build_auto_trading_batch_outcome,
)
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount

_TASK_OUTCOMES = {"success", "partial", "noop", "blocked", "failed"}
_MAX_TASK_BATCH_SIZE = 10_000

TaskResult = TypeVar("TaskResult", covariant=True)
DecoratedResult = TypeVar("DecoratedResult")


class _TaskRequestProtocol(Protocol):
    """Celery request fields used by bound tasks, without importing Celery."""

    retries: int


class _BoundTaskProtocol(Protocol):
    """Minimal bound-task retry surface consumed by task entrypoints."""

    request: _TaskRequestProtocol
    max_retries: int

    def retry(
        self,
        *,
        exc: BaseException,
        countdown: int,
    ) -> BaseException:
        """Build and raise a task retry exception."""

        ...


class _TypedTask(Protocol[TaskResult]):
    """Callable task object exposing its typed synchronous runner."""

    def __call__(self, *args: Any, **kwargs: Any) -> TaskResult: ...

    def run(self, *args: Any, **kwargs: Any) -> TaskResult:
        """Run the task synchronously and return its typed result."""

        ...


def _task_result(
    *,
    outcome: str,
    requested: int,
    succeeded: int,
    failed: int,
    stored: int,
    compatible_success: bool | None = None,
    **details: Any,
) -> dict[str, Any]:
    """Attach the existing normalized Celery business-outcome contract."""
    counters = (requested, succeeded, failed, stored)
    if outcome not in _TASK_OUTCOMES or any(
        type(value) is not int or value < 0 for value in counters
    ):
        raise ValueError("invalid simulated-trading task outcome")
    if succeeded + failed > requested:
        raise ValueError("simulated-trading task counters exceed requested work")
    success = outcome in {"success", "partial", "noop"}
    if compatible_success is not None:
        success = compatible_success
    return {
        "outcome": outcome,
        "success": success,
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "stored": stored,
        **details,
    }


def _failed_task_result(error: Exception, *, requested: int = 1) -> dict[str, Any]:
    """Return the existing failed envelope including the supplied error text."""
    return _task_result(
        outcome="failed",
        requested=requested,
        succeeded=0,
        failed=requested,
        stored=0,
        error=str(error),
    )


def _auto_trading_unavailable_scope_result(*, target_date: date) -> dict[str, Any]:
    """Report a default-scope failure without inventing an account denominator."""
    return {
        "outcome": "failed",
        "success": False,
        "requested": None,
        "succeeded": None,
        "failed": None,
        "partial_account_count": None,
        "stored": 0,
        "counts_unavailable": True,
        "buy_count": 0,
        "sell_count": 0,
        "confirmed_trade_count": 0,
        "reason_code": "ACCOUNT_SCOPE_UNAVAILABLE",
        "stable_error_code": "ACCOUNT_SCOPE_UNAVAILABLE",
        "task_issue": {
            "kind": AutoTradingIssueKind.FAILED.value,
            "stage": "task_scope",
            "code": "ACCOUNT_SCOPE_UNAVAILABLE",
        },
        "accounts": [],
        "trade_date": target_date.isoformat(),
        "total_accounts": None,
        "results": {},
        "summary": {
            "total_buy_count": 0,
            "total_sell_count": 0,
            "confirmed_trade_count": 0,
            "stored_trade_count": 0,
            "counts_unavailable": True,
        },
        "count_unit": "account",
        "stored_count_unit": "trade",
        "count_units": auto_trading_count_units(),
    }


def _build_pre_execution_failure_batch(
    account_ids: tuple[int, ...],
) -> AutoTradingBatchOutcome:
    """Create determinate zero-write failures for a known pre-engine scope."""
    results = {
        account_id: AccountAutoTradingOutcome(
            account_id=account_id,
            buy_count=0,
            sell_count=0,
            issues=(
                AutoTradingIssue(
                    kind=AutoTradingIssueKind.FAILED,
                    stage="task_setup",
                    code="TASK_SETUP_FAILED",
                ),
            ),
        )
        for account_id in account_ids
    }
    return build_auto_trading_batch_outcome(account_ids, results)


def select_default_auto_trading_account_ids(accounts: object) -> list[int]:
    """Validate active account rows and select only explicit simulated accounts."""
    if type(accounts) is not list:
        raise ValueError("active account repository returned an invalid collection")
    seen_ids: set[int] = set()
    selected_ids: list[int] = []
    for account in accounts:
        if not isinstance(account, SimulatedAccount):
            raise ValueError("active account repository returned an invalid account")
        if type(account.account_id) is not int or account.account_id <= 0:
            raise ValueError("active account repository returned an invalid identifier")
        if account.account_id in seen_ids:
            raise ValueError("active account repository returned duplicate identifiers")
        seen_ids.add(account.account_id)
        if type(account.account_type) is not AccountType:
            raise ValueError("active account repository returned an unknown account type")
        if account.account_type is AccountType.SIMULATED:
            selected_ids.append(account.account_id)
    if len(selected_ids) > _MAX_TASK_BATCH_SIZE:
        raise ValueError("default account scope exceeds the supported batch size")
    return selected_ids


def _parse_task_date(value: str | None, field_name: str) -> date:
    """Validate an optional ISO task date at the Application boundary."""
    if value is None:
        return date.today()
    if type(value) is not str or not value:
        raise ValueError(f"{field_name} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string") from exc


def _validate_optional_id(value: int | None, field_name: str) -> int | None:
    """Validate one optional positive integer identifier."""
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _validate_optional_ids(values: list[int] | None, field_name: str) -> list[int] | None:
    """Validate one optional bounded list of unique positive identifiers."""
    if values is None:
        return None
    if type(values) is not list or len(values) > _MAX_TASK_BATCH_SIZE:
        raise ValueError(f"{field_name} must be a bounded list")
    if any(type(value) is not int or value <= 0 for value in values):
        raise ValueError(f"{field_name} must contain positive integers")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
    return list(values)


def _require_non_negative_count(payload: Mapping[str, object], field_name: str) -> int:
    """Read one exact non-negative counter from provider evidence."""
    value = payload.get(field_name)
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value
