"""Strict reconstruction of one simulated order's immutable fill receipt chain."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import cast

from django.core.exceptions import ObjectDoesNotExist

from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
    SettlementBasis,
    SettlementPolicyV1,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventV1,
    SimulatedOrderFillResult,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _require_hash,
    _require_token,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
)
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillAccrual,
    OrderReservationFillEconomics,
)
from apps.simulated_trading.domain.order_reservation_fill_chain import (
    OrderReservationFillChainEntry,
    validate_order_reservation_fill_chain,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    simulated_order_fill_trade_key,
)
from apps.simulated_trading.infrastructure.execution_settlement_accounting_math import (
    _money_sum,
    _net_sell_proceeds,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    _intent_from_snapshot,
    decode_order_reservation,
    fee_policy_from_snapshot,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_request_reader import (
    _settlement_scope,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    DecodedOrderReservationFillRow,
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_snapshot_codec import (
    EncodedOrderReservationFillSnapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_sqlite_precision import (
    PrecisionValue,
    require_sqlite_values,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)

_ZERO_CASH = Decimal("0.00")
_ZERO_SHARES = Decimal("0.000000")
_QUANTITY_FIELDS = frozenset({"minimum", "step", "maximum"})
_EXECUTION_RULE_FIELDS = frozenset(
    {
        "rule_id",
        "rule_version",
        "security_id",
        "market",
        "board",
        "buy_quantity",
        "sell_quantity",
        "sell_odd_lot_mode",
        "price_tick",
        "rule_source_id",
        "rule_source_version",
        "rule_source_hash",
        "source_observed_at",
        "source_available_at",
        "effective_from",
        "valid_until",
        "content_hash",
    }
)
_PRICE_RANGE_FIELDS = frozenset(
    {
        "market",
        "board",
        "price_tick",
        "buy_deviation_ratio",
        "sell_deviation_ratio",
        "buy_widening_ticks",
        "sell_widening_ticks",
        "minimum_distance_ticks",
        "lower_floor_ticks",
        "rounding_mode",
    }
)
_SUBMISSION_RULE_FIELDS = frozenset(
    {"execution_rule_v1", "price_submission_range", "allowed_stages", "content_hash"}
)
_SETTLEMENT_POLICY_FIELDS = frozenset(
    {
        "policy_id",
        "policy_version",
        "security_id",
        "market",
        "board",
        "settlement_basis",
        "settlement_lag_sessions",
        "bound_execution_rule_v2_hash",
        "source_id",
        "source_version",
        "source_hash",
        "source_observed_at",
        "source_available_at",
        "effective_from",
        "valid_until",
        "content_hash",
    }
)
_SETTLEMENT_BUNDLE_FIELDS = frozenset(
    {
        "bundle_id",
        "bundle_version",
        "execution_submission_v2",
        "settlement_policy_v1",
        "content_hash",
    }
)


@dataclass(frozen=True, slots=True)
class _TradeSettlementBindings:
    """Typed settlement columns recovered from the validated sealed plan."""

    exchange: str
    lag_sessions: int
    bundle_id: str
    bundle_version: str
    bundle_hash: str
    policy_id: str
    policy_version: str
    policy_hash: str
    execution_rule_v2_hash: str


def _plan_payload_object(
    value: object,
    *,
    expected_fields: frozenset[str],
    label: str,
) -> dict[str, object]:
    """Narrow a nested plan object and reject both missing and unknown fields."""

    payload = _json_object(value, label)
    if frozenset(payload) != expected_fields:
        raise ValueError(f"{label} fields differ from the sealed schema")
    return payload


def _plan_text(payload: dict[str, object], field_name: str) -> str:
    """Return one exact text field from the JSON plan boundary."""

    value = payload.get(field_name)
    if type(value) is not str:
        raise ValueError(f"{field_name} must be exact text")
    return value


def _plan_integer(payload: dict[str, object], field_name: str) -> int:
    """Return one exact integer field without accepting bool as an integer."""

    value = payload.get(field_name)
    if type(value) is not int:
        raise ValueError(f"{field_name} must be an exact integer")
    return value


def _plan_decimal(payload: dict[str, object], field_name: str) -> Decimal:
    """Parse bounded decimal text for the pure risk-domain rule constructors."""

    value = payload.get(field_name)
    if type(value) is not str or not value or len(value) > 257:
        raise ValueError(f"{field_name} must be bounded decimal text")
    try:
        parsed = Decimal(value)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise ValueError(f"{field_name} is invalid decimal text") from error
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _plan_datetime(payload: dict[str, object], field_name: str) -> datetime:
    """Parse one bounded timestamp for revalidation by its Domain value object."""

    value = payload.get(field_name)
    if type(value) is not str or not value or len(value) > 64:
        raise ValueError(f"{field_name} must be bounded timestamp text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{field_name} is invalid timestamp text") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _decode_plan_quantity(value: object, *, label: str) -> ExecutionQuantityConstraint:
    """Rebuild and validate one exact whole-share quantity constraint."""

    payload = _plan_payload_object(
        value,
        expected_fields=_QUANTITY_FIELDS,
        label=label,
    )
    quantity = ExecutionQuantityConstraint(
        minimum=_plan_decimal(payload, "minimum"),
        step=_plan_decimal(payload, "step"),
        maximum=_plan_decimal(payload, "maximum"),
    )
    quantity.__post_init__()
    if quantity.to_payload() != payload:
        raise ValueError(f"{label} is not in canonical Domain form")
    return quantity


def _decode_plan_execution_rule(value: object) -> AShareExecutionRule:
    """Rebuild the pure v1 rule embedded in the sealed plan's v2 bundle."""

    payload = _plan_payload_object(
        value,
        expected_fields=_EXECUTION_RULE_FIELDS,
        label="execution_rule_v1",
    )
    rule = AShareExecutionRule(
        rule_id=_plan_text(payload, "rule_id"),
        rule_version=_plan_text(payload, "rule_version"),
        security_id=_plan_text(payload, "security_id"),
        market=_plan_text(payload, "market"),
        board=_plan_text(payload, "board"),
        buy_quantity=_decode_plan_quantity(payload.get("buy_quantity"), label="buy_quantity"),
        sell_quantity=_decode_plan_quantity(payload.get("sell_quantity"), label="sell_quantity"),
        sell_odd_lot_mode=SellOddLotMode(_plan_text(payload, "sell_odd_lot_mode")),
        price_tick=_plan_decimal(payload, "price_tick"),
        rule_source_id=_plan_text(payload, "rule_source_id"),
        rule_source_version=_plan_text(payload, "rule_source_version"),
        rule_source_hash=_plan_text(payload, "rule_source_hash"),
        source_observed_at=_plan_datetime(payload, "source_observed_at"),
        source_available_at=_plan_datetime(payload, "source_available_at"),
        effective_from=_plan_datetime(payload, "effective_from"),
        valid_until=_plan_datetime(payload, "valid_until"),
        content_hash=_plan_text(payload, "content_hash"),
    )
    rule.__post_init__()
    if rule.to_payload() != payload:
        raise ValueError("execution_rule_v1 is not in canonical Domain form")
    return rule


def _decode_plan_submission_rule(value: object) -> ExecutionSubmissionRuleV2:
    """Rebuild the pure v2 rule and validate its nested hashes and scope."""

    payload = _plan_payload_object(
        value,
        expected_fields=_SUBMISSION_RULE_FIELDS,
        label="execution_submission_v2",
    )
    raw_price = _plan_payload_object(
        payload.get("price_submission_range"),
        expected_fields=_PRICE_RANGE_FIELDS,
        label="price_submission_range",
    )
    price_rule = PriceSubmissionRangeRule(
        market=_plan_text(raw_price, "market"),
        board=_plan_text(raw_price, "board"),
        price_tick=_plan_decimal(raw_price, "price_tick"),
        buy_deviation_ratio=_plan_decimal(raw_price, "buy_deviation_ratio"),
        sell_deviation_ratio=_plan_decimal(raw_price, "sell_deviation_ratio"),
        buy_widening_ticks=_plan_integer(raw_price, "buy_widening_ticks"),
        sell_widening_ticks=_plan_integer(raw_price, "sell_widening_ticks"),
        minimum_distance_ticks=_plan_integer(raw_price, "minimum_distance_ticks"),
        lower_floor_ticks=_plan_integer(raw_price, "lower_floor_ticks"),
        rounding_mode=PriceRoundingMode(_plan_text(raw_price, "rounding_mode")),
    )
    price_rule.__post_init__()
    if price_rule.to_payload() != raw_price:
        raise ValueError("price_submission_range is not in canonical Domain form")
    raw_stages = payload.get("allowed_stages")
    if type(raw_stages) is not list:
        raise ValueError("allowed_stages must be an array of exact text values")
    stages: list[PriceSubmissionStage] = []
    for stage in raw_stages:
        if type(stage) is not str:
            raise ValueError("allowed_stages must contain exact text values")
        stages.append(PriceSubmissionStage(stage))
    submission = ExecutionSubmissionRuleV2(
        execution_rule_v1=_decode_plan_execution_rule(payload.get("execution_rule_v1")),
        price_submission_range=price_rule,
        allowed_stages=tuple(stages),
        content_hash=_plan_text(payload, "content_hash"),
    )
    submission.__post_init__()
    if submission.to_payload() != payload:
        raise ValueError("execution_submission_v2 is not in canonical Domain form")
    return submission


def _decode_plan_settlement_policy(value: object) -> SettlementPolicyV1:
    """Rebuild the pure policy and validate its identity, clocks, and bound rule."""

    payload = _plan_payload_object(
        value,
        expected_fields=_SETTLEMENT_POLICY_FIELDS,
        label="settlement_policy_v1",
    )
    policy = SettlementPolicyV1(
        policy_id=_plan_text(payload, "policy_id"),
        policy_version=_plan_text(payload, "policy_version"),
        security_id=_plan_text(payload, "security_id"),
        market=_plan_text(payload, "market"),
        board=_plan_text(payload, "board"),
        settlement_basis=SettlementBasis(_plan_text(payload, "settlement_basis")),
        settlement_lag_sessions=_plan_integer(payload, "settlement_lag_sessions"),
        bound_execution_rule_v2_hash=_plan_text(payload, "bound_execution_rule_v2_hash"),
        source_id=_plan_text(payload, "source_id"),
        source_version=_plan_text(payload, "source_version"),
        source_hash=_plan_text(payload, "source_hash"),
        source_observed_at=_plan_datetime(payload, "source_observed_at"),
        source_available_at=_plan_datetime(payload, "source_available_at"),
        effective_from=_plan_datetime(payload, "effective_from"),
        valid_until=_plan_datetime(payload, "valid_until"),
        content_hash=_plan_text(payload, "content_hash"),
    )
    policy.__post_init__()
    if policy.to_payload() != payload:
        raise ValueError("settlement_policy_v1 is not in canonical Domain form")
    return policy


def _decode_plan_bundle(value: object) -> ExecutionSettlementBundleV3:
    """Rebuild the exact pure bundle, validating policy and execution-rule hashes."""

    payload = _plan_payload_object(
        value,
        expected_fields=_SETTLEMENT_BUNDLE_FIELDS,
        label="execution_bundle",
    )
    bundle = ExecutionSettlementBundleV3(
        bundle_id=_plan_text(payload, "bundle_id"),
        bundle_version=_plan_text(payload, "bundle_version"),
        execution_submission_v2=_decode_plan_submission_rule(
            payload.get("execution_submission_v2")
        ),
        settlement_policy_v1=_decode_plan_settlement_policy(payload.get("settlement_policy_v1")),
        content_hash=_plan_text(payload, "content_hash"),
    )
    bundle.__post_init__()
    if bundle.to_payload() != payload:
        raise ValueError("execution_bundle is not in canonical Domain form")
    return bundle


def _trade_settlement_bindings(
    *,
    reservation_row: SimulatedOrderReservationModel,
    intent: SimulatedTradeIntent,
    as_of: datetime,
) -> _TradeSettlementBindings:
    """Recover Trade settlement columns only from the validated typed plan snapshot."""

    try:
        snapshot = validated_plan_snapshot(reservation_row)
        exchange, lag_sessions = _settlement_scope(reservation_row)
        bundle = _decode_plan_bundle(snapshot.get("execution_bundle"))
        policy = bundle.settlement_policy_v1
        plan_bundle_id = _plan_text(snapshot, "settlement_bundle_id")
        plan_bundle_version = _plan_text(snapshot, "settlement_bundle_version")
        plan_bundle_hash = _plan_text(snapshot, "settlement_bundle_hash")
        plan_policy_id = _plan_text(snapshot, "settlement_policy_id")
        plan_policy_version = _plan_text(snapshot, "settlement_policy_version")
        plan_policy_hash = _plan_text(snapshot, "settlement_policy_hash")
        plan_execution_hash = _plan_text(snapshot, "execution_rule_v2_hash")
        plan_bundle_source_observed_at = _plan_datetime(snapshot, "bundle_source_observed_at")
        plan_bundle_source_available_at = _plan_datetime(snapshot, "bundle_source_available_at")
        plan_bundle_effective_from = _plan_datetime(snapshot, "bundle_effective_from")
        plan_bundle_valid_until = _plan_datetime(snapshot, "bundle_valid_until")
        plan_type = _plan_text(snapshot, "plan_type")
        if plan_type == "SettlementExecutionPlanV2":
            identity_v1 = ExecutionInstrumentIdentityEvidenceV1.from_payload(
                snapshot.get("identity_evidence")
            )
            identity_v1.validate_for(intent=intent, as_of=as_of)
            identity_exchange = identity_v1.source_exchange
        elif plan_type == "SettlementExecutionPlanV3":
            identity_v2 = ExecutionInstrumentIdentityEvidenceV2.from_payload(
                snapshot.get("identity_evidence")
            )
            identity_v2.validate_for(intent=intent, as_of=as_of)
            identity_exchange = identity_v2.source_exchange
        else:
            raise ValueError("sealed plan identity version is unsupported")
        for field_name, value in (
            ("settlement_bundle_id", plan_bundle_id),
            ("settlement_bundle_version", plan_bundle_version),
            ("settlement_policy_id", plan_policy_id),
            ("settlement_policy_version", plan_policy_version),
        ):
            _require_token(value, field_name)
        for field_name, value in (
            ("settlement_bundle_hash", plan_bundle_hash),
            ("settlement_policy_hash", plan_policy_hash),
            ("execution_rule_v2_hash", plan_execution_hash),
        ):
            _require_hash(value, field_name)
        plan_lag = _plan_integer(snapshot, "settlement_lag_sessions")
        if (
            exchange != identity_exchange
            or lag_sessions != plan_lag
            or policy.settlement_lag_sessions != plan_lag
            or policy.security_id != intent.security_id
            or policy.market != intent.market
            or policy.board != intent.board
            or bundle.execution_submission_v2.execution_rule_v1.security_id != intent.security_id
            or bundle.execution_submission_v2.execution_rule_v1.market != intent.market
            or bundle.execution_submission_v2.execution_rule_v1.board != intent.board
            or bundle.bundle_id != plan_bundle_id
            or bundle.bundle_version != plan_bundle_version
            or bundle.content_hash != plan_bundle_hash
            or policy.policy_id != plan_policy_id
            or policy.policy_version != plan_policy_version
            or policy.content_hash != plan_policy_hash
            or bundle.execution_submission_v2.content_hash != plan_execution_hash
            or policy.bound_execution_rule_v2_hash != plan_execution_hash
            or bundle.latest_source_observed_at != plan_bundle_source_observed_at
            or bundle.source_available_at != plan_bundle_source_available_at
            or bundle.effective_from != plan_bundle_effective_from
            or bundle.valid_until != plan_bundle_valid_until
        ):
            raise ValueError("sealed plan metadata differs from its decoded settlement bundle")
    except SimulatedTradeExecutionBlocked:
        raise
    except (
        ArithmeticError,
        AttributeError,
        SimulatedSettlementContractError,
        TypeError,
        ValueError,
    ) as error:
        raise _blocked(
            "SIMULATED_FILL_PLAN_INVALID",
            "订单封存的结算计划与执行规则无法一致解码",
        ) from error
    return _TradeSettlementBindings(
        exchange=exchange,
        lag_sessions=lag_sessions,
        bundle_id=bundle.bundle_id,
        bundle_version=bundle.bundle_version,
        bundle_hash=bundle.content_hash,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_hash=policy.content_hash,
        execution_rule_v2_hash=bundle.execution_submission_v2.content_hash,
    )


def _blocked(code: str, message: str) -> SimulatedTradeExecutionBlocked:
    """Build a stable application-level block without hiding its cause."""

    return SimulatedTradeExecutionBlocked(message, code=code)


@dataclass(frozen=True, slots=True)
class _LockedFillChain:
    """Complete validated fill prefix reconstructed from locked ORM rows."""

    reservation: OrderReservation
    intent: SimulatedTradeIntent
    fee_policy: SimulatedFeePolicyV2
    accrual: OrderReservationFillAccrual
    rows: tuple[tuple[SimulatedOrderFillReceiptModel, DecodedOrderReservationFillRow], ...]


def _resource_cash_consumed(
    *,
    economics: OrderReservationFillEconomics,
) -> Decimal:
    """Return the G1 reservation resource consumption for one validated fill."""

    if economics.side is SimulatedTradeSide.BUY:
        return _money_sum(economics.gross_amount, economics.incremental_fees.total_fee)
    net = _net_sell_proceeds(economics.gross_amount, economics.incremental_fees.total_fee)
    return net.copy_abs() if net < 0 else _ZERO_CASH


def _validate_resource_prefix(
    *,
    reservation: OrderReservation,
    rows: tuple[tuple[SimulatedOrderFillReceiptModel, DecodedOrderReservationFillRow], ...],
    accrual: OrderReservationFillAccrual,
) -> None:
    """Bind stored reservation resource counters to every validated fill."""

    cash_values = tuple(_resource_cash_consumed(economics=decoded.economics) for _, decoded in rows)
    expected_cash = _money_sum(*cash_values)
    expected_shares = (
        accrual.cumulative_quantity if reservation.side is SimulatedTradeSide.SELL else _ZERO_SHARES
    )
    if reservation.cash_consumed != expected_cash or reservation.shares_consumed != expected_shares:
        raise _blocked(
            "SIMULATED_FILL_RESERVATION_CHAIN_INVALID",
            "订单预留消耗计数与完整成交回执链不一致",
        )


def _lock_receipt_trades_for_account(
    *,
    reservation_row: SimulatedOrderReservationModel,
    receipt_rows: tuple[SimulatedOrderFillReceiptModel, ...],
    using: str,
) -> dict[int, SimulatedTradeModel]:
    """Lock only linked Trades owned by the reservation account."""

    expected_ids = tuple(receipt.trade_id for receipt in receipt_rows)
    if (
        type(reservation_row.account_id) is not int
        or reservation_row.account_id <= 0
        or any(type(trade_id) is not int or trade_id <= 0 for trade_id in expected_ids)
        or len(set(expected_ids)) != len(expected_ids)
    ):
        raise _blocked(
            "SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
            "成交回执链的账户或 Trade 定位无效",
        )
    if not expected_ids:
        return {}
    trade_rows = tuple(
        SimulatedTradeModel._default_manager.using(using)
        .select_for_update()
        .filter(account_id=reservation_row.account_id, pk__in=expected_ids)
        .order_by("pk")
    )
    trades_by_id: dict[int, SimulatedTradeModel] = {}
    for trade_row in trade_rows:
        if type(trade_row.pk) is not int or trade_row.pk in trades_by_id:
            raise _blocked(
                "SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
                "成交回执链的 Trade 定位重复或无效",
            )
        trades_by_id[trade_row.pk] = trade_row
    if set(trades_by_id) != set(expected_ids):
        raise _blocked(
            "SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
            "成交回执引用了其他账户或不存在的 Trade",
        )
    return trades_by_id


def _locked_fill_chain(
    *,
    reservation_row: SimulatedOrderReservationModel,
    using: str,
) -> _LockedFillChain:
    """Decode and validate the full immutable fee/source receipt prefix."""

    try:
        reservation = decode_order_reservation(reservation_row)
        snapshot = validated_plan_snapshot(reservation_row)
        intent = _intent_from_snapshot(snapshot)
        fee_policy = fee_policy_from_snapshot(snapshot)
        receipt_rows = tuple(
            SimulatedOrderFillReceiptModel._base_manager.using(using)
            .select_for_update()
            .filter(reservation_id=reservation_row.pk)
            .order_by("fill_sequence", "pk")
        )
        trades_by_id = _lock_receipt_trades_for_account(
            reservation_row=reservation_row,
            receipt_rows=receipt_rows,
            using=using,
        )
        decoded_rows: list[
            tuple[SimulatedOrderFillReceiptModel, DecodedOrderReservationFillRow]
        ] = []
        entries: list[OrderReservationFillChainEntry] = []
        for receipt_row in receipt_rows:
            trade_row = trades_by_id.get(receipt_row.trade_id)
            if trade_row is None:
                raise _blocked(
                    "SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
                    "成交回执未绑定到本账户的 Trade",
                )
            receipt_row.trade = trade_row
            row_prefix = "persisted_fill"
            require_sqlite_values(
                values=_trade_precision_values(
                    trade_row,
                    field_prefix=f"{row_prefix}.trade",
                ),
                using=using,
                error_code="ORDER_RESERVATION_STATE_INVALID",
            )
            decoded = read_order_reservation_fill_row(
                reservation_row=reservation_row,
                receipt_row=receipt_row,
                trade_row=trade_row,
            )
            decoded_values: tuple[PrecisionValue, ...] = (
                (f"{row_prefix}.event.quantity", decoded.event.quantity, "quantity"),
                (f"{row_prefix}.event.price", decoded.event.price, "price"),
            )
            require_sqlite_values(
                values=decoded_values
                + _fill_economics_precision_values(
                    decoded.economics,
                    field_prefix=f"{row_prefix}.economics",
                ),
                using=using,
                error_code="ORDER_RESERVATION_STATE_INVALID",
            )
            decoded_rows.append((receipt_row, decoded))
            entries.append(
                OrderReservationFillChainEntry(
                    fill_sequence=decoded.fill_sequence,
                    economics=decoded.economics,
                )
            )
        accrual = validate_order_reservation_fill_chain(
            intent=intent,
            stored_intent_payload_hash=reservation_row.intent_payload_hash,
            reservation=reservation,
            fee_policy=fee_policy,
            entries=tuple(entries),
        )
        _validate_resource_prefix(
            reservation=reservation,
            rows=tuple(decoded_rows),
            accrual=accrual,
        )
        return _LockedFillChain(
            reservation=reservation,
            intent=intent,
            fee_policy=fee_policy,
            accrual=accrual,
            rows=tuple(decoded_rows),
        )
    except SimulatedTradeExecutionBlocked:
        raise
    except (ArithmeticError, AttributeError, ObjectDoesNotExist, TypeError, ValueError) as error:
        raise _blocked(
            "SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
            "成交回执链、订单封存数据或 FeeV2 资源计数无法核对",
        ) from error


def validate_locked_order_fill_chain(
    *,
    reservation_row: SimulatedOrderReservationModel,
    using: str,
) -> None:
    """Validate the complete persisted fill prefix while parent locks are held.

    The caller must hold the account and reservation rows in the current
    transaction. This keeps cancellation on the same lock order as the fill
    writer and checks every receipt, linked Trade, FeeV2 accrual, and resource
    counter before an active reservation releases any remaining hold.
    """

    _locked_fill_chain(reservation_row=reservation_row, using=using)


def _existing_result(
    *,
    chain: _LockedFillChain,
    event: LocalSimulatedFillEventV1,
    expected_event_payload_hash: str | None,
) -> SimulatedOrderFillResult | None:
    """Replay an exact stored receipt without reading source, calendar, or clock."""

    matching = tuple(
        decoded
        for receipt, decoded in chain.rows
        if receipt.source_namespace == event.source_namespace
        and receipt.source_event_id == event.source_event_id
    )
    if len(matching) > 1:
        raise _blocked("SIMULATED_FILL_RECEIPT_INVALID", "成交定位对应多条持久回执")
    if not matching:
        return None
    decoded = matching[0]
    if decoded.event.event_payload_hash != event.event_payload_hash or (
        expected_event_payload_hash is not None
        and expected_event_payload_hash != decoded.event.event_payload_hash
    ):
        raise SimulatedTradeIdempotencyConflict("成交事件定位已绑定到不同的源摘要")
    return SimulatedOrderFillResult(
        reservation_id=decoded.reservation_id,
        source_namespace=decoded.event.source_namespace,
        source_version=decoded.event.source_version,
        event_payload_hash=decoded.event.event_payload_hash,
        economics=decoded.economics,
        reservation=chain.reservation,
        trade_id=decoded.trade_id,
        replayed=True,
    )


def _trade_precision_values(
    trade_row: SimulatedTradeModel,
    *,
    field_prefix: str,
) -> tuple[PrecisionValue, ...]:
    """Return the stored Trade amounts that the fill path reads or replays."""

    values: list[PrecisionValue] = [
        (f"{field_prefix}.quantity", trade_row.quantity, "quantity"),
        (f"{field_prefix}.price", trade_row.price, "price"),
        (f"{field_prefix}.amount", trade_row.amount, "money"),
        (f"{field_prefix}.commission", trade_row.commission, "money"),
        (f"{field_prefix}.slippage", trade_row.slippage, "money"),
        (f"{field_prefix}.total_cost", trade_row.total_cost, "money"),
    ]
    for field_name, value in (
        ("transfer_fee", trade_row.transfer_fee),
        ("stamp_duty", trade_row.stamp_duty),
    ):
        if value is not None:
            values.append((f"{field_prefix}.{field_name}", value, "money"))
    if trade_row.realized_pnl is not None:
        # The precision guard accepts nonnegative storage families. Magnitude
        # checks the signed Decimal's storage envelope without changing it.
        values.append(
            (f"{field_prefix}.realized_pnl_magnitude", trade_row.realized_pnl.copy_abs(), "money")
        )
    return tuple(values)


def _fee_precision_values(
    fees: TradeFeeBreakdown,
    *,
    field_prefix: str,
) -> tuple[PrecisionValue, ...]:
    """Return exact money components from one persisted FeeV2 breakdown."""

    return (
        (f"{field_prefix}.commission", fees.commission, "money"),
        (f"{field_prefix}.transfer_fee", fees.transfer_fee, "money"),
        (f"{field_prefix}.stamp_duty", fees.stamp_duty, "money"),
        (f"{field_prefix}.slippage", fees.slippage, "money"),
        (f"{field_prefix}.total_fee", fees.total_fee, "money"),
    )


def _fill_economics_precision_values(
    economics: OrderReservationFillEconomics,
    *,
    field_prefix: str,
) -> tuple[PrecisionValue, ...]:
    """Return the FeeV2 snapshot values used to validate a receipt prefix."""

    values: list[PrecisionValue] = [
        (f"{field_prefix}.quantity", economics.quantity, "quantity"),
        (f"{field_prefix}.price", economics.price, "price"),
        (f"{field_prefix}.limit_price", economics.limit_price, "price"),
        (f"{field_prefix}.gross_amount", economics.gross_amount, "money"),
    ]
    values.extend(
        _fee_precision_values(
            economics.incremental_fees,
            field_prefix=f"{field_prefix}.incremental_fees",
        )
    )
    for label, accrual in (
        ("prior", economics.prior),
        ("cumulative", economics.cumulative_state),
    ):
        values.extend(
            (
                (f"{field_prefix}.{label}.quantity", accrual.cumulative_quantity, "quantity"),
                (f"{field_prefix}.{label}.gross", accrual.cumulative_gross, "money"),
            )
        )
        values.extend(
            _fee_precision_values(
                accrual.cumulative_fees,
                field_prefix=f"{field_prefix}.{label}.fees",
            )
        )
    return tuple(values)


def _json_object(value: object, label: str) -> dict[str, object]:
    """Narrow one canonical JSON snapshot at the ORM JSONField boundary."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise _blocked("SIMULATED_FILL_SNAPSHOT_INVALID", f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _create_trade(
    *,
    using: str,
    account: SimulatedAccountModel,
    reservation_row: SimulatedOrderReservationModel,
    chain: _LockedFillChain,
    economics: OrderReservationFillEconomics,
    encoded: EncodedOrderReservationFillSnapshot,
    binding_payload: dict[str, object],
    binding_hash: str,
    total_cost: Decimal,
    realized_pnl: Decimal | None,
    realized_pnl_pct: float | None,
    cost_basis_known: bool | None,
    settlement_status: str | None,
    proof: OrderFillSettlementProof,
    now: datetime,
    event: LocalSimulatedFillEventV1,
) -> SimulatedTradeModel:
    """Insert one V4 Trade that is fully bound before its receipt is created."""

    intent = chain.intent
    policy = chain.fee_policy
    settlement_bindings = _trade_settlement_bindings(
        reservation_row=reservation_row,
        intent=intent,
        as_of=now,
    )
    if (
        proof.settlement_exchange != settlement_bindings.exchange
        or proof.settlement_lag_sessions != settlement_bindings.lag_sessions
    ):
        raise _blocked(
            "SIMULATED_FILL_CALENDAR_SCOPE_MISMATCH",
            "成交日历证明与订单封存的结算计划不一致",
        )
    fees = economics.incremental_fees
    evidence = proof.calendar_evidence
    publication = evidence.publication
    if publication is None:
        raise _blocked("SIMULATED_FILL_CALENDAR_INVALID", "成交日历缺少发布记录")
    if economics.side is SimulatedTradeSide.BUY:
        immediate = settlement_status == "released"
        release_date: date | None = proof.expected_release_session
    else:
        immediate = False
        release_date = None
    trade_key = simulated_order_fill_trade_key(
        reservation_id=reservation_row.pk,
        source_namespace=event.source_namespace,
        fill_event_id=economics.fill_event_id,
    )
    schedule = policy.fee_schedule_v1
    released_at = now if immediate else None
    release_session = proof.fill_market_session if immediate else None
    release_evidence = evidence if immediate else None
    release_publication = publication if immediate else None
    trade = SimulatedTradeModel._base_manager.using(using).create(
        account=account,
        asset_code=intent.asset_code,
        asset_name=intent.asset_name,
        asset_type=intent.asset_type,
        action=economics.side.value,
        quantity=economics.quantity,
        price=economics.price,
        amount=economics.gross_amount,
        commission=fees.commission,
        transfer_fee=fees.transfer_fee,
        stamp_duty=fees.stamp_duty,
        slippage=fees.slippage,
        total_cost=total_cost,
        fee_amounts_known=True,
        cost_basis_known=cost_basis_known,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        reason=intent.reason,
        signal_id=intent.signal_id,
        order_date=reservation_row.market_session,
        execution_date=proof.fill_market_session,
        execution_time=economics.fill_occurred_at,
        status="executed",
        idempotency_key=trade_key,
        request_payload_hash=encoded.receipt_hash,
        settlement_plan_binding_version=4,
        settlement_plan_binding_payload=binding_payload,
        settlement_plan_binding_hash=binding_hash,
        fee_config_id=schedule.config_id,
        fee_schedule_hash=policy.content_hash,
        fee_schedule_snapshot=policy.to_payload(),
        fee_precision_basis=schedule.precision_basis.value,
        fee_calculation_purpose=schedule.calculation_purpose.value,
        fee_rounding_policy=schedule.rounding_policy.value,
        settlement_status=settlement_status,
        settlement_security_id=intent.security_id,
        settlement_market=intent.market,
        settlement_exchange=settlement_bindings.exchange,
        settlement_board=intent.board,
        settlement_market_session=proof.fill_market_session,
        settlement_lag_sessions=settlement_bindings.lag_sessions,
        settlement_bundle_id=settlement_bindings.bundle_id,
        settlement_bundle_version=settlement_bindings.bundle_version,
        settlement_bundle_hash=settlement_bindings.bundle_hash,
        settlement_policy_id=settlement_bindings.policy_id,
        settlement_policy_version=settlement_bindings.policy_version,
        settlement_policy_hash=settlement_bindings.policy_hash,
        execution_rule_v2_hash=settlement_bindings.execution_rule_v2_hash,
        settlement_release_date=release_date,
        settlement_calendar_snapshot_id=evidence.snapshot.snapshot_id,
        settlement_calendar_content_hash=evidence.snapshot.content_hash,
        settlement_calendar_record_digest=evidence.snapshot.record_digest,
        settlement_calendar_publication_id=publication.publication_id,
        settlement_calendar_publication_hash=publication.publication_hash,
        settlement_calendar_policy_hash=publication.policy_hash,
        settlement_calendar_evidence_hash=evidence.evidence_hash,
        settlement_calendar_timezone=publication.timezone_name,
        settlement_released_at=released_at,
        settlement_release_session=release_session,
        settlement_release_calendar_snapshot_id=(
            release_evidence.snapshot.snapshot_id if release_evidence is not None else None
        ),
        settlement_release_calendar_content_hash=(
            release_evidence.snapshot.content_hash if release_evidence is not None else None
        ),
        settlement_release_calendar_record_digest=(
            release_evidence.snapshot.record_digest if release_evidence is not None else None
        ),
        settlement_release_calendar_publication_id=(
            release_publication.publication_id if release_publication is not None else None
        ),
        settlement_release_calendar_publication_hash=(
            release_publication.publication_hash if release_publication is not None else None
        ),
        settlement_release_calendar_policy_hash=(
            release_publication.policy_hash if release_publication is not None else None
        ),
        settlement_release_calendar_evidence_hash=(
            release_evidence.evidence_hash if release_evidence is not None else None
        ),
        settlement_release_calendar_timezone=(
            release_publication.timezone_name if release_publication is not None else None
        ),
    )
    return trade


def _create_receipt(
    *,
    using: str,
    encoded: EncodedOrderReservationFillSnapshot,
    event: LocalSimulatedFillEventV1,
    trade: SimulatedTradeModel,
    reservation_row: SimulatedOrderReservationModel,
) -> SimulatedOrderFillReceiptModel:
    """Append the immutable JSON receipt after its V4 Trade row has a key."""

    event_payload = _json_object(
        json.loads(encoded.source_event_snapshot_json),
        "source event snapshot",
    )
    economics_payload = _json_object(
        json.loads(encoded.economics_snapshot_json),
        "fill economics snapshot",
    )
    initial_position_mark_payload: dict[str, object] | None = None
    if encoded.initial_position_mark_evidence_json is not None:
        initial_position_mark_payload = _json_object(
            json.loads(encoded.initial_position_mark_evidence_json),
            "initial-position mark evidence",
        )
    return SimulatedOrderFillReceiptModel._base_manager.using(using).create(
        reservation=reservation_row,
        trade=trade,
        fill_sequence=encoded.fill_sequence,
        source_namespace=encoded.source_namespace,
        source_version=encoded.source_version,
        source_event_id=encoded.source_event_id,
        event_kind=event.event_kind.value,
        source_event_payload=event_payload,
        source_event_payload_hash=encoded.source_event_payload_hash,
        source_event_snapshot_hash=encoded.source_event_snapshot_hash,
        economic_request_hash=encoded.economic_request_hash,
        economics_snapshot_hash=encoded.economics_snapshot_hash,
        plan_snapshot_hash=encoded.plan_snapshot_hash,
        economics_payload=economics_payload,
        receipt_hash=encoded.receipt_hash,
        receipt_version=encoded.receipt_version,
        initial_position_mark_evidence=initial_position_mark_payload,
    )
