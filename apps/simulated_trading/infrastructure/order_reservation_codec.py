"""Typed JSON and ORM codecs for durable simulated-order reservations."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from math import isfinite
from typing import TypeAlias, cast

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_current_reference import (
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import (
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
    validate_ledger_money,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationIdentity,
    OrderReservationRequest,
    OrderReservationStatus,
)

from .order_reservation_models import SimulatedOrderReservationModel
from .simulated_account_trade_models import PositionModel, SimulatedAccountModel

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
_PLAN_SCHEMA = "simulated-order-reservation-plan.v1"
ReservationPlan: TypeAlias = SettlementExecutionPlanV2 | SettlementExecutionPlanV3


def json_value(value: object) -> JSONValue:
    """Narrow a domain snapshot into canonical, finite JSON primitives."""

    if value is None or type(value) in (str, bool, int):
        return cast(JSONScalar, value)
    if type(value) is float:
        if not isfinite(value):
            raise _snapshot_error("snapshot contains a non-finite number")
        return value
    if type(value) is Decimal:
        number = value
        if not number.is_finite():
            raise _snapshot_error("snapshot contains a non-finite decimal")
        return format(number, "f")
    if type(value) is datetime:
        timestamp = value
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise _snapshot_error("snapshot contains a naive timestamp")
        return timestamp.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, Enum):
        enum_value = value.value
        if type(enum_value) is not str:
            raise _snapshot_error("snapshot contains an unsupported enum")
        return enum_value
    if type(value) in (list, tuple):
        items = cast(list[object] | tuple[object, ...], value)
        return [json_value(item) for item in items]
    if type(value) is dict:
        raw = cast(dict[object, object], value)
        if any(type(key) is not str for key in raw):
            raise _snapshot_error("snapshot contains a non-text key")
        return {cast(str, key): json_value(item) for key, item in raw.items()}
    raise _snapshot_error("snapshot contains an unsupported value")


def canonical_snapshot(payload: object) -> dict[str, JSONValue]:
    """Validate and canonicalize one complete persisted snapshot object."""

    value = json_value(payload)
    if type(value) is not dict:
        raise _snapshot_error("snapshot must be an object")
    return cast(dict[str, JSONValue], value)


def snapshot_digest(payload: object) -> str:
    """Hash one JSON-safe snapshot with stable key and number rendering."""

    canonical = json_value(payload)
    try:
        encoded = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise _snapshot_error("snapshot cannot be sealed") from error
    return sha256(encoded).hexdigest()


def json_object(value: object, field_name: str) -> dict[str, object]:
    """Validate a JSONField object before reading business fields."""

    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise _snapshot_error(f"stored {field_name} is not a JSON object")
    return cast(dict[str, object], value)


def plan_snapshot_payload(
    *,
    plan: ReservationPlan,
    bundle: ExecutionSettlementBundleV3,
    fee_policy: SimulatedFeePolicyV2,
) -> dict[str, JSONValue]:
    """Seal the exact plan, rule, calendar, identity, and FeeV2 evidence."""

    if type(plan) not in (SettlementExecutionPlanV2, SettlementExecutionPlanV3):
        raise _snapshot_error("unsupported settlement plan")
    if type(bundle) is not ExecutionSettlementBundleV3:
        raise _snapshot_error("unsupported settlement bundle")
    try:
        plan.__post_init__()
        bundle.__post_init__()
        fee_policy.__post_init__()
        calendar = plan.calendar_evidence
        calendar.__post_init__()
        publication = calendar.publication
        intent = plan.intent
        payload: dict[str, object] = {
            "schema": _PLAN_SCHEMA,
            "plan_type": type(plan).__name__,
            "intent": {
                "account_id": intent.account_id,
                "user_id": intent.user_id,
                "idempotency_key": intent.idempotency_key,
                "side": intent.side,
                "security_id": intent.security_id,
                "asset_code": intent.asset_code,
                "asset_name": intent.asset_name,
                "asset_type": intent.asset_type,
                "market": intent.market,
                "board": intent.board,
                "quantity": intent.quantity,
                "price": intent.price,
                "reason": intent.reason,
                "signal_id": intent.signal_id,
            },
            "market_session": plan.market_session,
            "pre_read_at": plan.pre_read_at,
            "settlement_lag_sessions": plan.settlement_lag_sessions,
            "settlement_release_date": plan.settlement_release_date,
            "settlement_bundle_id": plan.settlement_bundle_id,
            "settlement_bundle_version": plan.settlement_bundle_version,
            "settlement_bundle_hash": plan.settlement_bundle_hash,
            "settlement_policy_id": plan.settlement_policy_id,
            "settlement_policy_version": plan.settlement_policy_version,
            "settlement_policy_hash": plan.settlement_policy_hash,
            "execution_rule_v2_hash": plan.execution_rule_v2_hash,
            "bundle_source_observed_at": plan.bundle_source_observed_at,
            "bundle_source_available_at": plan.bundle_source_available_at,
            "bundle_effective_from": plan.bundle_effective_from,
            "bundle_valid_until": plan.bundle_valid_until,
            "identity_evidence": plan.identity_evidence.to_payload(),
            "execution_bundle": bundle.to_payload(),
            "calendar_evidence": {
                "snapshot": calendar.snapshot.to_payload(),
                "publication": publication.to_payload() if publication is not None else None,
                "evidence_hash": calendar.evidence_hash,
            },
            "fee_policy_v2": fee_policy.to_payload(),
        }
        return canonical_snapshot(payload)
    except SimulatedTradeExecutionBlocked:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _snapshot_error("settlement evidence could not be sealed") from error


def decode_order_reservation(row: SimulatedOrderReservationModel) -> OrderReservation:
    """Rebuild one Domain hold only after verifying its sealed snapshot and columns."""

    if (
        type(row.pk) is not int
        or type(row.account_id) is not int
        or type(row.owner_user_id) is not int
        or type(row.idempotency_key) is not str
        or type(row.intent_payload_hash) is not str
        or type(row.reservation_request_hash) is not str
        or type(row.security_id) is not str
    ):
        raise _state_error("stored reservation identity is incomplete")
    snapshot = validated_plan_snapshot(row)
    intent = _intent_from_snapshot(snapshot)
    if (
        intent.account_id != row.account_id
        or intent.user_id != row.owner_user_id
        or intent.idempotency_key != row.idempotency_key
        or intent.security_id != row.security_id
        or intent.asset_code != row.asset_code
        or intent.asset_name != row.asset_name
        or intent.side.value != row.side
        or intent.asset_type != row.asset_type
        or intent.market != row.market
        or intent.board != row.board
        or intent.quantity != decimal_field(row.quantity, "quantity")
        or intent.price != decimal_field(row.limit_price, "limit_price")
        or intent.request_payload_hash != row.intent_payload_hash
    ):
        raise _snapshot_error("stored identity or economics differ from sealed intent")
    fee_policy = fee_policy_from_snapshot(snapshot)
    schedule = fee_policy.fee_schedule_v1
    if (
        row.fee_policy_id != fee_policy.policy_id
        or row.fee_policy_version != fee_policy.policy_version
        or row.fee_config_id != schedule.config_id
        or row.fee_policy_hash != fee_policy.content_hash
    ):
        raise _snapshot_error("stored FeeV2 columns differ from sealed policy")
    _validate_fee_components(row=row, intent=intent, policy=fee_policy)
    request = OrderReservationRequest(
        account_id=row.account_id,
        security_id=row.security_id,
        idempotency_key=row.idempotency_key,
        side=SimulatedTradeSide(row.side),
        quantity=decimal_field(row.quantity, "quantity"),
        limit_price=decimal_field(row.limit_price, "limit_price"),
        asset_type=row.asset_type,
        market=row.market,
        board=row.board,
        fee_budget=(
            decimal_field(row.fee_budget, "fee_budget") if row.fee_budget is not None else None
        ),
    )
    expected_identity = request.identity(fee_policy_hash=fee_policy.content_hash)
    if expected_identity.request_payload_hash != row.reservation_request_hash:
        raise _snapshot_error("stored request hash differs from reservation economics")
    identity = OrderReservationIdentity(
        account_id=row.account_id,
        security_id=row.security_id,
        idempotency_key=row.idempotency_key,
        request_payload_hash=row.reservation_request_hash,
    )
    try:
        reservation = OrderReservation(
            identity=identity,
            side=SimulatedTradeSide(row.side),
            quantity=decimal_field(row.quantity, "quantity"),
            limit_price=decimal_field(row.limit_price, "limit_price"),
            notional=decimal_field(row.notional, "notional"),
            fee_estimate=decimal_field(row.fee_estimate, "fee_estimate"),
            fee_budget=(
                decimal_field(row.fee_budget, "fee_budget") if row.fee_budget is not None else None
            ),
            cash_reserved=decimal_field(row.cash_reserved, "cash_reserved"),
            shares_reserved=decimal_field(row.shares_reserved, "shares_reserved"),
            reserved_at=aware_field(row.reserved_at, "reserved_at"),
            status=OrderReservationStatus(row.status),
            filled_quantity=decimal_field(row.filled_quantity, "filled_quantity"),
            cash_consumed=decimal_field(row.cash_consumed, "cash_consumed"),
            shares_consumed=decimal_field(row.shares_consumed, "shares_consumed"),
            cash_released=decimal_field(row.cash_released, "cash_released"),
            shares_released=decimal_field(row.shares_released, "shares_released"),
        )
        reservation.__post_init__()
        _validate_source_snapshot(row)
        _validate_plan_columns(row=row, snapshot=snapshot)
    except SimulatedTradeExecutionBlocked:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _state_error("stored reservation failed Domain reconciliation") from error
    return reservation


def validated_plan_snapshot(
    row: SimulatedOrderReservationModel,
) -> dict[str, object]:
    """Verify version, canonical hash, and schema before reading stored evidence."""

    if row.plan_snapshot_version != 1:
        raise _snapshot_error("stored reservation snapshot version is unsupported")
    snapshot = json_object(row.plan_snapshot, "plan snapshot")
    if snapshot_digest(snapshot) != row.plan_snapshot_hash:
        raise _snapshot_error("stored reservation snapshot hash does not match payload")
    if snapshot.get("schema") != _PLAN_SCHEMA:
        raise _snapshot_error("stored reservation snapshot schema is unsupported")
    return snapshot


def fee_policy_from_snapshot(snapshot: dict[str, object]) -> SimulatedFeePolicyV2:
    """Decode and revalidate the single FeeV2 source embedded in the snapshot."""

    try:
        policy = SimulatedFeePolicyV2.from_payload(snapshot.get("fee_policy_v2"))
        policy.__post_init__()
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _snapshot_error("stored FeeV2 snapshot failed exact revalidation") from error
    return policy


def _intent_from_snapshot(snapshot: dict[str, object]) -> SimulatedTradeIntent:
    """Decode the exact caller intent stored in a sealed plan snapshot."""

    raw = json_object(snapshot.get("intent"), "intent snapshot")
    expected = {
        "account_id",
        "user_id",
        "idempotency_key",
        "side",
        "security_id",
        "asset_code",
        "asset_name",
        "asset_type",
        "market",
        "board",
        "quantity",
        "price",
        "reason",
        "signal_id",
    }
    if set(raw) != expected:
        raise _snapshot_error("stored intent snapshot fields are incomplete")
    try:
        intent = SimulatedTradeIntent(
            account_id=_int_field(raw["account_id"], "intent.account_id"),
            user_id=_int_field(raw["user_id"], "intent.user_id"),
            idempotency_key=_string_field(raw["idempotency_key"], "intent.idempotency_key"),
            side=SimulatedTradeSide(_string_field(raw["side"], "intent.side")),
            security_id=_string_field(raw["security_id"], "intent.security_id"),
            asset_code=_string_field(raw["asset_code"], "intent.asset_code"),
            asset_name=_string_field(raw["asset_name"], "intent.asset_name"),
            asset_type=_string_field(raw["asset_type"], "intent.asset_type"),
            market=_string_field(raw["market"], "intent.market"),
            board=_string_field(raw["board"], "intent.board"),
            quantity=_decimal_text(raw["quantity"], "intent.quantity"),
            price=_decimal_text(raw["price"], "intent.price"),
            reason=_string_field(raw["reason"], "intent.reason"),
            signal_id=(
                _int_field(raw["signal_id"], "intent.signal_id")
                if raw["signal_id"] is not None
                else None
            ),
        )
        intent.__post_init__()
    except SimulatedTradeExecutionBlocked:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _snapshot_error("stored intent failed exact validation") from error
    return intent


def _validate_fee_components(
    *,
    row: SimulatedOrderReservationModel,
    intent: SimulatedTradeIntent,
    policy: SimulatedFeePolicyV2,
) -> None:
    """Compare fee columns with the sealed policy calculation for the intent."""

    try:
        reserved_at = aware_field(row.reserved_at, "reserved_at")
        policy.validate_at(reserved_at)
        amount = validate_ledger_money(row.notional, "reservation.notional", allow_zero=False)
        fees = policy.calculate_for(
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            side=intent.side,
            amount=amount,
            as_of=reserved_at,
        )
        stored = (
            decimal_field(row.commission_estimate, "commission_estimate"),
            decimal_field(row.transfer_fee_estimate, "transfer_fee_estimate"),
            decimal_field(row.stamp_duty_estimate, "stamp_duty_estimate"),
            decimal_field(row.slippage_estimate, "slippage_estimate"),
            decimal_field(row.fee_estimate, "fee_estimate"),
        )
        expected = (
            fees.commission,
            fees.transfer_fee,
            fees.stamp_duty,
            fees.slippage,
            fees.total_fee,
        )
        for index, (actual, calculated) in enumerate(zip(stored, expected, strict=True)):
            validate_ledger_money(actual, f"fee_component_{index}", allow_zero=True)
            validate_ledger_money(calculated, f"fee_component_expected_{index}", allow_zero=True)
        if stored != expected:
            raise _snapshot_error("stored fee estimates differ from sealed FeeV2 policy")
    except SimulatedTradeExecutionBlocked:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _snapshot_error("stored fee estimates failed exact revalidation") from error


def _validate_plan_columns(
    *,
    row: SimulatedOrderReservationModel,
    snapshot: dict[str, object],
) -> None:
    """Require the immutable settlement columns to match their sealed plan."""

    release_date = snapshot.get("settlement_release_date")
    if release_date is None:
        expected_release = None
    elif type(release_date) is str:
        try:
            expected_release = date.fromisoformat(release_date)
        except ValueError as error:
            raise _snapshot_error("stored settlement release date is invalid") from error
    else:
        raise _snapshot_error("stored settlement release date has an invalid type")
    market_session = snapshot.get("market_session")
    if type(market_session) is not str:
        raise _snapshot_error("stored market session has an invalid type")
    try:
        parsed_session = date.fromisoformat(market_session)
    except ValueError as error:
        raise _snapshot_error("stored market session is invalid") from error
    lag = snapshot.get("settlement_lag_sessions")
    if (
        parsed_session != row.market_session
        or type(lag) is not int
        or lag != row.settlement_lag_sessions
        or expected_release != row.settlement_release_date
    ):
        raise _snapshot_error("stored settlement columns differ from sealed plan")


def _validate_source_snapshot(row: SimulatedOrderReservationModel) -> None:
    """Require source cash and sellable values to retain exact nullable meaning."""

    aware_field(row.source_snapshot_at, "source_snapshot_at")
    if row.source_book_cash is not None:
        validate_ledger_money(
            decimal_field(row.source_book_cash, "source_book_cash"),
            "source_book_cash",
            allow_zero=True,
        )
    if row.source_sellable_quantity is not None:
        validate_ledger_quantity(
            decimal_field(row.source_sellable_quantity, "source_sellable_quantity"),
            "source_sellable_quantity",
            allow_zero=True,
        )


def _decimal_text(value: object, field_name: str) -> Decimal:
    """Parse a finite canonical Decimal string from JSON without coercing other types."""

    if type(value) is not str:
        raise _snapshot_error(f"stored {field_name} is not decimal text")
    try:
        parsed = Decimal(value)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise _snapshot_error(f"stored {field_name} is invalid decimal text") from error
    if not parsed.is_finite() or format(parsed, "f") != value:
        raise _snapshot_error(f"stored {field_name} is not canonical decimal text")
    return parsed


def decimal_field(value: object, field_name: str) -> Decimal:
    """Require a Decimal from a database DecimalField without coercion."""

    if type(value) is not Decimal or not value.is_finite():
        raise _state_error(f"stored reservation {field_name} is not a finite Decimal")
    return value


def aware_field(value: object, field_name: str) -> datetime:
    """Require a stored aware datetime without inferring a missing clock."""

    if type(value) is not datetime or value.tzinfo is None:
        raise _state_error(f"stored reservation {field_name} is not timezone-aware")
    try:
        if value.utcoffset() is None:
            raise ValueError(field_name)
    except (OverflowError, TypeError, ValueError) as error:
        raise _state_error(f"stored reservation {field_name} is not timezone-aware") from error
    return value


def _int_field(value: object, field_name: str) -> int:
    """Require an exact integer in a persisted snapshot."""

    if type(value) is not int:
        raise _snapshot_error(f"stored {field_name} is not an integer")
    return value


def _string_field(value: object, field_name: str) -> str:
    """Require text in a persisted snapshot without stringifying unknown values."""

    if type(value) is not str:
        raise _snapshot_error(f"stored {field_name} is not text")
    return value


def _snapshot_error(message: str) -> SimulatedTradeExecutionBlocked:
    """Create the stable typed error for damaged or unsupported evidence JSON."""

    return SimulatedTradeExecutionBlocked(
        message,
        code="ORDER_RESERVATION_SNAPSHOT_INVALID",
    )


def _state_error(message: str) -> SimulatedTradeExecutionBlocked:
    """Create the stable typed error for inconsistent persisted ledger state."""

    return SimulatedTradeExecutionBlocked(
        message,
        code="ORDER_RESERVATION_STATE_INVALID",
    )


def current_order_reservation_book(
    *,
    account: SimulatedAccountModel,
    owner_user_id: int,
    position: PositionModel | None,
    active_rows: list[SimulatedOrderReservationModel],
    target: SimulatedOrderReservationModel | None,
    security_id: str,
    asset_code: str,
) -> OrderReservationBook:
    """Decode locked holds and current nullable balances into one Domain book."""

    if account.cash_known is True:
        book_cash = validate_ledger_money(
            decimal_field(account.current_cash, "account.current_cash"),
            "account.current_cash",
            allow_zero=True,
        )
    else:
        book_cash = None
    if position is None:
        sellable = Decimal("0.000000")
    elif position.available_quantity_known is True:
        sellable = validate_ledger_quantity(
            decimal_field(position.available_quantity, "position.available_quantity"),
            "position.available_quantity",
            allow_zero=True,
        )
    else:
        sellable = None
    rows_by_id: dict[int, SimulatedOrderReservationModel] = {}
    for row in active_rows:
        if type(row.pk) is not int or row.owner_user_id != owner_user_id:
            raise _state_error("active reservation identity is outside the locked owner scope")
        rows_by_id[row.pk] = row
    if target is not None:
        if type(target.pk) is not int or target.owner_user_id != owner_user_id:
            raise _state_error("target reservation identity is outside the locked owner scope")
        rows_by_id[target.pk] = target
    for row in rows_by_id.values():
        if row.status == SimulatedOrderReservationModel.STATUS_ACTIVE and (
            row.security_id == security_id
        ) != (row.asset_code == asset_code):
            raise SimulatedTradeExecutionBlocked(
                "active reservation security and ledger asset identities disagree",
                code="ORDER_RESERVATION_IDENTITY_CONFLICT",
            )
    reservations = tuple(
        decode_order_reservation(row) for row in (rows_by_id[key] for key in sorted(rows_by_id))
    )
    if type(account.pk) is not int:
        raise _state_error("locked simulated account identity is unavailable")
    try:
        return OrderReservationBook(
            account_id=account.pk,
            security_id=security_id,
            book_cash=book_cash,
            withdrawable_cash=None,
            sellable_shares=sellable,
            reservations=reservations,
        )
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _state_error("locked reservation book failed Domain validation") from error


__all__: tuple[str, ...] = (
    "JSONValue",
    "canonical_snapshot",
    "current_order_reservation_book",
    "decode_order_reservation",
    "decimal_field",
    "aware_field",
    "fee_policy_from_snapshot",
    "json_object",
    "plan_snapshot_payload",
    "snapshot_digest",
    "validated_plan_snapshot",
)
