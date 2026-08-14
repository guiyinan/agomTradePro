"""Pure fail-closed projection for legacy broker approval evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from apps.research.application.evidence_summary import EvidenceSummaryDTO
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    MethodKind,
    build_legacy_unverified_envelope,
)

_AMOUNT_QUANTUM = Decimal("0.01")
_ARTIFACT_VERSION = "approval-snapshot-v1"


@dataclass(frozen=True, slots=True)
class LegacyBrokerApprovalProjection:
    """Data-only boundary projection supplied by a cross-app composition root."""

    account_id: int
    agent_id: str
    asset_code: str
    market: str
    side: str
    order_type: str
    quantity: Decimal
    limit_price: Decimal | None
    estimated_amount: Decimal
    expires_at: str
    risk_policy_version: str
    risk_snapshot_json: str
    approval_mode: str
    source_recommendation_ids: tuple[str, ...]
    source_signal_ids: tuple[str, ...]


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_source_ids(values: tuple[str, ...], *, field_name: str, required: bool) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    if required and not values:
        raise ValueError(f"{field_name} must not be empty")
    for value in values:
        _require_token(value, field_name)
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{field_name} must be ordered and unique")


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"risk_snapshot_json contains invalid constant {value}")


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("risk_snapshot_json contains duplicate keys")
        result[key] = value
    return result


def _validate_risk_snapshot_json(value: object) -> None:
    if type(value) is not str or not value:
        raise ValueError("risk_snapshot_json must be canonical JSON object text")
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("risk_snapshot_json must be canonical JSON object text") from error
    if type(decoded) is not dict:
        raise ValueError("risk_snapshot_json must encode an object")
    canonical = json.dumps(
        decoded, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if value != canonical:
        raise ValueError("risk_snapshot_json must use canonical JSON encoding")


def _parse_expiry(value: object) -> datetime:
    if type(value) is not str or not value:
        raise ValueError("expires_at must be a timezone-aware ISO-8601 datetime")
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("expires_at must be a timezone-aware ISO-8601 datetime") from error
    _require_aware(expiry, "expires_at")
    return expiry


def _validate_projection(
    projection: LegacyBrokerApprovalProjection, *, evaluated_at: datetime
) -> datetime:
    if type(projection) is not LegacyBrokerApprovalProjection:
        raise TypeError("projection must be an exact LegacyBrokerApprovalProjection")
    _require_aware(evaluated_at, "evaluated_at")
    if type(projection.account_id) is not int or projection.account_id <= 0:
        raise ValueError("account_id must be a positive integer")
    for field_name in (
        "agent_id",
        "asset_code",
        "market",
        "risk_policy_version",
        "approval_mode",
    ):
        _require_token(getattr(projection, field_name), field_name)
    if projection.side not in {"BUY", "SELL"}:
        raise ValueError("side must be a canonical broker side")
    if projection.order_type != "LIMIT":
        raise ValueError("legacy approval snapshot adapter supports LIMIT orders only")
    if (
        type(projection.quantity) is not Decimal
        or not projection.quantity.is_finite()
        or projection.quantity <= 0
        or projection.quantity != projection.quantity.to_integral_value()
    ):
        raise ValueError("quantity must be a positive finite whole Decimal")
    if (
        type(projection.limit_price) is not Decimal
        or not projection.limit_price.is_finite()
        or projection.limit_price <= 0
    ):
        raise ValueError("limit_price must be a positive finite Decimal")
    if (
        type(projection.estimated_amount) is not Decimal
        or not projection.estimated_amount.is_finite()
        or projection.estimated_amount <= 0
    ):
        raise ValueError("estimated_amount must be a positive finite Decimal")
    expected_amount = (projection.quantity * projection.limit_price).quantize(_AMOUNT_QUANTUM)
    if projection.estimated_amount != expected_amount:
        raise ValueError("estimated_amount must equal quantity times limit_price")
    _validate_risk_snapshot_json(projection.risk_snapshot_json)
    _require_source_ids(
        projection.source_recommendation_ids,
        field_name="source_recommendation_ids",
        required=True,
    )
    _require_source_ids(
        projection.source_signal_ids, field_name="source_signal_ids", required=False
    )
    expiry = _parse_expiry(projection.expires_at)
    if expiry <= evaluated_at:
        raise ValueError("approval snapshot is expired at evaluated_at")
    return expiry


def _content_hash(projection: LegacyBrokerApprovalProjection) -> str:
    payload = asdict(projection)
    payload["quantity"] = str(projection.quantity)
    payload["limit_price"] = str(projection.limit_price)
    payload["estimated_amount"] = str(projection.estimated_amount)
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_broker_approval_projection_legacy_evidence_summary(
    projection: LegacyBrokerApprovalProjection, *, evaluated_at: datetime
) -> EvidenceSummaryDTO:
    """Wrap one exact broker projection as legacy-unverified display-only Evidence."""

    valid_until = _validate_projection(projection, evaluated_at=evaluated_at)
    content_hash = _content_hash(projection)
    artifact = ArtifactRef(
        owner="broker_execution",
        artifact_type="order_approval_snapshot",
        artifact_id=content_hash,
        artifact_version=_ARTIFACT_VERSION,
        content_hash=content_hash,
    )
    envelope = build_legacy_unverified_envelope(
        output_artifact=artifact,
        claim_kind=ClaimKind.DERIVED,
        method_kind=MethodKind.DETERMINISTIC,
        evaluated_at=evaluated_at,
        valid_until=valid_until,
    )
    return EvidenceSummaryDTO.from_legacy_envelope(envelope=envelope)


__all__ = [
    "LegacyBrokerApprovalProjection",
    "build_broker_approval_projection_legacy_evidence_summary",
]
