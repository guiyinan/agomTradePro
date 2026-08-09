"""Canonical row-header seals for the R6 activation ledgers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256

from apps.research.application.state_model_activation import R6ActivationCorruption
from apps.research.domain.state_model_activation import (
    R6ActivationApprovalRef,
    R6ActivationAuthorization,
    R6ActivationEvent,
)
from apps.research.infrastructure.state_model_activation_codec import (
    encode_r6_activation_authorization,
    encode_r6_activation_event,
)
from apps.research.infrastructure.state_model_activation_models import (
    R6ActivationAuthorizationModel,
    R6ActivationEventModel,
    R6ActivationStreamCommitModel,
)


def _aware_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise R6ActivationCorruption(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _ledger_value(value: object) -> object:
    if isinstance(value, datetime):
        return _aware_utc(value, "R6 activation ledger datetime").isoformat()
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise R6ActivationCorruption("R6 activation ledger keys must be strings")
        return {
            key: _ledger_value(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    if isinstance(value, (list, tuple)):
        return [_ledger_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise R6ActivationCorruption(f"unsupported R6 activation ledger value: {type(value).__name__}")


def ledger_header_hash(*, row_kind: str, values: dict[str, object]) -> str:
    """Return the canonical SHA-256 header seal for one ledger row."""

    payload = {
        "schema": "r6-activation-ledger-row-header.v1",
        "row_kind": row_kind,
        "values": {
            key: _ledger_value(value)
            for key, value in sorted(values.items(), key=lambda item: item[0])
            if key != "ledger_header_hash"
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def require_exact_values(
    *,
    model: R6ActivationAuthorizationModel | R6ActivationEventModel | R6ActivationStreamCommitModel,
    values: dict[str, object],
    label: str,
) -> None:
    """Reject a row whose persisted header differs from its canonical values."""

    if any(getattr(model, field_name) != expected for field_name, expected in values.items()):
        raise R6ActivationCorruption(f"R6 activation {label} row header differs")


def _approval_values(
    ref: R6ActivationApprovalRef | None,
    *,
    prefix: str,
) -> dict[str, object]:
    return {
        f"{prefix}_approval_id": None if ref is None else ref.approval_id,
        f"{prefix}_approval_version": None if ref is None else ref.approval_version,
        f"{prefix}_approval_hash": None if ref is None else ref.approval_hash,
    }


def authorization_values(
    authorization: R6ActivationAuthorization,
    *,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    """Return the complete canonical authorization row values."""

    values: dict[str, object] = {
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "event_id": authorization.event_id,
        "event_version": authorization.event_version,
        "scope_id": authorization.scope_ref.scope_id,
        "scope_version": authorization.scope_ref.scope_version,
        "scope_hash": authorization.scope_ref.scope_hash,
        "action": authorization.action.value,
        **_approval_values(authorization.subject, prefix="subject"),
        **_approval_values(authorization.rollback_target, prefix="rollback"),
        "expected_sequence": authorization.expected_sequence,
        "expected_previous_event_hash": authorization.expected_previous_event_hash,
        "owner": authorization.owner,
        "issued_at": authorization.issued_at,
        "owner_recorded_at": authorization.recorded_at,
        "valid_until": authorization.valid_until,
        "reason_codes": list(authorization.reason_codes),
        "evidence_ref": authorization.evidence_ref,
        "canonical_payload": encode_r6_activation_authorization(authorization),
        "content_hash": authorization.content_hash,
        "ledger_recorded_at": ledger_recorded_at,
        "research_only": authorization.research_only,
        "must_not_use_for_decision": authorization.must_not_use_for_decision,
        "must_not_replace_regime": authorization.must_not_replace_regime,
        "must_not_publish_current": authorization.must_not_publish_current,
        "must_not_execute": authorization.must_not_execute,
    }
    values["ledger_header_hash"] = ledger_header_hash(
        row_kind="authorization",
        values=values,
    )
    return values


def event_values(
    event: R6ActivationEvent,
    *,
    authorization_row_id: int,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    """Return the complete canonical activation-event row values."""

    values: dict[str, object] = {
        "authorization_row_id": authorization_row_id,
        "event_id": event.event_id,
        "event_version": event.event_version,
        "scope_id": event.scope_ref.scope_id,
        "scope_version": event.scope_ref.scope_version,
        "scope_hash": event.scope_ref.scope_hash,
        "action": event.action.value,
        **_approval_values(event.subject, prefix="subject"),
        **_approval_values(event.rollback_target, prefix="rollback"),
        "authorization_id": event.authorization_id,
        "authorization_version": event.authorization_version,
        "authorization_hash": event.authorization_hash,
        "sequence": event.sequence,
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "previous_event_hash": event.previous_event_hash,
        "reason_codes": list(event.reason_codes),
        "canonical_payload": encode_r6_activation_event(event),
        "content_hash": event.content_hash,
        "ledger_recorded_at": ledger_recorded_at,
        "research_only": event.research_only,
        "must_not_use_for_decision": event.must_not_use_for_decision,
        "must_not_replace_regime": event.must_not_replace_regime,
        "must_not_publish_current": event.must_not_publish_current,
        "must_not_execute": event.must_not_execute,
    }
    values["ledger_header_hash"] = ledger_header_hash(row_kind="event", values=values)
    return values


def stream_commit_values(
    *,
    authorization: R6ActivationAuthorization,
    event: R6ActivationEvent,
    authorization_row_id: int,
    event_row_id: int,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    """Return the complete three-way stream-commit row values."""

    values: dict[str, object] = {
        "authorization_row_id": authorization_row_id,
        "event_row_id": event_row_id,
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "authorization_hash": authorization.content_hash,
        "event_id": event.event_id,
        "event_version": event.event_version,
        "event_hash": event.content_hash,
        "scope_id": event.scope_ref.scope_id,
        "scope_version": event.scope_ref.scope_version,
        "scope_hash": event.scope_ref.scope_hash,
        "sequence": event.sequence,
        "previous_event_hash": event.previous_event_hash,
        "ledger_recorded_at": ledger_recorded_at,
        "research_only": event.research_only,
        "must_not_use_for_decision": event.must_not_use_for_decision,
        "must_not_replace_regime": event.must_not_replace_regime,
        "must_not_publish_current": event.must_not_publish_current,
        "must_not_execute": event.must_not_execute,
    }
    values["ledger_header_hash"] = ledger_header_hash(
        row_kind="stream_commit",
        values=values,
    )
    return values
