"""Broker-owned inactive seal binding one exact Portfolio plan row to one order."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

BROKER_PLAN_ORDER_BINDING_OWNER = "broker_execution"
BROKER_PLAN_ORDER_BINDING_TYPE = "plan_order_binding"
BROKER_PLAN_ORDER_BINDING_SCHEMA = "broker-plan-order-binding.v1"
BROKER_PLAN_ORDER_BINDING_PERMISSION = "inactive"
BROKER_PLAN_ORDER_BINDING_BLOCKERS = (
    "broker_plan_order_binding_inactive",
    "portfolio_broker_account_binding_unverified",
)

PORTFOLIO_PLAN_SOURCE_OWNER = "portfolio"
PORTFOLIO_PLAN_SOURCE_ARTIFACT_TYPE = "transition_plan_definition"
PORTFOLIO_RECEIPT_SOURCE_OWNER = "portfolio"
PORTFOLIO_RECEIPT_SOURCE_CAPABILITY = "transition_plan_inactive_approval"
BROKER_ORDER_ARTIFACT_SOURCE_OWNER = "broker_execution"
BROKER_ORDER_ARTIFACT_SOURCE_TYPE = "live_order_approval_snapshot"

_BROKER_ORDER_ARTIFACT_SCHEMA = "broker-live-order-approval-artifact.v1"
_ORDER_FIELDS = frozenset(
    {
        "asset_code",
        "side",
        "quantity",
        "reference_price",
        "estimated_fee",
        "status",
        "remaining_quantity",
        "constraints",
    }
)
_CONSTRAINT_FIELDS = frozenset(
    {
        "rule_code",
        "asset_code",
        "allowed",
        "original_quantity",
        "allowed_quantity",
        "reason",
    }
)


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


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"plan_order_payload_json contains invalid constant {value}")


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("plan_order_payload_json contains duplicate keys")
        result[key] = value
    return result


def _canonical_decimal_text(value: object, field_name: str, *, positive: bool) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{field_name} must be canonical finite Decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field_name} must be canonical finite Decimal text") from error
    if not parsed.is_finite() or str(parsed) != value:
        raise ValueError(f"{field_name} must be canonical finite Decimal text")
    if (positive and parsed <= 0) or (not positive and parsed < 0):
        raise ValueError(f"{field_name} has an invalid sign")
    return value


def _require_integer(value: object, field_name: str, *, positive: bool) -> int:
    if type(value) is not int or (value <= 0 if positive else value < 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{field_name} must be a {qualifier} integer")
    return value


def _validate_constraint_payload(value: object) -> None:
    if type(value) is not dict or set(value) != _CONSTRAINT_FIELDS:
        raise ValueError("plan order constraint must have the canonical-v1 shape")
    _require_token(value["rule_code"], "constraint.rule_code")
    _require_token(value["asset_code"], "constraint.asset_code", maximum=32)
    if type(value["allowed"]) is not bool:
        raise ValueError("constraint.allowed must be a bool")
    original = _require_integer(
        value["original_quantity"], "constraint.original_quantity", positive=False
    )
    allowed = _require_integer(
        value["allowed_quantity"], "constraint.allowed_quantity", positive=False
    )
    if allowed > original:
        raise ValueError("constraint allowed_quantity exceeds original_quantity")
    if type(value["reason"]) is not str:
        raise ValueError("constraint.reason must be a string")


def _decode_canonical_plan_order_payload_v1(payload_json: str) -> dict[str, object]:
    if type(payload_json) is not str or not payload_json:
        raise ValueError("plan_order_payload_json must be canonical-v1 JSON object text")
    try:
        decoded = json.loads(
            payload_json,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("plan_order_payload_json must be canonical-v1 JSON object text") from error
    if type(decoded) is not dict or set(decoded) != _ORDER_FIELDS:
        raise ValueError("plan_order_payload_json must have the canonical-v1 row shape")
    canonical = json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    if canonical != payload_json:
        raise ValueError("plan_order_payload_json must use canonical-v1 JSON bytes")
    _require_token(decoded["asset_code"], "order.asset_code", maximum=32)
    if decoded["side"] not in {"buy", "sell"}:
        raise ValueError("order.side is invalid")
    _require_integer(decoded["quantity"], "order.quantity", positive=False)
    _canonical_decimal_text(decoded["reference_price"], "order.reference_price", positive=True)
    _canonical_decimal_text(decoded["estimated_fee"], "order.estimated_fee", positive=False)
    if decoded["status"] not in {"draft", "partial", "blocked"}:
        raise ValueError("order.status is invalid")
    _require_integer(decoded["remaining_quantity"], "order.remaining_quantity", positive=False)
    constraints = decoded["constraints"]
    if type(constraints) is not list:
        raise TypeError("order.constraints must be an exact list")
    for constraint in constraints:
        _validate_constraint_payload(constraint)
    return decoded


def canonical_plan_order_payload_hash_v1(payload_json: str) -> str:
    """Hash one canonical-v1 order-row JSON value without semantic migration."""

    _decode_canonical_plan_order_payload_v1(payload_json)
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BrokerPlanOrderBinding:
    """Immutable exact-source seal that deliberately grants no execution authority."""

    binding_id: str
    binding_version: str
    portfolio_plan_id: str
    portfolio_plan_version: int
    portfolio_plan_content_hash: str
    portfolio_account_id: str
    portfolio_receipt_id: str
    portfolio_receipt_version: str
    portfolio_receipt_content_hash: str
    portfolio_subject_id: str
    portfolio_subject_version: str
    portfolio_subject_content_hash: str
    plan_order_ordinal: int
    plan_order_payload_json: str
    plan_order_content_hash: str
    broker_account_id: int
    order_artifact_id: str
    order_artifact_version: str
    order_artifact_identity_hash: str
    order_artifact_content_hash: str
    order_approval_digest: str
    order_version: int
    portfolio_plan_valid_until: datetime
    portfolio_receipt_valid_until: datetime
    order_artifact_valid_until: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_binding_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = BROKER_PLAN_ORDER_BINDING_OWNER
    artifact_type: str = BROKER_PLAN_ORDER_BINDING_TYPE
    schema: str = BROKER_PLAN_ORDER_BINDING_SCHEMA
    permission: str = BROKER_PLAN_ORDER_BINDING_PERMISSION
    blocker_codes: tuple[str, ...] = BROKER_PLAN_ORDER_BINDING_BLOCKERS
    portfolio_plan_owner: str = PORTFOLIO_PLAN_SOURCE_OWNER
    portfolio_plan_artifact_type: str = PORTFOLIO_PLAN_SOURCE_ARTIFACT_TYPE
    portfolio_receipt_owner: str = PORTFOLIO_RECEIPT_SOURCE_OWNER
    portfolio_receipt_capability: str = PORTFOLIO_RECEIPT_SOURCE_CAPABILITY
    order_artifact_owner: str = BROKER_ORDER_ARTIFACT_SOURCE_OWNER
    order_artifact_type: str = BROKER_ORDER_ARTIFACT_SOURCE_TYPE

    def __post_init__(self) -> None:
        if self.owner != BROKER_PLAN_ORDER_BINDING_OWNER:
            raise ValueError("binding owner is fixed")
        if self.artifact_type != BROKER_PLAN_ORDER_BINDING_TYPE:
            raise ValueError("binding artifact_type is fixed")
        if self.schema != BROKER_PLAN_ORDER_BINDING_SCHEMA:
            raise ValueError("binding schema is fixed")
        if self.binding_version != BROKER_PLAN_ORDER_BINDING_SCHEMA:
            raise ValueError("binding_version is fixed to the canonical schema")
        if self.permission != BROKER_PLAN_ORDER_BINDING_PERMISSION:
            raise ValueError("binding permission is fixed inactive")
        if self.blocker_codes != BROKER_PLAN_ORDER_BINDING_BLOCKERS:
            raise ValueError("binding blocker_codes are fixed")
        fixed_source_authority = (
            (self.portfolio_plan_owner, PORTFOLIO_PLAN_SOURCE_OWNER),
            (
                self.portfolio_plan_artifact_type,
                PORTFOLIO_PLAN_SOURCE_ARTIFACT_TYPE,
            ),
            (self.portfolio_receipt_owner, PORTFOLIO_RECEIPT_SOURCE_OWNER),
            (
                self.portfolio_receipt_capability,
                PORTFOLIO_RECEIPT_SOURCE_CAPABILITY,
            ),
            (self.order_artifact_owner, BROKER_ORDER_ARTIFACT_SOURCE_OWNER),
            (self.order_artifact_type, BROKER_ORDER_ARTIFACT_SOURCE_TYPE),
        )
        if any(actual != expected for actual, expected in fixed_source_authority):
            raise ValueError("source owner, artifact type, and capability are fixed")
        for field_name in (
            "binding_id",
            "portfolio_plan_id",
            "portfolio_account_id",
            "portfolio_receipt_id",
            "portfolio_receipt_version",
            "portfolio_subject_id",
            "portfolio_subject_version",
            "order_artifact_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_integer(self.portfolio_plan_version, "portfolio_plan_version", positive=True)
        _require_integer(self.plan_order_ordinal, "plan_order_ordinal", positive=False)
        _require_integer(self.broker_account_id, "broker_account_id", positive=True)
        _require_integer(self.order_version, "order_version", positive=True)
        for field_name in (
            "portfolio_plan_content_hash",
            "portfolio_receipt_content_hash",
            "portfolio_subject_content_hash",
            "plan_order_content_hash",
            "order_artifact_identity_hash",
            "order_artifact_content_hash",
            "order_approval_digest",
        ):
            _require_hash(getattr(self, field_name), field_name)
        expected_row_hash = canonical_plan_order_payload_hash_v1(self.plan_order_payload_json)
        if self.plan_order_content_hash != expected_row_hash:
            raise ValueError("plan_order_content_hash does not match canonical-v1 row bytes")
        try:
            canonical_order_id = str(UUID(self.order_artifact_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("order_artifact_id must be a canonical UUID") from error
        if canonical_order_id != self.order_artifact_id:
            raise ValueError("order_artifact_id must be a canonical UUID")
        expected_artifact_version = f"{_BROKER_ORDER_ARTIFACT_SCHEMA}.{self.order_version}"
        if self.order_artifact_version != expected_artifact_version:
            raise ValueError("order_artifact_version must bind the exact order_version")
        _require_aware(self.portfolio_plan_valid_until, "portfolio_plan_valid_until")
        _require_aware(self.portfolio_receipt_valid_until, "portfolio_receipt_valid_until")
        _require_aware(self.order_artifact_valid_until, "order_artifact_valid_until")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        source_valid_until = min(
            self.portfolio_plan_valid_until,
            self.portfolio_receipt_valid_until,
            self.order_artifact_valid_until,
        )
        if self.valid_until != source_valid_until:
            raise ValueError("valid_until must equal the earliest exact source expiry")
        if self.recorded_at >= source_valid_until:
            raise ValueError("binding must be recorded before every source expires")
        if self.supersedes_binding_hash is not None:
            _require_hash(self.supersedes_binding_hash, "supersedes_binding_hash")
        expected_identity = _hash_payload(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity:
                raise ValueError("binding identity_hash is invalid")
        expected_content = _hash_payload(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content:
                raise ValueError("binding content_hash is invalid")

    @property
    def plan_order_payload(self) -> dict[str, object]:
        """Return a fresh validated canonical-v1 order-row projection."""

        return _decode_canonical_plan_order_payload_v1(self.plan_order_payload_json)

    @property
    def activation_available(self) -> bool:
        """Remain false until every independent owner authorization is integrated."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a plan/order association is not execution authority."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable binding is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "schema": self.schema,
            "portfolio_plan_id": self.portfolio_plan_id,
            "portfolio_plan_version": self.portfolio_plan_version,
            "portfolio_plan_content_hash": self.portfolio_plan_content_hash,
            "portfolio_plan_owner": self.portfolio_plan_owner,
            "portfolio_plan_artifact_type": self.portfolio_plan_artifact_type,
            "portfolio_plan_valid_until": _utc_text(self.portfolio_plan_valid_until),
            "portfolio_account_id": self.portfolio_account_id,
            "portfolio_receipt_id": self.portfolio_receipt_id,
            "portfolio_receipt_version": self.portfolio_receipt_version,
            "portfolio_receipt_content_hash": self.portfolio_receipt_content_hash,
            "portfolio_receipt_owner": self.portfolio_receipt_owner,
            "portfolio_receipt_capability": self.portfolio_receipt_capability,
            "portfolio_receipt_valid_until": _utc_text(self.portfolio_receipt_valid_until),
            "portfolio_subject_id": self.portfolio_subject_id,
            "portfolio_subject_version": self.portfolio_subject_version,
            "portfolio_subject_content_hash": self.portfolio_subject_content_hash,
            "plan_order_ordinal": self.plan_order_ordinal,
            "plan_order_payload": self.plan_order_payload,
            "plan_order_content_hash": self.plan_order_content_hash,
            "broker_account_id": self.broker_account_id,
            "order_artifact_id": self.order_artifact_id,
            "order_artifact_version": self.order_artifact_version,
            "order_artifact_identity_hash": self.order_artifact_identity_hash,
            "order_artifact_content_hash": self.order_artifact_content_hash,
            "order_artifact_owner": self.order_artifact_owner,
            "order_artifact_type": self.order_artifact_type,
            "order_artifact_valid_until": _utc_text(self.order_artifact_valid_until),
            "order_approval_digest": self.order_approval_digest,
            "order_version": self.order_version,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_binding_hash": self.supersedes_binding_hash,
            "permission": self.permission,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the exact sealed projection with explicit inactive flags."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_plan_order_binding_successor(
    previous: BrokerPlanOrderBinding,
    successor: BrokerPlanOrderBinding,
) -> None:
    """Validate an adjacent immutable binding for the same logical plan order."""

    if type(previous) is not BrokerPlanOrderBinding:
        raise TypeError("previous must be an exact BrokerPlanOrderBinding")
    if type(successor) is not BrokerPlanOrderBinding:
        raise TypeError("successor must be an exact BrokerPlanOrderBinding")
    BrokerPlanOrderBinding.__post_init__(previous)
    BrokerPlanOrderBinding.__post_init__(successor)
    if successor.supersedes_binding_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous binding")
    if successor.portfolio_plan_id != previous.portfolio_plan_id:
        raise ValueError("binding successor changed Portfolio plan identity")
    if successor.portfolio_plan_version != previous.portfolio_plan_version:
        raise ValueError("binding successor changed Portfolio plan version")
    if successor.plan_order_ordinal != previous.plan_order_ordinal:
        raise ValueError("binding successor changed plan order ordinal")
    if successor.broker_account_id != previous.broker_account_id:
        raise ValueError("binding successor changed Broker account identity")
    if successor.order_artifact_id != previous.order_artifact_id:
        raise ValueError("binding successor changed Broker order identity")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("binding successor clock must advance")


__all__ = [
    "BROKER_PLAN_ORDER_BINDING_BLOCKERS",
    "BROKER_PLAN_ORDER_BINDING_OWNER",
    "BROKER_PLAN_ORDER_BINDING_PERMISSION",
    "BROKER_PLAN_ORDER_BINDING_SCHEMA",
    "BROKER_PLAN_ORDER_BINDING_TYPE",
    "BROKER_ORDER_ARTIFACT_SOURCE_OWNER",
    "BROKER_ORDER_ARTIFACT_SOURCE_TYPE",
    "PORTFOLIO_PLAN_SOURCE_ARTIFACT_TYPE",
    "PORTFOLIO_PLAN_SOURCE_OWNER",
    "PORTFOLIO_RECEIPT_SOURCE_CAPABILITY",
    "PORTFOLIO_RECEIPT_SOURCE_OWNER",
    "BrokerPlanOrderBinding",
    "canonical_plan_order_payload_hash_v1",
    "validate_plan_order_binding_successor",
]
