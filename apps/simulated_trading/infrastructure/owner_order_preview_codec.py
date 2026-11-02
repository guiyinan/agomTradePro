"""Authenticate bounded order previews and narrow their retained JSON evidence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from django.core import signing

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.owner_order_submission import OwnerOrderPreviewBinding
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
)

_SALT = "simulated-trading.owner-order-preview"
_FIELDS = frozenset(
    {
        "intent",
        "fee_budget",
        "fee_policy_hash",
        "settlement_bundle_hash",
        "identity_occurrence",
        "identity_binding_hash",
        "market_source_hash",
        "expires_at",
        "retained_source",
    }
)
_PURPOSE_FIELD = "market_purpose"
_FIELDS_WITH_PURPOSE = _FIELDS | {_PURPOSE_FIELD}
_LOCAL_MARKET_PURPOSE = "local_simulation_only"
_CLOSE_MARKET_PURPOSE = "close_snapshot_simulation"
_SUPPORTED_MARKET_PURPOSES = frozenset({_LOCAL_MARKET_PURPOSE, _CLOSE_MARKET_PURPOSE})
_INTENT_FIELDS = frozenset(
    {
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
)


def _object(value: object, fields: frozenset[str] | None = None) -> dict[str, object]:
    """Require a concrete JSON object with exact string keys."""
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError("preview must contain a JSON object")
    result = cast(dict[str, object], value)
    if fields is not None and frozenset(result) != fields:
        raise ValueError("preview fields are incomplete or unknown")
    return result


def _text(value: object) -> str:
    """Require bounded text without coercing arbitrary JSON values."""
    if type(value) is not str or len(value) > 512:
        raise ValueError("preview text is invalid")
    return value


def _integer(value: object) -> int:
    """Reject JSON booleans where an exact integer is required."""
    if type(value) is not int:
        raise ValueError("preview integer is invalid")
    return value


def _decimal(value: object) -> Decimal:
    """Read exact finite decimal text; the domain checks storage limits next."""
    text = _text(value)
    parsed = Decimal(text)
    if not parsed.is_finite() or format(parsed, "f") != text:
        raise ValueError("preview decimal is not finite canonical text")
    return parsed


def _digest(value: object) -> str:
    """Require an unprefixed lowercase SHA-256 digest."""
    result = _text(value)
    if len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
        raise ValueError("preview digest is invalid")
    return result


def _datetime(value: object) -> datetime:
    """Read a canonical aware deadline without using token age for recovery."""
    text = _text(value)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.isoformat() != text:
        raise ValueError("preview deadline must be canonical aware timestamp text")
    return parsed


class SignedOwnerOrderPreviewCodec:
    """Use Django's configured signing key without expiring accepted-order recovery."""

    def seal(self, binding: OwnerOrderPreviewBinding) -> str:
        """Sign the exact reviewed order; market/plan windows govern new commits."""
        binding.__post_init__()
        intent = binding.intent
        intent.__post_init__()
        payload: dict[str, object] = {
            "intent": {
                "account_id": intent.account_id,
                "user_id": intent.user_id,
                "idempotency_key": intent.idempotency_key,
                "side": intent.side.value,
                "security_id": intent.security_id,
                "asset_code": intent.asset_code,
                "asset_name": intent.asset_name,
                "asset_type": intent.asset_type,
                "market": intent.market,
                "board": intent.board,
                "quantity": format(intent.quantity, "f"),
                "price": format(intent.price, "f"),
                "reason": intent.reason,
                "signal_id": intent.signal_id,
            },
            "fee_budget": (
                format(binding.fee_budget, "f") if binding.fee_budget is not None else None
            ),
            "fee_policy_hash": binding.fee_policy_hash,
            "settlement_bundle_hash": binding.settlement_bundle_hash,
            "identity_occurrence": binding.identity_occurrence,
            "identity_binding_hash": binding.identity_binding_hash,
            "market_source_hash": binding.market_source_hash,
            "expires_at": _datetime(binding.expires_at.isoformat()).isoformat(),
            "retained_source": binding.retained_source,
        }
        # Keep the byte shape of existing local-only tokens stable.
        if binding.market_purpose != _LOCAL_MARKET_PURPOSE:
            payload[_PURPOSE_FIELD] = binding.market_purpose
        return signing.dumps(payload, salt=_SALT, compress=True)

    def open(self, token: str) -> OwnerOrderPreviewBinding:
        """Authenticate before parsing; a stale uncommitted source still fails its guard."""
        try:
            if type(token) is not str or not token or len(token) > 131072:
                raise ValueError("preview token is missing or too large")
            raw_payload = _object(signing.loads(token, salt=_SALT))
            payload_fields = frozenset(raw_payload)
            if payload_fields == _FIELDS:
                market_purpose = _LOCAL_MARKET_PURPOSE
            elif payload_fields == _FIELDS_WITH_PURPOSE:
                market_purpose = _text(raw_payload[_PURPOSE_FIELD])
                if market_purpose != _CLOSE_MARKET_PURPOSE:
                    raise ValueError("preview market purpose is unsupported")
            else:
                raise ValueError("preview fields are incomplete or unknown")
            payload = raw_payload
            values = _object(payload["intent"], _INTENT_FIELDS)
            intent = SimulatedTradeIntent(
                account_id=_integer(values["account_id"]),
                user_id=_integer(values["user_id"]),
                idempotency_key=_text(values["idempotency_key"]),
                side=SimulatedTradeSide(_text(values["side"])),
                security_id=_text(values["security_id"]),
                asset_code=_text(values["asset_code"]),
                asset_name=_text(values["asset_name"]),
                asset_type=_text(values["asset_type"]),
                market=_text(values["market"]),
                board=_text(values["board"]),
                quantity=_decimal(values["quantity"]),
                price=_decimal(values["price"]),
                reason=_text(values["reason"]),
                signal_id=(
                    _integer(values["signal_id"]) if values["signal_id"] is not None else None
                ),
            )
            occurrence = _text(payload["identity_occurrence"])
            if str(UUID(occurrence)) != occurrence:
                raise ValueError("preview occurrence is not canonical")
            return OwnerOrderPreviewBinding(
                intent=intent,
                fee_budget=(
                    _decimal(payload["fee_budget"]) if payload["fee_budget"] is not None else None
                ),
                fee_policy_hash=_digest(payload["fee_policy_hash"]),
                settlement_bundle_hash=_digest(payload["settlement_bundle_hash"]),
                identity_occurrence=occurrence,
                identity_binding_hash=_digest(payload["identity_binding_hash"]),
                market_source_hash=_digest(payload["market_source_hash"]),
                expires_at=_datetime(payload["expires_at"]),
                retained_source=_object(payload["retained_source"]),
                market_purpose=market_purpose,
            )
        except (signing.BadSignature, ArithmeticError, TypeError, ValueError, KeyError) as error:
            raise SimulatedTradeExecutionInputError("订单预览已损坏，请重新预览") from error
