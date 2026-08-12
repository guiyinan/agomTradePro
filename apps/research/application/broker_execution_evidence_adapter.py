"""Fail-closed Evidence adapter for legacy broker approval snapshots."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from apps.broker_execution.domain.entities import (
    LiveOrderSide,
    LiveOrderType,
    OrderApprovalSnapshot,
)
from apps.broker_execution.domain.rules import build_approval_digest
from apps.research.application.evidence_summary import EvidenceSummaryDTO
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    MethodKind,
    build_legacy_unverified_envelope,
)

_AMOUNT_QUANTUM = Decimal("0.01")
_ARTIFACT_VERSION = "approval-snapshot-v1"


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


def _require_source_ids(
    values: tuple[str, ...],
    *,
    field_name: str,
    required: bool,
) -> None:
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
        decoded,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
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


def _validate_snapshot(snapshot: OrderApprovalSnapshot, *, evaluated_at: datetime) -> datetime:
    if type(snapshot) is not OrderApprovalSnapshot:
        raise TypeError("snapshot must be an exact OrderApprovalSnapshot")
    _require_aware(evaluated_at, "evaluated_at")
    if type(snapshot.account_id) is not int or snapshot.account_id <= 0:
        raise ValueError("account_id must be a positive integer")
    for field_name in (
        "agent_id",
        "asset_code",
        "market",
        "risk_policy_version",
        "approval_mode",
    ):
        _require_token(getattr(snapshot, field_name), field_name)
    if type(snapshot.side) is not LiveOrderSide:
        raise TypeError("side must be an exact LiveOrderSide")
    if type(snapshot.order_type) is not LiveOrderType:
        raise TypeError("order_type must be an exact LiveOrderType")
    if snapshot.order_type is not LiveOrderType.LIMIT:
        raise ValueError("legacy approval snapshot adapter supports LIMIT orders only")
    if (
        type(snapshot.quantity) is not Decimal
        or not snapshot.quantity.is_finite()
        or snapshot.quantity <= 0
        or snapshot.quantity != snapshot.quantity.to_integral_value()
    ):
        raise ValueError("quantity must be a positive finite whole Decimal")
    if (
        type(snapshot.limit_price) is not Decimal
        or not snapshot.limit_price.is_finite()
        or snapshot.limit_price <= 0
    ):
        raise ValueError("limit_price must be a positive finite Decimal")
    if (
        type(snapshot.estimated_amount) is not Decimal
        or not snapshot.estimated_amount.is_finite()
        or snapshot.estimated_amount <= 0
    ):
        raise ValueError("estimated_amount must be a positive finite Decimal")
    expected_amount = (snapshot.quantity * snapshot.limit_price).quantize(_AMOUNT_QUANTUM)
    if snapshot.estimated_amount != expected_amount:
        raise ValueError("estimated_amount must equal quantity times limit_price")
    _validate_risk_snapshot_json(snapshot.risk_snapshot_json)
    _require_source_ids(
        snapshot.source_recommendation_ids,
        field_name="source_recommendation_ids",
        required=True,
    )
    _require_source_ids(
        snapshot.source_signal_ids,
        field_name="source_signal_ids",
        required=False,
    )
    expiry = _parse_expiry(snapshot.expires_at)
    if expiry <= evaluated_at:
        raise ValueError("approval snapshot is expired at evaluated_at")
    return expiry


def build_order_approval_snapshot_legacy_evidence_summary(
    snapshot: OrderApprovalSnapshot,
    *,
    evaluated_at: datetime,
) -> EvidenceSummaryDTO:
    """Wrap one exact approval snapshot as legacy-unverified display-only Evidence."""

    valid_until = _validate_snapshot(snapshot, evaluated_at=evaluated_at)
    content_hash = build_approval_digest(snapshot)
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


__all__ = ["build_order_approval_snapshot_legacy_evidence_summary"]
