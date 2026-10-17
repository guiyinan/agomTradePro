"""Validate and serialize typed simulated auto-trading batch outcomes."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingBatchOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
    build_auto_trading_batch_outcome,
)

logger = logging.getLogger(__name__)

_COUNT_UNITS: dict[str, str] = {
    "requested": "account",
    "succeeded": "account",
    "failed": "account",
    "partial_account_count": "account",
    "buy_count": "trade",
    "sell_count": "trade",
    "confirmed_trade_count": "trade",
    "stored": "trade",
}


def auto_trading_count_units() -> dict[str, str]:
    """Return explicit units for aggregate counts in a fresh dictionary."""
    return dict(_COUNT_UNITS)


def build_auto_trading_batch_outcome_from_engine_results(
    requested_account_ids: tuple[int, ...],
    engine_results: object,
) -> AutoTradingBatchOutcome:
    """Normalize one post-execution engine result against the requested scope.

    Missing requested outcomes become indeterminate through the Domain builder.
    A malformed mapping or any extra result also marks retained account outcomes
    indeterminate, since the engine may have acted outside the requested scope.
    """
    valid_results: dict[int, AccountAutoTradingOutcome] = {}
    contract_drift = not isinstance(engine_results, Mapping)
    if isinstance(engine_results, Mapping):
        try:
            for raw_account_id, raw_outcome in engine_results.items():
                if (
                    type(raw_account_id) is int
                    and raw_account_id in requested_account_ids
                    and type(raw_outcome) is AccountAutoTradingOutcome
                    and raw_outcome.account_id == raw_account_id
                ):
                    if raw_account_id in valid_results:
                        contract_drift = True
                    else:
                        valid_results[raw_account_id] = raw_outcome
                else:
                    contract_drift = True
        except Exception:
            logger.exception("无法读取模拟自动交易引擎结果映射")
            contract_drift = True

    recovered_results: dict[int, AccountAutoTradingOutcome] = {}
    for account_id in requested_account_ids:
        result = valid_results.get(account_id)
        if result is None and contract_drift:
            recovered_results[account_id] = AccountAutoTradingOutcome(
                account_id=account_id,
                buy_count=0,
                sell_count=0,
                issues=(
                    AutoTradingIssue(
                        kind=AutoTradingIssueKind.FAILED,
                        stage="task_result",
                        code="EXECUTION_RESULT_UNKNOWN",
                        effects_indeterminate=True,
                    ),
                ),
            )
            continue
        if result is None:
            # Let the Domain builder distinguish an ordinary missing account result.
            continue
        if contract_drift:
            result = AccountAutoTradingOutcome(
                account_id=result.account_id,
                buy_count=result.buy_count,
                sell_count=result.sell_count,
                issues=result.issues
                + (
                    AutoTradingIssue(
                        kind=AutoTradingIssueKind.FAILED,
                        stage="task_result",
                        code="TASK_RESULT_CONTRACT_INVALID",
                        effects_indeterminate=True,
                    ),
                ),
            )
        recovered_results[account_id] = result
    return build_auto_trading_batch_outcome(requested_account_ids, recovered_results)


def build_indeterminate_auto_trading_batch(
    requested_account_ids: tuple[int, ...],
    *,
    code: str,
) -> AutoTradingBatchOutcome:
    """Build unknown-write outcomes after an engine call has begun."""
    results = {
        account_id: AccountAutoTradingOutcome(
            account_id=account_id,
            buy_count=0,
            sell_count=0,
            issues=(
                AutoTradingIssue(
                    kind=AutoTradingIssueKind.FAILED,
                    stage="task_execution",
                    code=code,
                    effects_indeterminate=True,
                ),
            ),
        )
        for account_id in requested_account_ids
    }
    return build_auto_trading_batch_outcome(requested_account_ids, results)


def serialize_auto_trading_batch_outcome(
    batch: AutoTradingBatchOutcome,
    *,
    trade_date: date,
) -> dict[str, Any]:
    """Serialize a batch for both Celery and HTTP callers with explicit units."""
    account_payloads = [account.to_payload() for account in batch.accounts]
    result_by_id = {account["account_id"]: account for account in account_payloads}
    stable_error_code = batch.reason_code
    if stable_error_code is None:
        stable_error_code = next(
            (issue.code for account in batch.accounts for issue in account.issues),
            None,
        )
    return {
        **batch.to_payload(),
        "trade_date": trade_date.isoformat(),
        "total_accounts": batch.requested,
        "results": result_by_id,
        "summary": {
            "total_buy_count": batch.buy_count,
            "total_sell_count": batch.sell_count,
            "confirmed_trade_count": batch.confirmed_trade_count,
            "stored_trade_count": batch.stored,
            "counts_unavailable": batch.counts_unavailable,
        },
        "stable_error_code": stable_error_code,
        "count_unit": "account",
        "stored_count_unit": "trade",
        "count_units": auto_trading_count_units(),
    }
