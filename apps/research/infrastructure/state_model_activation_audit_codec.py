"""Immutable snapshot and signed-cursor codec for R6 activation audit paging."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from django.core import signing

from apps.research.application.state_model_activation import (
    R6ActivationCorruption,
    R6ActivationUnavailable,
)
from apps.research.application.state_model_activation_persistence import (
    R6ActivationAuditEntry,
    R6ActivationEventRef,
)
from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApprovalRef,
    R6ActivationAuthorizationRef,
    R6ActivationScopeRef,
)
from apps.research.infrastructure.state_model_activation_models import (
    R6ActivationAuditSnapshotModel,
)


def _aware_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise R6ActivationCorruption(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


_AUDIT_CURSOR_SCHEMA = "r6-activation-audit-cursor.v1"
_AUDIT_CURSOR_SALT = "research.r6-activation-audit-cursor.v1"
_AUDIT_SNAPSHOT_SCHEMA = "r6-activation-audit-snapshot-payload.v1"
_AUDIT_SNAPSHOT_VERSION = "r6-activation-audit-snapshot.v1"


@dataclass(frozen=True)
class _AuditCursor:
    snapshot_as_of: datetime
    snapshot_id: str
    snapshot_version: str
    snapshot_hash: str
    next_offset: int


@dataclass(frozen=True)
class _AuditSnapshot:
    snapshot_id: str
    snapshot_version: str
    as_of: datetime
    created_at: datetime
    entries: tuple[R6ActivationAuditEntry, ...]
    internal_audit_only: bool
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    must_not_publish_current: bool
    must_not_execute: bool
    content_hash: str


def _require_token(value: object, label: str, *, maximum: int = 192) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise R6ActivationCorruption(f"{label} is invalid")
    return value


def _require_hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise R6ActivationCorruption(f"{label} is not a lowercase SHA-256 hash")
    return value


def _payload_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise R6ActivationCorruption(f"R6 activation {label} must be an object")
    return value


def _payload_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise R6ActivationCorruption(f"R6 activation {label} must be a string")
    return value


def _payload_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise R6ActivationCorruption(f"R6 activation {label} must be boolean")
    return value


def _payload_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise R6ActivationCorruption(f"R6 activation {label} must be an integer")
    return value


def _payload_datetime(value: object, label: str) -> datetime:
    raw = _payload_string(value, label)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise R6ActivationCorruption(f"R6 activation {label} is invalid") from error
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.astimezone(UTC).isoformat() != raw
    ):
        raise R6ActivationCorruption(f"R6 activation {label} is non-canonical")
    return parsed


def _approval_payload(ref: R6ActivationApprovalRef | None) -> object:
    if ref is None:
        return None
    ref.__post_init__()
    return {
        "approval_id": ref.approval_id,
        "approval_version": ref.approval_version,
        "approval_hash": ref.approval_hash,
    }


def _decode_approval_payload(value: object, label: str) -> R6ActivationApprovalRef | None:
    if value is None:
        return None
    mapping = _payload_mapping(value, label)
    if set(mapping) != {"approval_id", "approval_version", "approval_hash"}:
        raise R6ActivationCorruption(f"R6 activation {label} fields differ")
    return R6ActivationApprovalRef(
        _payload_string(mapping["approval_id"], f"{label}.approval_id"),
        _payload_string(mapping["approval_version"], f"{label}.approval_version"),
        _payload_string(mapping["approval_hash"], f"{label}.approval_hash"),
    )


def _encode_audit_entry(entry: R6ActivationAuditEntry) -> dict[str, object]:
    return {
        "event_id": entry.event_ref.event_id,
        "event_version": entry.event_ref.event_version,
        "event_hash": entry.event_ref.event_hash,
        "authorization_id": entry.authorization_ref.authorization_id,
        "authorization_version": entry.authorization_ref.authorization_version,
        "authorization_hash": entry.authorization_hash,
        "scope_id": entry.scope_ref.scope_id,
        "scope_version": entry.scope_ref.scope_version,
        "scope_hash": entry.scope_ref.scope_hash,
        "action": entry.action.value,
        "subject": _approval_payload(entry.subject),
        "rollback_target": _approval_payload(entry.rollback_target),
        "sequence": entry.sequence,
        "occurred_at": entry.occurred_at.astimezone(UTC).isoformat(),
        "ledger_recorded_at": entry.ledger_recorded_at.astimezone(UTC).isoformat(),
        "research_only": entry.research_only,
        "must_not_use_for_decision": entry.must_not_use_for_decision,
        "must_not_replace_regime": entry.must_not_replace_regime,
        "must_not_publish_current": entry.must_not_publish_current,
        "must_not_execute": entry.must_not_execute,
    }


def _decode_audit_entry(value: object) -> R6ActivationAuditEntry:
    mapping = _payload_mapping(value, "audit snapshot entry")
    expected = {
        "event_id",
        "event_version",
        "event_hash",
        "authorization_id",
        "authorization_version",
        "authorization_hash",
        "scope_id",
        "scope_version",
        "scope_hash",
        "action",
        "subject",
        "rollback_target",
        "sequence",
        "occurred_at",
        "ledger_recorded_at",
        "research_only",
        "must_not_use_for_decision",
        "must_not_replace_regime",
        "must_not_publish_current",
        "must_not_execute",
    }
    if set(mapping) != expected:
        raise R6ActivationCorruption("R6 activation audit snapshot entry fields differ")
    try:
        entry = R6ActivationAuditEntry(
            event_ref=R6ActivationEventRef(
                _payload_string(mapping["event_id"], "audit event_id"),
                _payload_string(mapping["event_version"], "audit event_version"),
                _payload_string(mapping["event_hash"], "audit event_hash"),
            ),
            authorization_ref=R6ActivationAuthorizationRef(
                _payload_string(mapping["authorization_id"], "audit authorization_id"),
                _payload_string(
                    mapping["authorization_version"],
                    "audit authorization_version",
                ),
            ),
            authorization_hash=_payload_string(
                mapping["authorization_hash"],
                "audit authorization_hash",
            ),
            scope_ref=R6ActivationScopeRef(
                _payload_string(mapping["scope_id"], "audit scope_id"),
                _payload_string(mapping["scope_version"], "audit scope_version"),
                _payload_string(mapping["scope_hash"], "audit scope_hash"),
            ),
            action=R6ActivationAction(_payload_string(mapping["action"], "audit action")),
            subject=_decode_required_approval(mapping["subject"], "audit subject"),
            rollback_target=_decode_approval_payload(
                mapping["rollback_target"],
                "audit rollback_target",
            ),
            sequence=_payload_int(mapping["sequence"], "audit sequence"),
            occurred_at=_payload_datetime(mapping["occurred_at"], "audit occurred_at"),
            ledger_recorded_at=_payload_datetime(
                mapping["ledger_recorded_at"],
                "audit ledger_recorded_at",
            ),
            research_only=_payload_bool(mapping["research_only"], "audit research_only"),
            must_not_use_for_decision=_payload_bool(
                mapping["must_not_use_for_decision"],
                "audit must_not_use_for_decision",
            ),
            must_not_replace_regime=_payload_bool(
                mapping["must_not_replace_regime"],
                "audit must_not_replace_regime",
            ),
            must_not_publish_current=_payload_bool(
                mapping["must_not_publish_current"],
                "audit must_not_publish_current",
            ),
            must_not_execute=_payload_bool(mapping["must_not_execute"], "audit must_not_execute"),
        )
    except (TypeError, ValueError) as error:
        raise R6ActivationCorruption("R6 activation audit snapshot entry is invalid") from error
    _validate_audit_entry(entry)
    return entry


def _decode_required_approval(value: object, label: str) -> R6ActivationApprovalRef:
    result = _decode_approval_payload(value, label)
    if result is None:
        raise R6ActivationCorruption(f"R6 activation {label} is absent")
    return result


def _validate_audit_entry(entry: R6ActivationAuditEntry) -> None:
    entry.event_ref.__post_init__()
    entry.authorization_ref.__post_init__()
    entry.scope_ref.__post_init__()
    entry.subject.__post_init__()
    if entry.rollback_target is not None:
        entry.rollback_target.__post_init__()
    _require_hash(entry.authorization_hash, "audit authorization_hash")
    if isinstance(entry.sequence, bool) or entry.sequence < 1:
        raise R6ActivationCorruption("R6 activation audit sequence is invalid")
    _aware_utc(entry.occurred_at, "activation audit occurred_at")
    _aware_utc(entry.ledger_recorded_at, "activation audit ledger_recorded_at")
    if entry.occurred_at > entry.ledger_recorded_at:
        raise R6ActivationCorruption("R6 activation audit clocks are invalid")
    if (entry.action is R6ActivationAction.ROLLBACK) != (entry.rollback_target is not None):
        raise R6ActivationCorruption("R6 activation audit rollback shape is invalid")
    if not (
        entry.research_only
        and entry.must_not_use_for_decision
        and entry.must_not_replace_regime
        and entry.must_not_publish_current
        and entry.must_not_execute
    ):
        raise R6ActivationCorruption("R6 activation audit safety flags are relaxed")


def _create_audit_snapshot(
    *,
    as_of: datetime,
    created_at: datetime,
    entries: tuple[R6ActivationAuditEntry, ...],
) -> _AuditSnapshot:
    normalized_as_of = _aware_utc(as_of, "activation audit snapshot as_of")
    normalized_created_at = _aware_utc(created_at, "activation audit snapshot created_at")
    if normalized_as_of > normalized_created_at:
        raise R6ActivationUnavailable("activation audit snapshot clock moved backwards")
    snapshot_id = f"r6-activation-audit-snapshot:{uuid4()}"
    digest = _audit_snapshot_hash(
        snapshot_id=snapshot_id,
        snapshot_version=_AUDIT_SNAPSHOT_VERSION,
        as_of=normalized_as_of,
        created_at=normalized_created_at,
        entries=entries,
    )
    return _AuditSnapshot(
        snapshot_id=snapshot_id,
        snapshot_version=_AUDIT_SNAPSHOT_VERSION,
        as_of=normalized_as_of,
        created_at=normalized_created_at,
        entries=entries,
        internal_audit_only=True,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_replace_regime=True,
        must_not_publish_current=True,
        must_not_execute=True,
        content_hash=digest,
    )


def _audit_snapshot_hash(
    *,
    snapshot_id: str,
    snapshot_version: str,
    as_of: datetime,
    created_at: datetime,
    entries: tuple[R6ActivationAuditEntry, ...],
) -> str:
    body = {
        "snapshot_id": snapshot_id,
        "snapshot_version": snapshot_version,
        "as_of": as_of.astimezone(UTC).isoformat(),
        "created_at": created_at.astimezone(UTC).isoformat(),
        "entries": [_encode_audit_entry(entry) for entry in entries],
        "internal_audit_only": True,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_replace_regime": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _audit_snapshot_payload(snapshot: _AuditSnapshot) -> dict[str, object]:
    return {
        "schema": _AUDIT_SNAPSHOT_SCHEMA,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of.isoformat(),
        "created_at": snapshot.created_at.isoformat(),
        "entries": [_encode_audit_entry(entry) for entry in snapshot.entries],
        "internal_audit_only": snapshot.internal_audit_only,
        "research_only": snapshot.research_only,
        "must_not_use_for_decision": snapshot.must_not_use_for_decision,
        "must_not_replace_regime": snapshot.must_not_replace_regime,
        "must_not_publish_current": snapshot.must_not_publish_current,
        "must_not_execute": snapshot.must_not_execute,
        "content_hash": snapshot.content_hash,
    }


def _audit_snapshot_values(snapshot: _AuditSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "entry_count": len(snapshot.entries),
        "canonical_payload": _audit_snapshot_payload(snapshot),
        "content_hash": snapshot.content_hash,
        "internal_audit_only": snapshot.internal_audit_only,
        "research_only": snapshot.research_only,
        "must_not_use_for_decision": snapshot.must_not_use_for_decision,
        "must_not_replace_regime": snapshot.must_not_replace_regime,
        "must_not_publish_current": snapshot.must_not_publish_current,
        "must_not_execute": snapshot.must_not_execute,
    }


def _restore_audit_snapshot(model: R6ActivationAuditSnapshotModel) -> _AuditSnapshot:
    payload = _payload_mapping(model.canonical_payload, "audit snapshot")
    expected = {
        "schema",
        "snapshot_id",
        "snapshot_version",
        "as_of",
        "created_at",
        "entries",
        "internal_audit_only",
        "research_only",
        "must_not_use_for_decision",
        "must_not_replace_regime",
        "must_not_publish_current",
        "must_not_execute",
        "content_hash",
    }
    if set(payload) != expected or payload["schema"] != _AUDIT_SNAPSHOT_SCHEMA:
        raise R6ActivationCorruption("R6 activation audit snapshot schema is invalid")
    raw_entries = payload["entries"]
    if not isinstance(raw_entries, list):
        raise R6ActivationCorruption("R6 activation audit snapshot entries are invalid")
    entries = tuple(_decode_audit_entry(item) for item in raw_entries)
    snapshot = _AuditSnapshot(
        snapshot_id=_require_token(payload["snapshot_id"], "audit snapshot_id"),
        snapshot_version=_require_token(payload["snapshot_version"], "audit snapshot_version"),
        as_of=_payload_datetime(payload["as_of"], "audit snapshot as_of"),
        created_at=_payload_datetime(payload["created_at"], "audit snapshot created_at"),
        entries=entries,
        internal_audit_only=_payload_bool(
            payload["internal_audit_only"],
            "audit snapshot internal_audit_only",
        ),
        research_only=_payload_bool(payload["research_only"], "audit snapshot research_only"),
        must_not_use_for_decision=_payload_bool(
            payload["must_not_use_for_decision"],
            "audit snapshot must_not_use_for_decision",
        ),
        must_not_replace_regime=_payload_bool(
            payload["must_not_replace_regime"],
            "audit snapshot must_not_replace_regime",
        ),
        must_not_publish_current=_payload_bool(
            payload["must_not_publish_current"],
            "audit snapshot must_not_publish_current",
        ),
        must_not_execute=_payload_bool(
            payload["must_not_execute"],
            "audit snapshot must_not_execute",
        ),
        content_hash=_require_hash(payload["content_hash"], "audit snapshot content_hash"),
    )
    if snapshot.as_of > snapshot.created_at:
        raise R6ActivationCorruption("R6 activation audit snapshot clocks are invalid")
    if not (
        snapshot.internal_audit_only
        and snapshot.research_only
        and snapshot.must_not_use_for_decision
        and snapshot.must_not_replace_regime
        and snapshot.must_not_publish_current
        and snapshot.must_not_execute
    ):
        raise R6ActivationCorruption("R6 activation audit snapshot safety is relaxed")
    ordering = tuple(
        (
            entry.ledger_recorded_at,
            entry.event_ref.event_id,
            entry.event_ref.event_version,
            entry.event_ref.event_hash,
        )
        for entry in entries
    )
    if ordering != tuple(sorted(ordering)) or len(ordering) != len(set(ordering)):
        raise R6ActivationCorruption("R6 activation audit snapshot ordering is invalid")
    if any(entry.ledger_recorded_at > snapshot.as_of for entry in entries):
        raise R6ActivationCorruption("R6 activation audit snapshot contains future evidence")
    expected_hash = _audit_snapshot_hash(
        snapshot_id=snapshot.snapshot_id,
        snapshot_version=snapshot.snapshot_version,
        as_of=snapshot.as_of,
        created_at=snapshot.created_at,
        entries=snapshot.entries,
    )
    if snapshot.content_hash != expected_hash:
        raise R6ActivationCorruption("R6 activation audit snapshot hash differs")
    expected_headers = _audit_snapshot_values(snapshot)
    if (
        any(
            getattr(model, key) != value
            for key, value in expected_headers.items()
            if key != "canonical_payload"
        )
        or model.canonical_payload != expected_headers["canonical_payload"]
    ):
        raise R6ActivationCorruption("R6 activation audit snapshot row header differs")
    return snapshot


def _encode_cursor(*, snapshot: _AuditSnapshot, next_offset: int) -> str:
    payload: dict[str, object] = {
        "schema": _AUDIT_CURSOR_SCHEMA,
        "snapshot_as_of": snapshot.as_of.isoformat(),
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "snapshot_hash": snapshot.content_hash,
        "next_offset": next_offset,
    }
    return signing.dumps(payload, salt=_AUDIT_CURSOR_SALT, compress=True)


def _decode_cursor(cursor: str | None) -> _AuditCursor | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
        raise ValueError("R6 activation audit cursor is invalid")
    try:
        raw_payload = signing.loads(cursor, salt=_AUDIT_CURSOR_SALT)
    except signing.BadSignature as error:
        raise ValueError("R6 activation audit cursor signature is invalid") from error
    payload = _payload_mapping(raw_payload, "audit cursor")
    expected = {
        "schema",
        "snapshot_as_of",
        "snapshot_id",
        "snapshot_version",
        "snapshot_hash",
        "next_offset",
    }
    if set(payload) != expected or payload["schema"] != _AUDIT_CURSOR_SCHEMA:
        raise ValueError("R6 activation audit cursor fields are invalid")
    try:
        snapshot_as_of = _payload_datetime(
            payload["snapshot_as_of"],
            "audit cursor snapshot_as_of",
        )
        snapshot_id = _require_token(payload["snapshot_id"], "audit cursor snapshot_id")
        snapshot_version = _require_token(
            payload["snapshot_version"],
            "audit cursor snapshot_version",
        )
        snapshot_hash = _require_hash(payload["snapshot_hash"], "audit cursor snapshot_hash")
        next_offset = _payload_int(payload["next_offset"], "audit cursor next_offset")
    except R6ActivationCorruption as error:
        raise ValueError("R6 activation audit cursor payload is invalid") from error
    if next_offset < 1:
        raise ValueError("R6 activation audit cursor offset is invalid")
    return _AuditCursor(
        snapshot_as_of=snapshot_as_of,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        snapshot_hash=snapshot_hash,
        next_offset=next_offset,
    )
