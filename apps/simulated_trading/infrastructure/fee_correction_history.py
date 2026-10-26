"""Locked validation and as-of projection for simulated fee corrections.

This module deliberately refuses incomplete cash or cost histories. The
correction overlay is calculated from immutable Trade and event rows; it never
rewrites the original Trade or V4 receipt economics.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionAccountHistoryProjection,
    FeeCorrectionBlockedError,
    FeeCorrectionCashPosting,
)
from apps.simulated_trading.domain.entities import OrderStatus, SimulatedTrade, TradeAction
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.fee_correction import (
    AverageCostReplayResult,
    AverageCostReplayStep,
    CorrectableFeeComponents,
    FeeCorrectionCashEvent,
    FeeCorrectionReplayTrade,
    calculate_fee_correction_delta,
    calculate_ledger_percentage,
    replay_average_cost_history,
    require_exact_ledger_money,
    require_exact_ledger_quantity,
    require_exact_signed_ledger_money,
    subtract_ledger_money,
    sum_ledger_money,
    sum_signed_ledger_money,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
    fee_correction_account_prefix_sha256,
)
from apps.simulated_trading.infrastructure.models import UnifiedAccountCashFlowModel
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.trade_mapper import SimulatedTradeMapper

_MAX_TRADE_FEE = Decimal("99999999.99")
_SHA256_HEX = frozenset("0123456789abcdef")


def _blocked(message: str, code: str) -> FeeCorrectionBlockedError:
    """Create a stable error for unsupported or damaged correction history."""

    return FeeCorrectionBlockedError(message, code=code)


def _is_digest(value: object) -> bool:
    """Return whether the input is an exact lowercase SHA-256 token."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in _SHA256_HEX for character in value)
    )


def _aware(value: object, field_name: str) -> datetime:
    """Require one aware timestamp before comparing financial history clocks."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _blocked(f"{field_name} is not an aware timestamp", "FEE_CORRECTION_HISTORY_INVALID")
    return value


def _exact_money(value: object, field_name: str, *, allow_zero: bool = True) -> Decimal:
    """Require finite nonnegative cent money representable in the ledger."""

    try:
        if type(value) is not Decimal:
            raise TypeError(field_name)
        return require_exact_ledger_money(value, field_name, allow_zero=allow_zero)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            f"{field_name} is not exact ledger money", "FEE_CORRECTION_HISTORY_INVALID"
        ) from error


def _exact_signed_money(value: object, field_name: str) -> Decimal:
    """Require exact signed cents through the Domain's protected Decimal context."""

    if type(value) is not Decimal:
        raise _blocked(f"{field_name} is not exact Decimal money", "FEE_CORRECTION_HISTORY_INVALID")
    try:
        return require_exact_signed_ledger_money(value, field_name)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            f"{field_name} cannot be represented as cents", "FEE_CORRECTION_HISTORY_INVALID"
        ) from error


def _exact_quantity(value: object, field_name: str) -> Decimal:
    """Require positive six-decimal quantity from a stored executed Trade."""

    try:
        if type(value) is not Decimal:
            raise TypeError(field_name)
        return require_exact_ledger_quantity(value, field_name, allow_zero=False)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            f"{field_name} is not exact ledger quantity", "FEE_CORRECTION_HISTORY_INVALID"
        ) from error


def _money_add(left: Decimal, right: Decimal, field_name: str) -> Decimal:
    """Add signed cents using the canonical Domain fee arithmetic context."""

    try:
        return sum_signed_ledger_money((left, right), field_name)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            f"{field_name} cannot be calculated", "FEE_CORRECTION_HISTORY_INVALID"
        ) from error


def _money_sum(values: Sequence[Decimal], field_name: str) -> Decimal:
    """Sum nonnegative money using the canonical Domain fee arithmetic context."""

    try:
        return sum_ledger_money(values, field_name)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            f"{field_name} cannot be calculated", "FEE_CORRECTION_HISTORY_INVALID"
        ) from error


def fee_components_from_trade(trade: SimulatedTradeModel) -> CorrectableFeeComponents:
    """Read explicit original correctable fee fields; never infer null fees as zero."""

    if (
        type(trade.fee_amounts_known) is not bool
        or trade.fee_amounts_known is not True
        or trade.transfer_fee is None
        or trade.stamp_duty is None
    ):
        raise _blocked(
            "交易费用分项不完整，无法证明费用更正历史",
            "FEE_CORRECTION_FEE_HISTORY_UNKNOWN",
        )
    try:
        result = CorrectableFeeComponents(
            commission=_exact_money(trade.commission, "trade.commission"),
            transfer_fee=_exact_money(trade.transfer_fee, "trade.transfer_fee"),
            stamp_duty=_exact_money(trade.stamp_duty, "trade.stamp_duty"),
        )
        result.__post_init__()
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            "交易费用分项不满足精确账本合同",
            "FEE_CORRECTION_FEE_HISTORY_UNKNOWN",
        ) from error
    for fee in (result.commission, result.transfer_fee, result.stamp_duty):
        if fee > _MAX_TRADE_FEE:
            raise _blocked(
                "交易费用分项超出持久字段范围",
                "FEE_CORRECTION_FEE_HISTORY_INVALID",
            )
    return result


def _fee_values_from_event(
    event: SimulatedFeeCorrectionEventModel,
    prefix: str,
) -> CorrectableFeeComponents:
    """Read one persisted event's fee component triple without lossy coercion."""
    if prefix == "previous":
        commission = event.previous_commission
        transfer_fee = event.previous_transfer_fee
        stamp_duty = event.previous_stamp_duty
    elif prefix == "revised":
        commission = event.revised_commission
        transfer_fee = event.revised_transfer_fee
        stamp_duty = event.revised_stamp_duty
    else:
        raise _blocked("费用更正事件字段组未知", "FEE_CORRECTION_HISTORY_INVALID")
    return CorrectableFeeComponents(
        commission=_exact_money(commission, f"event.{prefix}_commission"),
        transfer_fee=_exact_money(transfer_fee, f"event.{prefix}_transfer_fee"),
        stamp_duty=_exact_money(stamp_duty, f"event.{prefix}_stamp_duty"),
    )


def receipt_snapshot_hash(receipt: SimulatedOrderFillReceiptModel) -> str:
    """Hash the immutable receipt locator and all content/economics seal hashes."""

    payload = {
        "receipt_id": receipt.pk,
        "reservation_id": receipt.reservation_id,
        "trade_id": receipt.trade_id,
        "fill_sequence": receipt.fill_sequence,
        "source_namespace": receipt.source_namespace,
        "source_version": receipt.source_version,
        "source_event_id": receipt.source_event_id,
        "event_kind": receipt.event_kind,
        "source_event_payload_hash": receipt.source_event_payload_hash,
        "source_event_snapshot_hash": receipt.source_event_snapshot_hash,
        "economic_request_hash": receipt.economic_request_hash,
        "economics_snapshot_hash": receipt.economics_snapshot_hash,
        "plan_snapshot_hash": receipt.plan_snapshot_hash,
        "receipt_hash": receipt.receipt_hash,
        "receipt_version": receipt.receipt_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def correction_event_payload_hash(event: SimulatedFeeCorrectionEventModel) -> str:
    """Rebuild the immutable idempotency payload seal from one stored event."""

    authority_snapshot = event.authority_snapshot_json
    if type(authority_snapshot) is not dict:
        authority_snapshot = {}

    payload: dict[str, object] = {
        "schema": "simulated-fee-correction-request.v1",
        "account_id": event.account_id,
        "trade_id": event.trade_id,
        "idempotency_key": event.idempotency_key,
        "expected_revision": event.revision - 1,
        "expected_predecessor_id": event.previous_event_id,
        "trade_snapshot_hash": event.trade_snapshot_hash,
        "source_namespace": event.source_namespace,
        "source_record_id": event.source_record_id,
        "source_evidence_hash": event.source_evidence_hash,
        "source_payload_hash": event.source_payload_hash,
        "source_observed_at": _aware(event.source_observed_at, "event.source_observed_at")
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "previous_fees": {
            "commission": format(event.previous_commission, ".2f"),
            "transfer_fee": format(event.previous_transfer_fee, ".2f"),
            "stamp_duty": format(event.previous_stamp_duty, ".2f"),
        },
        "revised_fees": {
            "commission": format(event.revised_commission, ".2f"),
            "transfer_fee": format(event.revised_transfer_fee, ".2f"),
            "stamp_duty": format(event.revised_stamp_duty, ".2f"),
        },
        "verifier_identity": event.verifier_identity,
        "actor_user_id": event.actor_user_id,
        "authority_identity": event.authority_identity,
        "authority_record_id": event.authority_record_id,
        "authority_hash": event.authority_hash,
        "policy_version": authority_snapshot.get("policy_version"),
        "policy_sha256": authority_snapshot.get("policy_sha256"),
        "policy_enabled": authority_snapshot.get("policy_enabled"),
        "policy_allows_operator_attested_upload": authority_snapshot.get(
            "policy_allows_operator_attested_upload"
        ),
        "policy_ledger_currency": authority_snapshot.get("policy_ledger_currency"),
        "policy_valid_from": authority_snapshot.get("policy_valid_from"),
        "policy_valid_until": authority_snapshot.get("policy_valid_until"),
        "policy_updated_by_id": authority_snapshot.get("policy_updated_by_id"),
        "principal_enabled": authority_snapshot.get("principal_enabled"),
        "authorization_scope": authority_snapshot.get("authorization_scope"),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def account_ledger_currency_from_events(
    event_rows: Sequence[SimulatedFeeCorrectionEventModel],
) -> str | None:
    """Return the established account currency, rejecting missing or mixed snapshots."""

    established_currency: str | None = None
    for event in event_rows:
        if type(event) is not SimulatedFeeCorrectionEventModel:
            raise _blocked(
                "账户费用更正历史包含未知事件类型",
                "FEE_CORRECTION_HISTORY_INVALID",
            )
        snapshot = event.authority_snapshot_json
        if type(snapshot) is not dict:
            raise _blocked(
                "账户费用更正历史缺少权限币种快照",
                "FEE_CORRECTION_HISTORY_INVALID",
            )
        currency = snapshot.get("policy_ledger_currency")
        if (
            type(currency) is not str
            or len(currency) != 3
            or any(character < "A" or character > "Z" for character in currency)
        ):
            raise _blocked(
                "账户费用更正历史缺少有效账本币种",
                "FEE_CORRECTION_HISTORY_INVALID",
            )
        if established_currency is None:
            established_currency = currency
        elif currency != established_currency:
            raise _blocked(
                "账户费用更正历史混用不同账本币种",
                "FEE_CORRECTION_CURRENCY_MISMATCH",
            )
    return established_currency


def require_account_ledger_currency(
    *,
    event_rows: Sequence[SimulatedFeeCorrectionEventModel],
    authorization_currency: str,
) -> str:
    """Require one explicit current policy currency to continue the account ledger."""

    if (
        type(authorization_currency) is not str
        or len(authorization_currency) != 3
        or any(character < "A" or character > "Z" for character in authorization_currency)
    ):
        raise _blocked(
            "费用更正授权未提供有效账本币种",
            "FEE_CORRECTION_AUTHORITY_INVALID",
        )
    established_currency = account_ledger_currency_from_events(event_rows)
    if established_currency is not None and authorization_currency != established_currency:
        raise _blocked(
            "费用更正授权币种与账户账本既有币种不一致",
            "FEE_CORRECTION_CURRENCY_MISMATCH",
        )
    return established_currency or authorization_currency


def receipt_hashes_for_trades(
    *,
    trade_ids: tuple[int, ...],
    using: str,
    lock_rows: bool,
) -> dict[int, SimulatedOrderFillReceiptModel]:
    """Load unique receipt rows for selected trades, preserving the caller's lock mode."""

    if not trade_ids:
        return {}
    queryset = (
        SimulatedOrderFillReceiptModel._base_manager.using(using)
        .filter(trade_id__in=trade_ids)
        .order_by("trade_id", "pk")
    )
    if lock_rows:
        queryset = queryset.select_for_update(of=("self",))
    by_trade: dict[int, SimulatedOrderFillReceiptModel] = {}
    for receipt in queryset:
        if receipt.trade_id in by_trade:
            raise _blocked(
                "一笔模拟交易关联多条成交回执",
                "SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
            )
        by_trade[receipt.trade_id] = receipt
    return by_trade


def _cash_delta_for_trade(trade: SimulatedTradeModel) -> Decimal:
    """Reconstruct the original account cash movement from stored exact economics."""

    if trade.status != OrderStatus.EXECUTED.value:
        raise _blocked("现金账本包含非成交交易", "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED")
    if trade.action not in (TradeAction.BUY.value, TradeAction.SELL.value):
        raise _blocked("交易动作未知，无法重建账户现金", "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED")
    amount = _exact_money(trade.amount, "trade.amount", allow_zero=False)
    total_cost = _exact_money(trade.total_cost, "trade.total_cost")
    commission = _exact_money(trade.commission, "trade.commission")
    transfer_fee = _exact_money(trade.transfer_fee, "trade.transfer_fee")
    stamp_duty = _exact_money(trade.stamp_duty, "trade.stamp_duty")
    slippage = _exact_money(trade.slippage, "trade.slippage")
    if type(trade.fee_amounts_known) is not bool or trade.fee_amounts_known is not True:
        raise _blocked("账户含费用未知的成交", "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED")
    fees = _money_sum((commission, transfer_fee, stamp_duty, slippage), "trade.total_fees")
    expected_total_cost = (
        _money_add(amount, fees, "trade.buy_total_cost")
        if trade.action == TradeAction.BUY.value
        else fees
    )
    if expected_total_cost != total_cost:
        raise _blocked("交易费用与保存的现金成本不一致", "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED")
    if trade.action == TradeAction.BUY.value:
        return _exact_signed_money(total_cost.copy_negate(), "trade.buy_cash_delta")
    try:
        return subtract_ledger_money(amount, total_cost, "trade.sell_cash_delta")
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            "trade.sell_cash_delta cannot be calculated",
            "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED",
        ) from error


def _reconstruct_cash_by_posting_time(
    *,
    initial_cash: Decimal,
    trade_rows: Sequence[SimulatedTradeModel],
    event_rows: Sequence[SimulatedFeeCorrectionEventModel],
) -> Decimal:
    """Apply original and correction postings in their persisted ledger-time order.

    Trade ``created_at`` records when the account-locked Trade writer persisted
    the cash movement. Corrections use their lock-sampled ``posted_at``. Rows
    sharing one timestamp have no persisted cross-table order, so this checks
    the worst case with all debits before credits and never assumes a refund
    funded a same-time purchase.
    """

    postings: list[tuple[datetime, Decimal]] = []
    seen_trade_ids: set[int] = set()
    created_at_by_trade: dict[int, datetime] = {}
    for trade in trade_rows:
        if type(trade.pk) is not int or trade.pk in seen_trade_ids:
            raise _blocked(
                "账户交易历史身份重复或无效",
                "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED",
            )
        seen_trade_ids.add(trade.pk)
        if trade.status in (
            OrderStatus.PENDING.value,
            OrderStatus.CANCELLED.value,
            OrderStatus.FAILED.value,
        ):
            continue
        if trade.status != OrderStatus.EXECUTED.value:
            raise _blocked("账户交易状态未知", "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED")
        posted_at = _aware(trade.created_at, "trade.created_at").astimezone(UTC)
        created_at_by_trade[trade.pk] = posted_at
        postings.append((posted_at, _cash_delta_for_trade(trade)))
    for event in event_rows:
        posted_at = _aware(event.posted_at, "event.posted_at").astimezone(UTC)
        target_created_at = created_at_by_trade.get(event.trade_id)
        if target_created_at is None or target_created_at > posted_at:
            raise _blocked(
                "费用更正入账时间早于目标 Trade 的现金入账记录",
                "FEE_CORRECTION_CASH_HISTORY_ORDER_UNKNOWN",
            )
        postings.append((posted_at, _exact_signed_money(event.cash_delta, "event.cash_delta")))

    postings.sort(key=lambda posting: posting[0])
    cash = _exact_money(initial_cash, "account.initial_capital")
    index = 0
    while index < len(postings):
        posting_time = postings[index][0]
        same_time: list[Decimal] = []
        while index < len(postings) and postings[index][0] == posting_time:
            same_time.append(postings[index][1])
            index += 1
        debits = tuple(delta for delta in same_time if delta < 0)
        try:
            debit_total = sum_signed_ledger_money(
                debits,
                "account.same_time_debits",
            )
            posting_total = sum_signed_ledger_money(
                tuple(same_time),
                "account.same_time_postings",
            )
            cash_after_debits = _money_add(
                cash,
                debit_total,
                "account.cash_before_same_time_credits",
            )
            cash_after_group = _money_add(
                cash,
                posting_total,
                "account.cash_after_posting_group",
            )
        except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
            raise _blocked(
                "账户现金入账时间线无法精确重建",
                "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED",
            ) from error
        if cash_after_group < 0:
            raise _blocked(
                "账户现金入账时间线出现已证明的透支",
                "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED",
            )
        if cash_after_debits < 0:
            raise _blocked(
                "同一入账时点的现金扣款顺序无法证明不透支",
                "FEE_CORRECTION_CASH_HISTORY_ORDER_UNKNOWN",
            )
        cash = cash_after_group
    return cash


def validate_cash_ledger(
    *,
    account: SimulatedAccountModel,
    trade_rows: Sequence[SimulatedTradeModel],
    event_rows: Sequence[SimulatedFeeCorrectionEventModel],
    using: str,
) -> None:
    """Prove current cash from initial capital, every supported Trade, and corrections."""

    if (
        account.account_type != "simulated"
        or account.cash_known is not True
        or account.cash_reconciliation_status != "simulated_ledger"
    ):
        raise _blocked("模拟账户现金账本未核实", "ACCOUNT_CASH_UNKNOWN")
    initial = _exact_money(account.initial_capital, "account.initial_capital")
    current = _exact_money(account.current_cash, "account.current_cash")
    current_market_value = _exact_money(
        account.current_market_value, "account.current_market_value"
    )
    total_value = _exact_money(account.total_value, "account.total_value")

    cash_flows = tuple(
        UnifiedAccountCashFlowModel._base_manager.using(using)
        .filter(account_id=account.pk)
        .order_by("pk")
    )
    initial_flow_count = 0
    for flow in cash_flows:
        flow_amount = _exact_money(flow.amount, "cash_flow.amount")
        if (
            flow.flow_type != "initial_capital"
            or flow.source_app != "simulated_trading"
            or flow.source_id != ""
            or flow_amount != initial
        ):
            raise _blocked(
                "账户存在现金更正未支持的外部或非初始现金流",
                "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED",
            )
        initial_flow_count += 1
    if initial_flow_count > 1:
        raise _blocked(
            "模拟账户存在重复初始入金记录",
            "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED",
        )

    if any(trade.account_id != account.pk for trade in trade_rows):
        raise _blocked("账户交易历史越界", "FEE_CORRECTION_CASH_HISTORY_UNSUPPORTED")
    reconstructed = _reconstruct_cash_by_posting_time(
        initial_cash=initial,
        trade_rows=trade_rows,
        event_rows=event_rows,
    )
    if reconstructed != current:
        raise _blocked(
            "模拟账户现金与完整初始资金、成交及更正历史不一致",
            "FEE_CORRECTION_CASH_RECONCILIATION_FAILED",
        )
    expected_total = _money_add(current, current_market_value, "account.total_value")
    if total_value != expected_total:
        raise _blocked(
            "模拟账户总资产与现金及持仓市值不一致",
            "FEE_CORRECTION_ACCOUNT_VALUE_RECONCILIATION_FAILED",
        )


def validate_event_chains(
    *,
    account: SimulatedAccountModel,
    trade_rows: Sequence[SimulatedTradeModel],
    event_rows: Sequence[SimulatedFeeCorrectionEventModel],
    receipt_by_trade: Mapping[int, SimulatedOrderFillReceiptModel],
    fingerprint_by_trade: Mapping[int, str],
) -> dict[int, tuple[SimulatedFeeCorrectionEventModel, ...]]:
    """Validate every account correction chain against immutable Trade and receipt snapshots."""

    trades_by_id: dict[int, SimulatedTradeModel] = {}
    for trade in trade_rows:
        if type(trade.pk) is not int or trade.pk <= 0 or trade.pk in trades_by_id:
            raise _blocked("账户 Trade 主键重复或无效", "FEE_CORRECTION_HISTORY_INVALID")
        trades_by_id[trade.pk] = trade

    account_ledger_currency_from_events(event_rows)

    account_revisions = [event.account_revision for event in event_rows]
    if any(type(revision) is not int or revision <= 0 for revision in account_revisions) or sorted(
        account_revisions
    ) != list(range(1, len(account_revisions) + 1)):
        raise _blocked(
            "账户费用更正序号前缀缺失、重复或不连续",
            "FEE_CORRECTION_HISTORY_INVALID",
        )
    expected_prefix = fee_correction_account_genesis_sha256(account.pk)
    previous_posted_at: datetime | None = None
    for event in sorted(event_rows, key=lambda row: row.account_revision):
        posted_at = _aware(event.posted_at, "event.posted_at")
        if event.account_predecessor_hash != expected_prefix or (
            previous_posted_at is not None and posted_at < previous_posted_at
        ):
            raise _blocked(
                "账户费用更正前缀链断裂或时间逆序",
                "FEE_CORRECTION_HISTORY_INVALID",
            )
        authority_snapshot_sha256 = event.authority_snapshot_sha256
        if type(authority_snapshot_sha256) is not str or not _is_digest(authority_snapshot_sha256):
            raise _blocked(
                "账户费用更正授权快照摘要缺失或无效",
                "FEE_CORRECTION_HISTORY_INVALID",
            )
        expected_prefix = fee_correction_account_prefix_sha256(
            account_id=event.account_id,
            account_revision=event.account_revision,
            predecessor_sha256=event.account_predecessor_hash,
            request_payload_sha256=event.request_payload_hash,
            cash_delta=_exact_signed_money(event.cash_delta, "event.cash_delta"),
            authority_snapshot_sha256=authority_snapshot_sha256,
            posted_at=posted_at,
            posting_date=event.posting_date,
        )
        if event.account_prefix_hash != expected_prefix:
            raise _blocked(
                "账户费用更正前缀摘要与事件内容不一致",
                "FEE_CORRECTION_HISTORY_INVALID",
            )
        previous_posted_at = posted_at

    grouped: dict[int, list[SimulatedFeeCorrectionEventModel]] = defaultdict(list)
    keys: set[str] = set()
    for event in event_rows:
        if (
            event.account_id != account.pk
            or event.trade_id not in trades_by_id
            or trades_by_id[event.trade_id].account_id != account.pk
            or type(event.actor_user_id) is not int
            or event.actor_user_id <= 0
            or type(event.pk) is not int
            or event.pk <= 0
        ):
            raise _blocked("费用更正事件账户或 Trade 身份无效", "FEE_CORRECTION_HISTORY_INVALID")
        if event.idempotency_key in keys:
            raise _blocked("账户费用更正幂等键重复", "FEE_CORRECTION_HISTORY_INVALID")
        keys.add(event.idempotency_key)
        if not all(
            _is_digest(value)
            for value in (
                event.request_payload_hash,
                event.trade_snapshot_hash,
                event.source_evidence_hash,
                event.source_payload_hash,
                event.authority_hash,
            )
        ):
            raise _blocked("费用更正事件哈希无效", "FEE_CORRECTION_HISTORY_INVALID")
        if event.request_payload_hash != correction_event_payload_hash(event):
            raise _blocked("费用更正请求语义哈希与事件内容不一致", "FEE_CORRECTION_HISTORY_INVALID")
        trade = trades_by_id[event.trade_id]
        receipt = receipt_by_trade.get(event.trade_id)
        if receipt is not None:
            expected_receipt_hash = receipt_snapshot_hash(receipt)
            if event.receipt_snapshot_hash != expected_receipt_hash:
                raise _blocked(
                    "费用更正事件成交回执快照已变化", "FEE_CORRECTION_TRADE_SNAPSHOT_CONFLICT"
                )
        elif event.receipt_snapshot_hash is not None:
            raise _blocked(
                "普通交易更正事件错误绑定成交回执", "FEE_CORRECTION_TRADE_SNAPSHOT_CONFLICT"
            )
        if (
            event.trade_id not in fingerprint_by_trade
            or event.trade_snapshot_hash != fingerprint_by_trade[event.trade_id]
        ):
            raise _blocked(
                "费用更正事件 Trade 经济快照已变化", "FEE_CORRECTION_TRADE_SNAPSHOT_CONFLICT"
            )
        trade_time = _aware(trade.execution_time, "trade.execution_time")
        observed_at = _aware(event.source_observed_at, "event.source_observed_at")
        verified_at = _aware(event.evidence_verified_at, "event.evidence_verified_at")
        posted_at = _aware(event.posted_at, "event.posted_at")
        if (
            observed_at > verified_at
            or verified_at > posted_at
            or trade_time > posted_at
            or event.posting_date != timezone.localdate(posted_at)
            or type(event.source_namespace) is not str
            or not event.source_namespace
            or type(event.source_record_id) is not str
            or not event.source_record_id
            or type(event.verifier_identity) is not str
            or not event.verifier_identity
            or type(event.authority_identity) is not str
            or not event.authority_identity
            or type(event.authority_record_id) is not str
            or not event.authority_record_id
        ):
            raise _blocked("费用更正事件来源、授权或时间顺序无效", "FEE_CORRECTION_HISTORY_INVALID")
        grouped[event.trade_id].append(event)

    result: dict[int, tuple[SimulatedFeeCorrectionEventModel, ...]] = {}
    for trade_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: (row.revision, row.pk))
        trade = trades_by_id[trade_id]
        previous = fee_components_from_trade(trade)
        previous_id: int | None = None
        for expected_revision, event in enumerate(ordered, start=1):
            if (
                event.revision != expected_revision
                or event.previous_event_id != previous_id
                or event.revised_commission > _MAX_TRADE_FEE
                or event.revised_transfer_fee > _MAX_TRADE_FEE
                or event.revised_stamp_duty > _MAX_TRADE_FEE
            ):
                raise _blocked(
                    "费用更正版本链断裂或金额超出字段范围", "FEE_CORRECTION_REVISION_CONFLICT"
                )
            persisted_previous = _fee_values_from_event(event, "previous")
            revised = _fee_values_from_event(event, "revised")
            slippage = _exact_money(trade.slippage, "trade.slippage")
            if persisted_previous != previous or event.original_slippage != slippage:
                raise _blocked(
                    "费用更正前值与 Trade/前序更正不一致", "FEE_CORRECTION_REVISION_CONFLICT"
                )
            try:
                delta = calculate_fee_correction_delta(persisted_previous, revised)
            except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
                raise _blocked(
                    "费用更正差额不能精确重建", "FEE_CORRECTION_HISTORY_INVALID"
                ) from error
            if (
                event.commission_delta != delta.commission
                or event.transfer_fee_delta != delta.transfer_fee
                or event.stamp_duty_delta != delta.stamp_duty
                or event.total_fee_delta != delta.total_fee_delta
                or event.cash_delta != delta.cash_delta
            ):
                raise _blocked("费用更正差额与现金方向不一致", "FEE_CORRECTION_HISTORY_INVALID")
            previous = revised
            previous_id = event.pk
        result[trade_id] = tuple(ordered)
    return result


def _effective_fee_map(
    *,
    trade_rows: Sequence[SimulatedTradeModel],
    events_by_trade: Mapping[int, tuple[SimulatedFeeCorrectionEventModel, ...]],
    as_of: datetime,
    overrides: Mapping[int, CorrectableFeeComponents] | None = None,
) -> dict[int, CorrectableFeeComponents]:
    """Resolve each executed Trade's source-supported fee components as of one instant."""

    result: dict[int, CorrectableFeeComponents] = {}
    checked_overrides = overrides or {}
    for trade in trade_rows:
        if trade.status != OrderStatus.EXECUTED.value:
            continue
        if _aware(trade.execution_time, "trade.execution_time") > as_of:
            continue
        override = checked_overrides.get(trade.pk)
        if override is not None:
            override.__post_init__()
            result[trade.pk] = override
            continue
        visible = tuple(
            event
            for event in events_by_trade.get(trade.pk, ())
            if _aware(event.posted_at, "event.posted_at") <= as_of
        )
        result[trade.pk] = (
            _fee_values_from_event(visible[-1], "revised")
            if visible
            else fee_components_from_trade(trade)
        )
    return result


def replay_asset_history(
    *,
    account_id: int,
    asset_code: str,
    trade_rows: Sequence[SimulatedTradeModel],
    fee_map: Mapping[int, CorrectableFeeComponents],
) -> tuple[AverageCostReplayResult, dict[int, AverageCostReplayStep]]:
    """Replay every executed trade for one exact asset and return indexed steps."""

    replay_rows: list[FeeCorrectionReplayTrade] = []
    for trade in trade_rows:
        if (
            trade.account_id != account_id
            or trade.asset_code != asset_code
            or trade.status != OrderStatus.EXECUTED.value
            or trade.pk not in fee_map
        ):
            continue
        if (
            type(trade.fee_amounts_known) is not bool
            or trade.fee_amounts_known is not True
            or type(trade.cost_basis_known) is not bool
            or trade.cost_basis_known is not True
        ):
            raise _blocked(
                "目标资产存在费用或成本基数未知的成交",
                "FEE_CORRECTION_ASSET_HISTORY_UNKNOWN",
            )
        quantity = _exact_quantity(trade.quantity, "trade.quantity")
        amount = _exact_money(trade.amount, "trade.amount", allow_zero=False)
        slippage = _exact_money(trade.slippage, "trade.slippage")
        side = {
            TradeAction.BUY.value: SimulatedTradeSide.BUY,
            TradeAction.SELL.value: SimulatedTradeSide.SELL,
        }.get(trade.action)
        if side is None:
            raise _blocked("目标资产交易动作未知", "FEE_CORRECTION_ASSET_HISTORY_UNKNOWN")
        replay_rows.append(
            FeeCorrectionReplayTrade(
                trade_id=trade.pk,
                account_id=account_id,
                asset_code=asset_code,
                execution_time=_aware(trade.execution_time, "trade.execution_time"),
                side=side,
                quantity=quantity,
                amount=amount,
                fee_components=fee_map[trade.pk],
                original_slippage=slippage,
                fee_amounts_known=True,
                cost_basis_known=True,
            )
        )
    try:
        result = replay_average_cost_history(tuple(replay_rows))
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            "目标资产完整成交历史无法重放", "FEE_CORRECTION_ASSET_HISTORY_UNKNOWN"
        ) from error
    return result, {step.trade_id: step for step in result.steps}


def project_trades_as_of(
    *,
    account_id: int,
    trade_rows: Sequence[SimulatedTradeModel],
    events_by_trade: Mapping[int, tuple[SimulatedFeeCorrectionEventModel, ...]],
    receipt_by_trade: Mapping[int, SimulatedOrderFillReceiptModel],
    as_of: datetime,
    start_date: date | None,
    end_date: date | None,
) -> FeeCorrectionAccountHistoryProjection:
    """Project the full eligible trade history, then apply output date filters."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise _blocked("费用更正查询时点必须带时区", "FEE_CORRECTION_AS_OF_INVALID")
    visible_events_by_trade = {
        trade_id: tuple(
            event for event in events if _aware(event.posted_at, "event.posted_at") <= as_of
        )
        for trade_id, events in events_by_trade.items()
    }
    trade_by_id = {row.pk: row for row in trade_rows}
    touched_assets = {
        trade_by_id[trade_id].asset_code
        for trade_id, events in visible_events_by_trade.items()
        if events and trade_id in trade_by_id
    }
    output_by_trade: dict[int, SimulatedTrade] = {}
    for trade in trade_rows:
        if trade.status == OrderStatus.EXECUTED.value:
            if _aware(trade.execution_time, "trade.execution_time") > as_of:
                continue
        elif _aware(trade.created_at, "trade.created_at") > as_of:
            continue
        mapped = SimulatedTradeMapper.to_entity(trade)
        output_by_trade[trade.pk] = mapped

    for asset_code in touched_assets:
        rows_for_asset = tuple(
            row
            for row in trade_rows
            if row.asset_code == asset_code
            and row.status == OrderStatus.EXECUTED.value
            and _aware(row.execution_time, "trade.execution_time") <= as_of
        )
        fee_map = _effective_fee_map(
            trade_rows=rows_for_asset,
            events_by_trade=visible_events_by_trade,
            as_of=as_of,
        )
        _, steps = replay_asset_history(
            account_id=account_id,
            asset_code=asset_code,
            trade_rows=rows_for_asset,
            fee_map=fee_map,
        )
        for row in rows_for_asset:
            entity = output_by_trade[row.pk]
            fees = fee_map[row.pk]
            slippage = _exact_money(row.slippage, "trade.slippage")
            total_fees = _money_sum(
                (fees.commission, fees.transfer_fee, fees.stamp_duty, slippage),
                "trade.effective_fees",
            )
            effective_total_cost = (
                _money_add(
                    _exact_money(row.amount, "trade.amount"),
                    total_fees,
                    "trade.effective_total_cost",
                )
                if row.action == TradeAction.BUY.value
                else total_fees
            )
            step = steps.get(row.pk)
            realized = step.realized_pnl if step is not None else None
            realized_pct: float | None = None
            if (
                step is not None
                and step.realized_pnl is not None
                and step.allocated_sale_cost is not None
            ):
                try:
                    realized_pct = float(
                        calculate_ledger_percentage(
                            step.realized_pnl,
                            step.allocated_sale_cost,
                        )
                    )
                except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
                    raise _blocked(
                        "目标资产卖出收益率无法精确重建",
                        "FEE_CORRECTION_ASSET_HISTORY_UNKNOWN",
                    ) from error
            corrections = visible_events_by_trade.get(row.pk, ())
            effective_predecessors = tuple(
                event
                for trade_id, events in visible_events_by_trade.items()
                if trade_id in trade_by_id
                and trade_by_id[trade_id].asset_code == asset_code
                and _aware(trade_by_id[trade_id].execution_time, "trade.execution_time")
                <= _aware(row.execution_time, "trade.execution_time")
                for event in events
            )
            attached_events = tuple(
                FeeCorrectionCashEvent(
                    event_id=event.pk,
                    posting_date=event.posting_date,
                    posted_at=event.posted_at,
                    cash_delta=_exact_signed_money(event.cash_delta, "event.cash_delta"),
                )
                for event in corrections
            )
            output_by_trade[row.pk] = replace(
                entity,
                effective_commission=float(fees.commission),
                effective_transfer_fee=float(fees.transfer_fee),
                effective_stamp_duty=float(fees.stamp_duty),
                effective_total_cost=float(effective_total_cost),
                effective_realized_pnl=(float(realized) if realized is not None else None),
                effective_realized_pnl_pct=realized_pct,
                fee_correction_revision=(
                    max(event.revision for event in corrections) if corrections else None
                ),
                fee_correction_overlay_applied=bool(effective_predecessors),
                fee_correction_cash_events=attached_events,
            )

    projected_trades = tuple(
        trade
        for trade in sorted(
            output_by_trade.values(),
            key=lambda row: (row.execution_date, row.execution_time, row.trade_id),
        )
        if (start_date is None or trade.execution_date >= start_date)
        and (end_date is None or trade.execution_date <= end_date)
    )
    account_cash_events = tuple(
        sorted(
            (
                FeeCorrectionCashPosting(
                    event=FeeCorrectionCashEvent(
                        event_id=event.pk,
                        posting_date=event.posting_date,
                        posted_at=event.posted_at,
                        cash_delta=_exact_signed_money(event.cash_delta, "event.cash_delta"),
                    ),
                    account_revision=event.account_revision,
                    account_prefix_sha256=event.account_prefix_hash,
                )
                for events in visible_events_by_trade.values()
                for event in events
                if (start_date is None or event.posting_date >= start_date)
                and (end_date is None or event.posting_date <= end_date)
            ),
            key=lambda event: (event.posted_at, event.event_id),
        )
    )
    return FeeCorrectionAccountHistoryProjection(
        account_id=account_id,
        as_of=as_of,
        trades=projected_trades,
        cash_events=account_cash_events,
    )


__all__ = [
    "fee_components_from_trade",
    "correction_event_payload_hash",
    "account_ledger_currency_from_events",
    "require_account_ledger_currency",
    "project_trades_as_of",
    "receipt_hashes_for_trades",
    "receipt_snapshot_hash",
    "replay_asset_history",
    "validate_cash_ledger",
    "validate_event_chains",
]
