"""Broker-owned immutable seal for one approved live-order snapshot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from .entities import LiveOrderSide, LiveOrderType, OrderApprovalSnapshot
from .rules import build_approval_digest

BROKER_ORDER_APPROVAL_ARTIFACT_OWNER = "broker_execution"
BROKER_ORDER_APPROVAL_ARTIFACT_TYPE = "live_order_approval_snapshot"
BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA = "broker-live-order-approval-artifact.v1"


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


def _require_decimal(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    if (positive and value <= 0) or (not positive and value < 0):
        raise ValueError(f"{field_name} has an invalid sign")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _snapshot_expiry(snapshot: OrderApprovalSnapshot) -> datetime:
    text = snapshot.expires_at
    if type(text) is not str or not text or text.strip() != text:
        raise ValueError("approval snapshot expires_at must be exact ISO-8601 text")
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("approval snapshot expires_at is invalid") from error
    return _require_aware(value, "approval snapshot expires_at")


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be an exact tuple")
    result = value
    for item in result:
        _require_token(item, field_name)
    if result != tuple(sorted(set(result))):
        raise ValueError(f"{field_name} must be ordered and unique")
    return result


def _validate_snapshot(snapshot: OrderApprovalSnapshot) -> None:
    if type(snapshot) is not OrderApprovalSnapshot:
        raise TypeError("approval_snapshot must be an exact OrderApprovalSnapshot")
    if type(snapshot.account_id) is not int or snapshot.account_id <= 0:
        raise ValueError("approval snapshot account_id must be a positive integer")
    _require_token(snapshot.agent_id, "approval snapshot agent_id")
    _require_token(snapshot.asset_code, "approval snapshot asset_code", maximum=32)
    _require_token(snapshot.market, "approval snapshot market", maximum=16)
    if type(snapshot.side) is not LiveOrderSide:
        raise TypeError("approval snapshot side must be an exact LiveOrderSide")
    if type(snapshot.order_type) is not LiveOrderType:
        raise TypeError("approval snapshot order_type must be an exact LiveOrderType")
    _require_decimal(snapshot.quantity, "approval snapshot quantity", positive=True)
    if snapshot.order_type is LiveOrderType.LIMIT:
        _require_decimal(snapshot.limit_price, "approval snapshot limit_price", positive=True)
    elif snapshot.limit_price is not None:
        _require_decimal(snapshot.limit_price, "approval snapshot limit_price", positive=True)
    _require_decimal(snapshot.estimated_amount, "approval snapshot estimated_amount")
    if snapshot.limit_price is None or (
        snapshot.quantity * snapshot.limit_price != snapshot.estimated_amount
    ):
        raise ValueError("approval snapshot estimated_amount must equal quantity * limit_price")
    _snapshot_expiry(snapshot)
    _require_token(snapshot.risk_policy_version, "approval snapshot risk_policy_version")
    _require_token(snapshot.approval_mode, "approval snapshot approval_mode")
    _string_tuple(snapshot.source_recommendation_ids, "source_recommendation_ids")
    if not snapshot.source_recommendation_ids:
        raise ValueError("source_recommendation_ids must not be empty")
    _string_tuple(snapshot.source_signal_ids, "source_signal_ids")
    try:
        risk_snapshot = json.loads(snapshot.risk_snapshot_json)
    except (TypeError, ValueError) as error:
        raise ValueError("approval snapshot risk_snapshot_json is invalid") from error
    canonical_risk = json.dumps(
        risk_snapshot,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if type(risk_snapshot) is not dict or canonical_risk != snapshot.risk_snapshot_json:
        raise ValueError("approval snapshot risk_snapshot_json must be a canonical object")


def _snapshot_payload(snapshot: OrderApprovalSnapshot) -> dict[str, object]:
    return {
        "account_id": snapshot.account_id,
        "agent_id": snapshot.agent_id,
        "asset_code": snapshot.asset_code,
        "market": snapshot.market,
        "side": snapshot.side.value,
        "order_type": snapshot.order_type.value,
        "quantity": str(snapshot.quantity),
        "limit_price": str(snapshot.limit_price) if snapshot.limit_price is not None else None,
        "estimated_amount": str(snapshot.estimated_amount),
        "expires_at": snapshot.expires_at,
        "risk_policy_version": snapshot.risk_policy_version,
        "risk_snapshot_json": snapshot.risk_snapshot_json,
        "approval_mode": snapshot.approval_mode,
        "source_recommendation_ids": list(snapshot.source_recommendation_ids),
        "source_signal_ids": list(snapshot.source_signal_ids),
    }


@dataclass(frozen=True, slots=True)
class BrokerOrderApprovalActor:
    """Server-authenticated actor sealed by the Broker artifact."""

    actor_id: str
    user_id: int
    role: str

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        _require_token(self.role, "role")

    def to_payload(self) -> dict[str, object]:
        """Return the immutable authenticated actor identity."""

        return {"actor_id": self.actor_id, "user_id": self.user_id, "role": self.role}


@dataclass(frozen=True, slots=True)
class BrokerOrderApprovalArtifact:
    """Immutable owner seal; it deliberately grants no execution capability."""

    artifact_id: str
    artifact_version: str
    client_order_id: str
    account_id: int
    order_version: int
    approval_snapshot: OrderApprovalSnapshot
    approval_digest: str
    approved_by: BrokerOrderApprovalActor
    approved_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = BROKER_ORDER_APPROVAL_ARTIFACT_OWNER
    artifact_type: str = BROKER_ORDER_APPROVAL_ARTIFACT_TYPE
    schema: str = BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA

    def __post_init__(self) -> None:
        try:
            canonical_order_id = str(UUID(self.client_order_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("client_order_id must be a canonical UUID") from error
        if canonical_order_id != self.client_order_id:
            raise ValueError("client_order_id must be a canonical UUID")
        if self.artifact_id != self.client_order_id:
            raise ValueError("artifact_id must equal the canonical client_order_id")
        if type(self.order_version) is not int or self.order_version <= 0:
            raise ValueError("order_version must be a positive integer")
        expected_version = f"{BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA}.{self.order_version}"
        if self.artifact_version != expected_version:
            raise ValueError("artifact_version must bind the exact order_version")
        if self.owner != BROKER_ORDER_APPROVAL_ARTIFACT_OWNER:
            raise ValueError("artifact owner is fixed")
        if self.artifact_type != BROKER_ORDER_APPROVAL_ARTIFACT_TYPE:
            raise ValueError("artifact_type is fixed")
        if self.schema != BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA:
            raise ValueError("artifact schema is fixed")
        _validate_snapshot(self.approval_snapshot)
        if self.account_id != self.approval_snapshot.account_id:
            raise ValueError("artifact account_id does not match approval snapshot")
        expected_digest = build_approval_digest(self.approval_snapshot)
        _require_hash(self.approval_digest, "approval_digest")
        if self.approval_digest != expected_digest:
            raise ValueError("approval_digest does not match the exact snapshot")
        if type(self.approved_by) is not BrokerOrderApprovalActor:
            raise TypeError("approved_by must be an exact BrokerOrderApprovalActor")
        BrokerOrderApprovalActor.__post_init__(self.approved_by)
        _require_aware(self.approved_at, "approved_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until != _snapshot_expiry(self.approval_snapshot):
            raise ValueError("valid_until must exactly equal approval snapshot expires_at")
        if self.approved_at >= self.valid_until:
            raise ValueError("approval artifact validity window is invalid")
        expected_identity = _hash_payload(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity:
                raise ValueError("artifact identity_hash is invalid")
        expected_content = _hash_payload(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content:
                raise ValueError("artifact content_hash is invalid")

    @property
    def activation_available(self) -> bool:
        """Remain false until exact cross-owner receipts are integrated."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this artifact is only an owner seal."""

        return True

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "schema": self.schema,
            "client_order_id": self.client_order_id,
            "account_id": self.account_id,
            "order_version": self.order_version,
            "approval_snapshot": _snapshot_payload(self.approval_snapshot),
            "approval_digest": self.approval_digest,
            "approved_by": self.approved_by.to_payload(),
            "approved_at": _utc_text(self.approved_at),
            "valid_until": _utc_text(self.valid_until),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the sealed artifact without implying activation."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


__all__ = [
    "BROKER_ORDER_APPROVAL_ARTIFACT_OWNER",
    "BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA",
    "BROKER_ORDER_APPROVAL_ARTIFACT_TYPE",
    "BrokerOrderApprovalActor",
    "BrokerOrderApprovalArtifact",
]
