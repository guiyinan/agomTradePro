"""Add a bounded, exact-unit SQLite storage contract for order reservations."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

from apps.simulated_trading.infrastructure.order_reservation_sqlite_precision import (
    OrderReservationPrecisionCheck,
    PrecisionFamily,
    sqlite_decimal_fits,
)

_PLAN_SCHEMA = "simulated-order-reservation-plan.v1"
_PLAN_KEYS = {
    "schema",
    "plan_type",
    "intent",
    "market_session",
    "pre_read_at",
    "settlement_lag_sessions",
    "settlement_release_date",
    "settlement_bundle_id",
    "settlement_bundle_version",
    "settlement_bundle_hash",
    "settlement_policy_id",
    "settlement_policy_version",
    "settlement_policy_hash",
    "execution_rule_v2_hash",
    "bundle_source_observed_at",
    "bundle_source_available_at",
    "bundle_effective_from",
    "bundle_valid_until",
    "identity_evidence",
    "execution_bundle",
    "calendar_evidence",
    "fee_policy_v2",
}
_INTENT_KEYS = {
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
_MONEY_FIELDS = (
    "notional",
    "fee_estimate",
    "fee_budget",
    "commission_estimate",
    "transfer_fee_estimate",
    "stamp_duty_estimate",
    "slippage_estimate",
    "cash_reserved",
    "cash_consumed",
    "cash_released",
    "source_book_cash",
)
_QUANTITY_FIELDS = (
    "quantity",
    "shares_reserved",
    "filled_quantity",
    "shares_consumed",
    "shares_released",
    "source_sellable_quantity",
)


def _fail(row_id: object, detail: str) -> RuntimeError:
    """Create a migration refusal without exposing stored financial values."""

    return RuntimeError(
        "SQLite reservation precision preflight refused row "
        f"{row_id!r}: {detail}; no stored row was rewritten"
    )


def _snapshot_digest(value: object) -> str:
    """Reproduce the v1 reservation snapshot's canonical JSON digest."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return sha256(encoded).hexdigest()


def _domain_payload_digest(value: dict[str, object]) -> str:
    """Reproduce the exact UTF-8 JSON digest used by persisted Domain identities."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _decimal_numeric_text(value: Decimal) -> str:
    """Match Domain identity decimal spelling without ambient context rounding."""

    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int) or len(parts.digits) > 64 or abs(exponent) > 64:
        raise ValueError("decimal identity value is outside the bounded canonical form")
    digits = list(parts.digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    normalized = Decimal((parts.sign, tuple(digits), exponent))
    return format(normalized, "f")


def _intent_and_request_digests(row: Any, intent: dict[str, object]) -> tuple[str, str]:
    """Rebuild both stable identities bound by the canonical snapshot and row."""

    quantity_text = intent.get("quantity")
    price_text = intent.get("price")
    if type(quantity_text) is not str or type(price_text) is not str:
        raise ValueError("sealed intent Decimal fields must be canonical strings")
    quantity = Decimal(quantity_text)
    price = Decimal(price_text)
    fee_budget = _decimal_field(row, "fee_budget", nullable=True)
    intent_digest = _domain_payload_digest(
        {
            "account_id": intent["account_id"],
            "user_id": intent["user_id"],
            "side": intent["side"],
            "security_id": intent["security_id"],
            "asset_code": intent["asset_code"],
            "asset_name": intent["asset_name"],
            "asset_type": intent["asset_type"],
            "market": intent["market"],
            "board": intent["board"],
            "quantity": _decimal_numeric_text(quantity),
            "price": _decimal_numeric_text(price),
            "reason": intent["reason"],
            "signal_id": intent["signal_id"],
        }
    )
    request_digest = _domain_payload_digest(
        {
            "schema": "simulated-order-reservation-request.v1",
            "account_id": row.account_id,
            "security_id": row.security_id,
            "side": row.side,
            "quantity": _decimal_numeric_text(quantity),
            "limit_price": _decimal_numeric_text(price),
            "asset_type": row.asset_type,
            "market": row.market,
            "board": row.board,
            "fee_budget": (_decimal_numeric_text(fee_budget) if fee_budget is not None else None),
            "fee_policy_hash": row.fee_policy_hash,
        }
    )
    return intent_digest, request_digest


def _is_sha256(value: object) -> bool:
    """Check one lowercase SHA-256 hex field without accepting coercions."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _decimal_field(row: Any, field_name: str, *, nullable: bool) -> Decimal | None:
    """Require one finite, canonical Decimal returned by a historical model."""

    value = getattr(row, field_name)
    if value is None and nullable:
        return None
    if type(value) is not Decimal or not value.is_finite():
        raise _fail(row.pk, f"{field_name} is not a finite Decimal")
    return value


def _supports_sqlite_decimal(value: Decimal | None, family: PrecisionFamily) -> bool:
    """Check the fixed storage envelope and decimal quantum for one column."""

    return value is None or sqlite_decimal_fits(value, family)


def _validate_plan_binding(row: Any) -> None:
    """Verify the canonical sealed plan and its row-critical identity fields."""

    snapshot = row.plan_snapshot
    if (
        row.plan_snapshot_version != 1
        or type(snapshot) is not dict
        or set(snapshot) != _PLAN_KEYS
        or snapshot.get("schema") != _PLAN_SCHEMA
        or snapshot.get("plan_type")
        not in ("SettlementExecutionPlanV2", "SettlementExecutionPlanV3")
    ):
        raise _fail(row.pk, "sealed plan version or schema is unsupported")
    try:
        if _snapshot_digest(snapshot) != row.plan_snapshot_hash:
            raise _fail(row.pk, "sealed plan digest does not match the stored payload")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise _fail(row.pk, "sealed plan is not canonical JSON") from error

    intent = snapshot.get("intent")
    if type(intent) is not dict or set(intent) != _INTENT_KEYS:
        raise _fail(row.pk, "sealed intent fields are incomplete")
    expected_identity: tuple[tuple[str, object], ...] = (
        ("account_id", row.account_id),
        ("user_id", row.owner_user_id),
        ("idempotency_key", row.idempotency_key),
        ("side", row.side),
        ("security_id", row.security_id),
        ("asset_code", row.asset_code),
        ("asset_name", row.asset_name),
        ("asset_type", row.asset_type),
        ("market", row.market),
        ("board", row.board),
    )
    if any(
        type(intent.get(key)) is not type(value) or intent.get(key) != value
        for key, value in expected_identity
    ):
        raise _fail(row.pk, "sealed intent identity differs from reservation columns")
    if type(intent["quantity"]) is not str or type(intent["price"]) is not str:
        raise _fail(row.pk, "sealed intent amounts are not canonical text")
    try:
        quantity = Decimal(intent["quantity"])
        price = Decimal(intent["price"])
    except (InvalidOperation, TypeError, ValueError) as error:
        raise _fail(row.pk, "sealed intent amounts are invalid") from error
    if quantity != row.quantity or price != row.limit_price:
        raise _fail(row.pk, "sealed intent amounts differ from reservation columns")

    if not _is_sha256(row.intent_payload_hash) or not _is_sha256(row.reservation_request_hash):
        raise _fail(row.pk, "stored intent or reservation request digest is malformed")
    try:
        intent_hash, request_hash = _intent_and_request_digests(row, intent)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _fail(row.pk, "stored intent or reservation request identity is invalid") from error
    if intent_hash != row.intent_payload_hash or request_hash != row.reservation_request_hash:
        raise _fail(row.pk, "stored intent/request identity digest differs from sealed economics")

    release_date = snapshot.get("settlement_release_date")
    if release_date is not None and type(release_date) is not str:
        raise _fail(row.pk, "sealed settlement release date is not canonical text")
    try:
        session_text = snapshot.get("market_session")
        if type(session_text) is not str:
            raise ValueError("market session is not text")
        parsed_session = date.fromisoformat(session_text)
        parsed_release = date.fromisoformat(release_date) if type(release_date) is str else None
    except (TypeError, ValueError) as error:
        raise _fail(row.pk, "sealed settlement dates are invalid") from error
    if (
        parsed_session != row.market_session
        or type(snapshot.get("settlement_lag_sessions")) is not int
        or snapshot["settlement_lag_sessions"] != row.settlement_lag_sessions
        or parsed_release != row.settlement_release_date
        or (row.settlement_release_date.isoformat() if row.settlement_release_date else None)
        != release_date
    ):
        raise _fail(row.pk, "sealed settlement scope differs from stored columns")
    for key in ("identity_evidence", "execution_bundle", "calendar_evidence", "fee_policy_v2"):
        if type(snapshot.get(key)) is not dict:
            raise _fail(row.pk, f"sealed {key} object is missing")
    calendar = snapshot["calendar_evidence"]
    if type(calendar.get("snapshot")) is not dict or not _is_sha256(calendar.get("evidence_hash")):
        raise _fail(row.pk, "sealed calendar evidence is incomplete")
    policy = snapshot["fee_policy_v2"]
    schedule = policy.get("fee_schedule_v1")
    if (
        type(schedule) is not dict
        or policy.get("schema") != "simulated-fee-policy.v2"
        or policy.get("policy_id") != row.fee_policy_id
        or policy.get("policy_version") != row.fee_policy_version
        or policy.get("content_hash") != row.fee_policy_hash
        or schedule.get("config_id") != row.fee_config_id
    ):
        raise _fail(row.pk, "sealed FeeV2 identity differs from stored columns")
    fee_content = dict(policy)
    fee_content.pop("content_hash", None)
    try:
        if _domain_payload_digest(fee_content) != row.fee_policy_hash:
            raise _fail(row.pk, "sealed FeeV2 digest does not match its payload")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise _fail(row.pk, "sealed FeeV2 payload is not canonical JSON") from error


def _validate_resource_constraints(row: Any, values: dict[str, Decimal | None]) -> None:
    """Check the pre-existing resource and lifecycle equations exactly."""

    quantity = values["quantity"]
    limit_price = values["limit_price"]
    notional = values["notional"]
    fee_estimate = values["fee_estimate"]
    fee_budget = values["fee_budget"]
    cash_reserved = values["cash_reserved"]
    shares_reserved = values["shares_reserved"]
    filled = values["filled_quantity"]
    cash_consumed = values["cash_consumed"]
    shares_consumed = values["shares_consumed"]
    cash_released = values["cash_released"]
    shares_released = values["shares_released"]
    required = (
        quantity,
        limit_price,
        notional,
        fee_estimate,
        cash_reserved,
        shares_reserved,
        filled,
        cash_consumed,
        shares_consumed,
        cash_released,
        shares_released,
    )
    if any(value is None for value in required):
        raise _fail(row.pk, "required resource amount is NULL")
    assert quantity is not None and limit_price is not None and notional is not None
    assert fee_estimate is not None and cash_reserved is not None and shares_reserved is not None
    assert filled is not None and cash_consumed is not None and shares_consumed is not None
    assert cash_released is not None and shares_released is not None
    if any(value < 0 for value in required if value is not None):
        raise _fail(row.pk, "resource amount is negative")
    if quantity <= 0 or limit_price <= 0 or notional <= 0:
        raise _fail(row.pk, "required order amount is not positive")
    if (
        filled > quantity
        or cash_consumed > cash_reserved - cash_released
        or shares_consumed > shares_reserved - shares_released
    ):
        raise _fail(row.pk, "stored resource counters do not conserve their reservation")
    if row.side == "buy":
        if (
            fee_budget is None
            or fee_budget < fee_estimate
            or cash_reserved != notional + fee_budget
            or shares_reserved != 0
            or shares_consumed != 0
            or shares_released != 0
        ):
            raise _fail(row.pk, "BUY resource counters violate their reservation contract")
    elif row.side == "sell":
        if fee_budget is not None or shares_reserved != quantity or shares_consumed != filled:
            raise _fail(row.pk, "SELL resource counters violate their reservation contract")
    else:
        raise _fail(row.pk, "reservation side is unsupported")

    if row.status == "active":
        if (
            row.cancelled_at is not None
            or filled >= quantity
            or cash_released != 0
            or shares_released != 0
            or (row.side == "buy" and cash_consumed >= cash_reserved)
            or (row.side == "sell" and shares_consumed >= shares_reserved)
        ):
            raise _fail(row.pk, "active reservation state is inconsistent")
    elif row.status == "completed":
        if (
            row.cancelled_at is not None
            or filled != quantity
            or cash_consumed != cash_reserved - cash_released
            or shares_consumed != shares_reserved - shares_released
        ):
            raise _fail(row.pk, "completed reservation state is inconsistent")
    elif row.status == "cancelled":
        if (
            row.cancelled_at is None
            or row.cancelled_at < row.reserved_at
            or filled >= quantity
            or cash_consumed != cash_reserved - cash_released
            or shares_consumed != shares_reserved - shares_released
        ):
            raise _fail(row.pk, "cancelled reservation state is inconsistent")
    else:
        raise _fail(row.pk, "reservation status is unsupported")


def validate_sqlite_reservation_storage(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Refuse unprovable legacy SQLite rows before changing any constraints."""

    connection = schema_editor.connection
    if connection.vendor != "sqlite":
        return
    reservation_model = apps.get_model(
        "simulated_trading",
        "SimulatedOrderReservationModel",
    )
    alias = connection.alias
    money_nullable = {"fee_budget", "source_book_cash"}
    share_nullable = {"source_sellable_quantity"}
    for row in reservation_model._base_manager.using(alias).iterator(chunk_size=256):
        _validate_plan_binding(row)
        values: dict[str, Decimal | None] = {}
        for field_name in _MONEY_FIELDS:
            value = _decimal_field(row, field_name, nullable=field_name in money_nullable)
            if not _supports_sqlite_decimal(value, "money"):
                raise _fail(row.pk, f"{field_name} is outside the SQLite money envelope")
            values[field_name] = value
        for field_name in _QUANTITY_FIELDS:
            value = _decimal_field(row, field_name, nullable=field_name in share_nullable)
            if not _supports_sqlite_decimal(value, "quantity"):
                raise _fail(row.pk, f"{field_name} is outside the SQLite quantity envelope")
            values[field_name] = value
        price = _decimal_field(row, "limit_price", nullable=False)
        if not _supports_sqlite_decimal(price, "price"):
            raise _fail(row.pk, "limit_price is outside the SQLite price envelope")
        values["limit_price"] = price
        _validate_resource_constraints(row, values)


class Migration(migrations.Migration):
    """Use exact scaled-unit checks on SQLite without narrowing PostgreSQL."""

    atomic = True

    dependencies = [("simulated_trading", "0036_simulated_order_fill_receipt")]

    operations = [
        migrations.RunPython(
            validate_sqlite_reservation_storage,
            migrations.RunPython.noop,
        ),
        migrations.RemoveConstraint(
            model_name="simulatedorderreservationmodel",
            name="simord_amounts_conserved_ck",
        ),
        migrations.RemoveConstraint(
            model_name="simulatedorderreservationmodel",
            name="simord_side_resources_ck",
        ),
        migrations.RemoveConstraint(
            model_name="simulatedorderreservationmodel",
            name="simord_state_conservation_ck",
        ),
        migrations.AddConstraint(
            model_name="simulatedorderreservationmodel",
            constraint=models.CheckConstraint(
                condition=OrderReservationPrecisionCheck("amounts_conserved"),
                name="simord_amounts_conserved_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedorderreservationmodel",
            constraint=models.CheckConstraint(
                condition=OrderReservationPrecisionCheck("side_resources"),
                name="simord_side_resources_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedorderreservationmodel",
            constraint=models.CheckConstraint(
                condition=OrderReservationPrecisionCheck("state_conservation"),
                name="simord_state_conservation_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedorderreservationmodel",
            constraint=models.CheckConstraint(
                condition=OrderReservationPrecisionCheck("sqlite_envelope"),
                name="simord_sqlite_decimal_envelope_ck",
            ),
        ),
    ]
