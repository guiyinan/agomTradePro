"""Typed fail-closed Evidence projection for one broker order detail read."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from apps.broker_execution.domain.services import (
    approval_digest_for_order,
    approval_snapshot_for_order,
)
from core.integration.legacy_broker_approval_evidence import (
    LegacyBrokerApprovalEvidenceProjectorUnavailable,
    project_legacy_broker_approval_evidence,
)

JsonObject = dict[str, object]

DISPLAY_ONLY: Final = "display_only"
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ORDER_ACTIONS: Final = ("approve", "reject", "cancel")
_EVENT_FIELDS: Final = (
    "event_id",
    "event_type",
    "status",
    "occurred_at",
    "received_at",
)
_FILL_FIELDS: Final = (
    "broker_trade_id",
    "quantity",
    "price",
    "amount",
    "occurred_at",
)
_EVIDENCE_FIELDS: Final = frozenset(
    {
        "output_owner",
        "output_artifact_type",
        "output_artifact_id",
        "output_artifact_version",
        "output_content_hash",
        "envelope_content_hash",
        "operator_spec_content_hash",
        "claim_kind",
        "method_kind",
        "research_family",
        "governance_state",
        "permission",
        "blocker_codes",
        "dependency_flags",
        "track_record_availability",
        "track_record_content_hash",
        "n_eff",
        "coverage",
        "evaluated_at",
        "valid_until",
        "must_not_use_for_decision",
        "must_not_execute",
    }
)


def _require_aware(value: datetime) -> None:
    """Require a trusted timezone-aware projection clock."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluated_at must be a timezone-aware datetime")


def _validated_evidence_payload(
    value: Mapping[str, object], *, evaluated_at: datetime
) -> JsonObject:
    """Close and validate the app-neutral projector response before publication."""

    if type(value) is not dict or set(value) != _EVIDENCE_FIELDS:
        raise ValueError("legacy approval Evidence response is not closed")
    expected_values = {
        "output_owner": "broker_execution",
        "output_artifact_type": "order_approval_snapshot",
        "output_artifact_version": "approval-snapshot-v1",
        "claim_kind": "derived",
        "method_kind": "deterministic",
        "research_family": "legacy",
        "governance_state": "research_only",
        "permission": DISPLAY_ONLY,
        "blocker_codes": ["evidence.legacy_unverified"],
        "dependency_flags": [],
        "track_record_availability": "unavailable",
        "track_record_content_hash": None,
        "n_eff": None,
        "coverage": None,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    if any(value.get(key) != expected for key, expected in expected_values.items()):
        raise ValueError("legacy approval Evidence response widened authority")
    for field_name in (
        "output_content_hash",
        "envelope_content_hash",
        "operator_spec_content_hash",
    ):
        field_value = value.get(field_name)
        if type(field_value) is not str or _DIGEST_PATTERN.fullmatch(field_value) is None:
            raise ValueError("legacy approval Evidence response contains an invalid digest")
    if value.get("output_artifact_id") != value.get("output_content_hash"):
        raise ValueError("legacy approval Evidence artifact identity is not content-bound")
    if value.get("evaluated_at") != evaluated_at.isoformat():
        raise ValueError("legacy approval Evidence response changed evaluated_at")
    valid_until_raw = value.get("valid_until")
    if type(valid_until_raw) is not str:
        raise ValueError("legacy approval Evidence valid_until is invalid")
    try:
        valid_until = datetime.fromisoformat(valid_until_raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("legacy approval Evidence valid_until is invalid") from error
    _require_aware(valid_until)
    if valid_until <= evaluated_at:
        raise ValueError("legacy approval Evidence is expired")
    return dict(value)


def _boolean_actions(value: object) -> dict[str, bool]:
    """Project only the three stable order-action flags."""

    source = value if isinstance(value, Mapping) else {}
    return {action: source.get(action) is True for action in _ORDER_ACTIONS}


def _allowlisted_rows(
    value: object,
    *,
    fields: tuple[str, ...],
    invalid_blocker: str,
) -> tuple[list[JsonObject], tuple[str, ...]]:
    """Strip untyped nested payloads and flag malformed timeline rows."""

    if value is None:
        return [], ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return [], (invalid_blocker,)
    rows: list[JsonObject] = []
    malformed = False
    for raw in value:
        if not isinstance(raw, Mapping):
            malformed = True
            continue
        rows.append({field: raw.get(field) for field in fields})
    return rows, ((invalid_blocker,) if malformed else ())


@dataclass(frozen=True, slots=True)
class BrokerOrderDetailResult:
    """One order plus explicit lifecycle, authorization, and Evidence gates."""

    order: JsonObject
    evaluated_at: datetime
    lifecycle_transitions: dict[str, bool]
    actor_authorization: dict[str, bool]
    transport_blocker_codes: tuple[str, ...]
    approval_evidence_status: str
    approval_evidence_blocker_codes: tuple[str, ...]
    approval_evidence: JsonObject | None
    permission: str = DISPLAY_ONLY
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        """Prevent callers from widening the legacy adapter's authority."""

        _require_aware(self.evaluated_at)
        if self.permission != DISPLAY_ONLY:
            raise ValueError("broker order detail permission must remain display_only")
        if self.must_not_use_for_decision is not True or self.must_not_execute is not True:
            raise ValueError("broker order detail legacy Evidence must remain fail-closed")
        if set(self.lifecycle_transitions) != set(_ORDER_ACTIONS) or set(
            self.actor_authorization
        ) != set(_ORDER_ACTIONS):
            raise ValueError("order actions must use the stable approve/reject/cancel set")
        if not all(type(value) is bool for value in self.lifecycle_transitions.values()):
            raise TypeError("lifecycle transition flags must be booleans")
        if not all(type(value) is bool for value in self.actor_authorization.values()):
            raise TypeError("actor authorization flags must be booleans")
        if self.approval_evidence_status not in {"blocked", DISPLAY_ONLY}:
            raise ValueError("approval_evidence_status is invalid")
        if self.approval_evidence_status == DISPLAY_ONLY:
            if self.approval_evidence is None or self.approval_evidence_blocker_codes:
                raise ValueError("display-only approval Evidence must be exact and unblocked")
        elif self.approval_evidence is not None or not self.approval_evidence_blocker_codes:
            raise ValueError("blocked approval Evidence must publish stable blockers")

    def to_payload(self) -> JsonObject:
        """Preserve safe order fields and append governed read markers."""

        return {
            **self.order,
            "evaluated_at": self.evaluated_at.isoformat(),
            "lifecycle_transitions": dict(self.lifecycle_transitions),
            "actor_authorization": dict(self.actor_authorization),
            "transport_blocker_codes": list(self.transport_blocker_codes),
            "event_payload_policy": "omitted_untyped",
            "risk_snapshot_policy": "content_hash_only",
            "approval_evidence_status": self.approval_evidence_status,
            "approval_evidence_blocker_codes": list(self.approval_evidence_blocker_codes),
            "approval_evidence": (
                dict(self.approval_evidence) if self.approval_evidence is not None else None
            ),
            "permission": self.permission,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
        }


def _safe_order(
    order: JsonObject,
) -> tuple[JsonObject, dict[str, bool], tuple[str, ...]]:
    """Remove ambiguous action hints and allowlist broker timeline rows."""

    safe = dict(order)
    lifecycle = _boolean_actions(safe.pop("action_availability", None))
    raw_risk_snapshot = safe.pop("risk_snapshot", None)
    risk_blockers: tuple[str, ...] = ()
    try:
        canonical_risk = json.dumps(
            raw_risk_snapshot,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        safe["risk_snapshot_content_hash"] = hashlib.sha256(
            canonical_risk.encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError):
        safe["risk_snapshot_content_hash"] = None
        risk_blockers = ("broker_order_risk_snapshot_invalid",)
    events, event_blockers = _allowlisted_rows(
        safe.pop("events", None),
        fields=_EVENT_FIELDS,
        invalid_blocker="broker_order_events_invalid",
    )
    fills, fill_blockers = _allowlisted_rows(
        safe.pop("fills", None),
        fields=_FILL_FIELDS,
        invalid_blocker="broker_order_fills_invalid",
    )
    safe["events"] = events
    safe["fills"] = fills
    return safe, lifecycle, risk_blockers + event_blockers + fill_blockers


def _blocked(
    order: JsonObject,
    *,
    evaluated_at: datetime,
    actor_authorization: Mapping[str, bool],
    blocker_code: str,
) -> BrokerOrderDetailResult:
    """Build one stable display-only blocked result."""

    safe_order, lifecycle, transport_blockers = _safe_order(order)
    return BrokerOrderDetailResult(
        order=safe_order,
        evaluated_at=evaluated_at,
        lifecycle_transitions=lifecycle,
        actor_authorization=_boolean_actions(actor_authorization),
        transport_blocker_codes=transport_blockers,
        approval_evidence_status="blocked",
        approval_evidence_blocker_codes=(blocker_code,),
        approval_evidence=None,
    )


def project_broker_order_detail(
    order: JsonObject,
    *,
    evaluated_at: datetime,
    actor_authorization: Mapping[str, bool],
) -> BrokerOrderDetailResult:
    """Bind exact approval content to display-only Evidence or fail closed."""

    _require_aware(evaluated_at)
    persisted_digest = order.get("approval_digest")
    if not isinstance(persisted_digest, str) or not persisted_digest:
        return _blocked(
            order,
            evaluated_at=evaluated_at,
            actor_authorization=actor_authorization,
            blocker_code="broker_order_approval_missing",
        )
    if _DIGEST_PATTERN.fullmatch(persisted_digest) is None:
        return _blocked(
            order,
            evaluated_at=evaluated_at,
            actor_authorization=actor_authorization,
            blocker_code="broker_order_approval_digest_invalid",
        )

    try:
        snapshot = approval_snapshot_for_order(order)
        current_digest = approval_digest_for_order(order)
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return _blocked(
            order,
            evaluated_at=evaluated_at,
            actor_authorization=actor_authorization,
            blocker_code="broker_order_approval_snapshot_invalid",
        )
    if not hmac.compare_digest(persisted_digest, current_digest):
        return _blocked(
            order,
            evaluated_at=evaluated_at,
            actor_authorization=actor_authorization,
            blocker_code="broker_order_approval_digest_mismatch",
        )
    if snapshot.risk_snapshot_json == "{}":
        return _blocked(
            order,
            evaluated_at=evaluated_at,
            actor_authorization=actor_authorization,
            blocker_code="broker_order_approval_evidence_invalid",
        )

    projection: JsonObject = {
        "account_id": snapshot.account_id,
        "agent_id": snapshot.agent_id,
        "asset_code": snapshot.asset_code,
        "market": snapshot.market,
        "side": snapshot.side.value,
        "order_type": snapshot.order_type.value,
        "quantity": snapshot.quantity,
        "limit_price": snapshot.limit_price,
        "estimated_amount": snapshot.estimated_amount,
        "expires_at": snapshot.expires_at,
        "risk_policy_version": snapshot.risk_policy_version,
        "risk_snapshot_json": snapshot.risk_snapshot_json,
        "approval_mode": snapshot.approval_mode,
        "source_recommendation_ids": snapshot.source_recommendation_ids,
        "source_signal_ids": snapshot.source_signal_ids,
        "evaluated_at": evaluated_at,
    }
    try:
        summary = _validated_evidence_payload(
            project_legacy_broker_approval_evidence(projection),
            evaluated_at=evaluated_at,
        )
    except LegacyBrokerApprovalEvidenceProjectorUnavailable:
        return _blocked(
            order,
            evaluated_at=evaluated_at,
            actor_authorization=actor_authorization,
            blocker_code="broker_order_approval_evidence_provider_unavailable",
        )
    except (ArithmeticError, TypeError, ValueError):
        return _blocked(
            order,
            evaluated_at=evaluated_at,
            actor_authorization=actor_authorization,
            blocker_code="broker_order_approval_evidence_invalid",
        )
    output_content_hash = summary["output_content_hash"]
    if type(output_content_hash) is not str or not hmac.compare_digest(
        output_content_hash, persisted_digest
    ):
        return _blocked(
            order,
            evaluated_at=evaluated_at,
            actor_authorization=actor_authorization,
            blocker_code="broker_order_approval_evidence_digest_mismatch",
        )
    safe_order, lifecycle, transport_blockers = _safe_order(order)
    return BrokerOrderDetailResult(
        order=safe_order,
        evaluated_at=evaluated_at,
        lifecycle_transitions=lifecycle,
        actor_authorization=_boolean_actions(actor_authorization),
        transport_blocker_codes=transport_blockers,
        approval_evidence_status=DISPLAY_ONLY,
        approval_evidence_blocker_codes=(),
        approval_evidence=summary,
    )


__all__ = ["BrokerOrderDetailResult", "DISPLAY_ONLY", "project_broker_order_detail"]
