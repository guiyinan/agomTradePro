"""Lossless optional Portfolio plan binding codec for existing order snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanOrderExecutionBinding,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.domain.transition_plan_execution import (
    derive_plan_order_idempotency_key,
)

_SCHEMA = "portfolio-transition-plan-order-execution.v1"
_WRAPPER_FIELDS = frozenset({"schema", "revision_recorded_at", "binding", "binding_content_hash"})
_BINDING_FIELDS = frozenset(
    {
        "plan_id",
        "family_id",
        "root_plan_id",
        "plan_version",
        "revision_hash",
        "order_ordinal",
        "plan_order_binding_id",
        "order_content_hash",
        "account_id",
        "owner_user_id",
        "action_attempt_key",
        "asset_code",
        "security_id",
        "asset_type",
        "classification_content_hash",
        "side",
        "approved_quantity",
        "approved_limit_price",
        "quantity_unit",
        "money_unit",
        "plan_expires_at",
        "reference_price_is_executable_limit",
        "estimated_fee_is_actual_fee",
    }
)


def _snapshot_error(message: str) -> ValueError:
    """Return the stable validation error class used by the reservation codec."""

    return ValueError(f"TRANSITION_PLAN_EXECUTION_BINDING_INVALID: {message}")


def _mapping(value: object, expected: frozenset[str], field_name: str) -> dict[str, object]:
    """Require one JSON object with an exact schema field set."""

    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise _snapshot_error(f"{field_name} must be an object")
    result = cast(dict[str, object], value)
    if frozenset(result) != expected:
        raise _snapshot_error(f"{field_name} has missing or unknown fields")
    return result


def _text(value: object, field_name: str) -> str:
    """Narrow a bounded nonempty JSON token without coercion."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(c.isspace() for c in value)
    ):
        raise _snapshot_error(f"{field_name} must be canonical text")
    return value


def _integer(value: object, field_name: str) -> int:
    """Reject JSON booleans where an exact integer is required."""

    if type(value) is not int:
        raise _snapshot_error(f"{field_name} must be an integer")
    return value


def _digest(value: object, field_name: str) -> str:
    """Require an unprefixed lowercase SHA-256 digest."""

    result = _text(value, field_name)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise _snapshot_error(f"{field_name} must be SHA-256")
    return result


def _datetime(value: object, field_name: str) -> datetime:
    """Decode an aware timestamp while preserving its serialized offset."""

    text = _text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise _snapshot_error(f"{field_name} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.isoformat() != text:
        raise _snapshot_error(f"{field_name} must be canonical and timezone-aware")
    return parsed


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    """Decode exact finite Decimal text or preserve an explicit absence."""

    if value is None:
        return None
    text = _text(value, field_name)
    try:
        parsed = Decimal(text)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise _snapshot_error(f"{field_name} is invalid") from error
    if not parsed.is_finite() or str(parsed) != text:
        raise _snapshot_error(f"{field_name} is not canonical Decimal text")
    return parsed


def encode_plan_execution_binding(
    *, binding: TransitionPlanOrderExecutionBinding, revision_recorded_at: datetime
) -> dict[str, object]:
    """Return the exact optional wrapper embedded in an accepted reservation snapshot."""

    if type(binding) is not TransitionPlanOrderExecutionBinding:
        raise _snapshot_error("binding must use Portfolio's exact typed revision binding")
    try:
        binding.__post_init__()
        _datetime(revision_recorded_at.isoformat(), "revision_recorded_at")
        if revision_recorded_at >= binding.plan_expires_at:
            raise ValueError("revision record time must precede plan expiry")
    except (ArithmeticError, TypeError, ValueError) as error:
        raise _snapshot_error("binding timestamps or fields are invalid") from error
    return {
        "schema": _SCHEMA,
        "revision_recorded_at": revision_recorded_at.isoformat(),
        "binding": binding.to_payload(),
        "binding_content_hash": binding.content_hash,
    }


def decode_plan_execution_binding(
    value: object,
) -> tuple[TransitionPlanOrderExecutionBinding, datetime]:
    """Decode the canonical Portfolio binding and preserve its original plan clock."""

    wrapper = _mapping(value, _WRAPPER_FIELDS, "transition plan execution binding")
    if wrapper["schema"] != _SCHEMA:
        raise _snapshot_error("schema is unsupported")
    recorded_at = _datetime(wrapper["revision_recorded_at"], "revision_recorded_at")
    raw = _mapping(wrapper["binding"], _BINDING_FIELDS, "binding")
    if raw["reference_price_is_executable_limit"] is not False:
        raise _snapshot_error("reference price cannot grant an execution limit")
    if raw["estimated_fee_is_actual_fee"] is not False:
        raise _snapshot_error("estimated fee cannot claim a posted fee")
    side_text = _text(raw["side"], "side")
    if side_text not in {"buy", "sell"}:
        raise _snapshot_error("side is invalid")
    try:
        binding = TransitionPlanOrderExecutionBinding(
            plan_id=_text(raw["plan_id"], "plan_id"),
            family_id=_text(raw["family_id"], "family_id"),
            root_plan_id=_text(raw["root_plan_id"], "root_plan_id"),
            plan_version=_integer(raw["plan_version"], "plan_version"),
            revision_hash=_digest(raw["revision_hash"], "revision_hash"),
            order_ordinal=_integer(raw["order_ordinal"], "order_ordinal"),
            plan_order_binding_id=_digest(raw["plan_order_binding_id"], "plan_order_binding_id"),
            order_content_hash=_digest(raw["order_content_hash"], "order_content_hash"),
            account_id=_integer(raw["account_id"], "account_id"),
            owner_user_id=_integer(raw["owner_user_id"], "owner_user_id"),
            action_attempt_key=_text(raw["action_attempt_key"], "action_attempt_key"),
            asset_code=_text(raw["asset_code"], "asset_code"),
            security_id=_text(raw["security_id"], "security_id"),
            asset_type=_text(raw["asset_type"], "asset_type"),
            classification_content_hash=_digest(
                raw["classification_content_hash"], "classification_content_hash"
            ),
            side=cast(Literal["buy", "sell"], side_text),
            approved_quantity=_integer(raw["approved_quantity"], "approved_quantity"),
            approved_limit_price=_optional_decimal(
                raw["approved_limit_price"], "approved_limit_price"
            ),
            quantity_unit=_text(raw["quantity_unit"], "quantity_unit"),
            money_unit=_text(raw["money_unit"], "money_unit"),
            plan_expires_at=_datetime(raw["plan_expires_at"], "plan_expires_at"),
        )
        binding.__post_init__()
    except (ArithmeticError, TypeError, ValueError) as error:
        raise _snapshot_error("typed binding validation failed") from error
    if recorded_at >= binding.plan_expires_at:
        raise _snapshot_error("revision record time must precede plan expiry")
    if _digest(wrapper["binding_content_hash"], "binding_content_hash") != binding.content_hash:
        raise _snapshot_error("canonical binding digest differs from stored digest")
    return binding, recorded_at


def validate_binding_matches_intent(
    *, binding: TransitionPlanOrderExecutionBinding, intent: SimulatedTradeIntent
) -> None:
    """Bind the approved order identity and optional limit to the exact reservation intent."""

    if (
        type(binding) is not TransitionPlanOrderExecutionBinding
        or type(intent) is not SimulatedTradeIntent
    ):
        raise _snapshot_error("binding and intent types are invalid")
    binding.__post_init__()
    intent.__post_init__()
    if (
        (
            binding.account_id,
            binding.owner_user_id,
            binding.asset_code,
            binding.security_id,
            binding.side,
        )
        != (
            intent.account_id,
            intent.user_id,
            intent.asset_code,
            intent.security_id,
            intent.side.value,
        )
        or binding.asset_type != intent.asset_type
        or intent.idempotency_key != derive_plan_order_idempotency_key(binding.content_hash)
        or intent.quantity > Decimal(binding.approved_quantity)
        or (
            binding.approved_limit_price is not None
            and intent.price != binding.approved_limit_price
        )
    ):
        raise _snapshot_error("binding does not match the exact reservation intent")
