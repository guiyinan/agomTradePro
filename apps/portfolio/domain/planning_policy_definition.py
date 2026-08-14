"""Immutable Portfolio planning-policy definition contract without activation semantics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

PLANNING_POLICY_DEFINITION_OWNER = "portfolio"
PLANNING_POLICY_DEFINITION_TYPE = "planning_policy_definition"
PLANNING_POLICY_DEFINITION_SCHEMA = "portfolio-planning-policy-definition.v1"
PLANNING_POLICY_DEFINITION_PERMISSION = "definition_only"


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _require_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_decimal(
    value: object,
    field_name: str,
    *,
    strictly_positive: bool,
    maximum: Decimal | None = None,
) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be an exact Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if value.is_zero() and value.is_signed():
        raise ValueError(f"{field_name} cannot be negative zero")
    if (strictly_positive and value <= 0) or (not strictly_positive and value < 0):
        qualifier = "positive" if strictly_positive else "non-negative"
        raise ValueError(f"{field_name} must be {qualifier}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} exceeds its maximum")
    return value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PlanningPolicyDefinition:
    """Content-addressed planning inputs that grant no active or execution state."""

    policy_id: str
    policy_version: str
    buy_lot_size: int
    fee_rate: Decimal
    slippage_rate: Decimal
    min_rebalance_value: Decimal
    max_asset_weight: Decimal
    max_volume_participation: Decimal
    recorded_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = PLANNING_POLICY_DEFINITION_OWNER
    artifact_type: str = PLANNING_POLICY_DEFINITION_TYPE
    schema: str = PLANNING_POLICY_DEFINITION_SCHEMA
    permission: str = PLANNING_POLICY_DEFINITION_PERMISSION

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "policy_id")
        _require_token(self.policy_version, "policy_version")
        if type(self.buy_lot_size) is not int or self.buy_lot_size <= 0:
            raise ValueError("buy_lot_size must be an exact positive integer")
        _require_decimal(self.fee_rate, "fee_rate", strictly_positive=False)
        _require_decimal(self.slippage_rate, "slippage_rate", strictly_positive=False)
        _require_decimal(
            self.min_rebalance_value,
            "min_rebalance_value",
            strictly_positive=False,
        )
        _require_decimal(
            self.max_asset_weight,
            "max_asset_weight",
            strictly_positive=True,
            maximum=Decimal("1"),
        )
        _require_decimal(
            self.max_volume_participation,
            "max_volume_participation",
            strictly_positive=True,
            maximum=Decimal("1"),
        )
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("planning policy definition validity window is invalid")
        if self.owner != PLANNING_POLICY_DEFINITION_OWNER:
            raise ValueError("planning policy definition owner is fixed")
        if self.artifact_type != PLANNING_POLICY_DEFINITION_TYPE:
            raise ValueError("planning policy definition artifact_type is fixed")
        if self.schema != PLANNING_POLICY_DEFINITION_SCHEMA:
            raise ValueError("planning policy definition schema is fixed")
        if self.permission != PLANNING_POLICY_DEFINITION_PERMISSION:
            raise ValueError("planning policy definition permission is fixed")
        expected_identity = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity:
                raise ValueError("planning policy definition identity_hash is invalid")
        expected_content = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content:
                raise ValueError("planning policy definition content_hash is invalid")

    @property
    def must_not_execute(self) -> bool:
        """Remain true because planning inputs never grant execution permission."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable definition is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "buy_lot_size": self.buy_lot_size,
            "fee_rate": _decimal_text(self.fee_rate),
            "slippage_rate": _decimal_text(self.slippage_rate),
            "min_rebalance_value": _decimal_text(self.min_rebalance_value),
            "max_asset_weight": _decimal_text(self.max_asset_weight),
            "max_volume_participation": _decimal_text(self.max_volume_participation),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "permission": self.permission,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the canonical definition with explicit non-activation markers."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "must_not_execute": True,
        }


__all__ = [
    "PLANNING_POLICY_DEFINITION_OWNER",
    "PLANNING_POLICY_DEFINITION_PERMISSION",
    "PLANNING_POLICY_DEFINITION_SCHEMA",
    "PLANNING_POLICY_DEFINITION_TYPE",
    "PlanningPolicyDefinition",
]
