"""Stable audit snapshot and cursor codec for R7 research result lifecycle."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from django.core import signing

from apps.research.application.r7_research_result_lifecycle import (
    R7ResearchResultAuditEntry,
    R7ResultLifecycleCorruption,
)
from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleStatus,
)
from apps.research.domain.scenario_probability_contracts import ResearchEvidenceStatus
from apps.research.domain.scenario_research_hashing import require_sha256, require_token
from apps.research.infrastructure.r7_research_result_lifecycle_models import (
    R7ResearchResultAuditSnapshotModel,
)

_CURSOR_SCHEMA = "r7-result-audit-cursor.v1"
_CURSOR_SALT = "research.r7-result-audit-cursor.v1"
_SNAPSHOT_SCHEMA = "r7-result-audit-snapshot-payload.v1"
_SNAPSHOT_VERSION = "r7-result-audit-snapshot.v1"


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
    entries: tuple[R7ResearchResultAuditEntry, ...]
    internal_audit_only: bool
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool
    content_hash: str


def _create_audit_snapshot(
    *,
    as_of: datetime,
    created_at: datetime,
    entries: tuple[R7ResearchResultAuditEntry, ...],
) -> _AuditSnapshot:
    snapshot_id = f"r7-result-audit-snapshot:{uuid4()}"
    normalized_as_of = as_of.astimezone(UTC)
    normalized_created_at = created_at.astimezone(UTC)
    digest = _audit_snapshot_hash(
        snapshot_id=snapshot_id,
        snapshot_version=_SNAPSHOT_VERSION,
        as_of=normalized_as_of,
        created_at=normalized_created_at,
        entries=entries,
    )
    return _AuditSnapshot(
        snapshot_id=snapshot_id,
        snapshot_version=_SNAPSHOT_VERSION,
        as_of=normalized_as_of,
        created_at=normalized_created_at,
        entries=entries,
        internal_audit_only=True,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_execute=True,
        content_hash=digest,
    )


def _audit_snapshot_values(snapshot: _AuditSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "entry_count": len(snapshot.entries),
        "canonical_payload": _audit_snapshot_payload(snapshot),
        "internal_audit_only": snapshot.internal_audit_only,
        "research_only": snapshot.research_only,
        "must_not_use_for_decision": snapshot.must_not_use_for_decision,
        "must_not_execute": snapshot.must_not_execute,
        "content_hash": snapshot.content_hash,
    }


def _audit_snapshot_payload(snapshot: _AuditSnapshot) -> dict[str, object]:
    return {
        "schema": _SNAPSHOT_SCHEMA,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of.astimezone(UTC).isoformat(),
        "created_at": snapshot.created_at.astimezone(UTC).isoformat(),
        "entries": [_encode_audit_entry(entry) for entry in snapshot.entries],
        "internal_audit_only": snapshot.internal_audit_only,
        "research_only": snapshot.research_only,
        "must_not_use_for_decision": snapshot.must_not_use_for_decision,
        "must_not_execute": snapshot.must_not_execute,
        "content_hash": snapshot.content_hash,
    }


def _restore_audit_snapshot(model: R7ResearchResultAuditSnapshotModel) -> _AuditSnapshot:
    payload = _payload_mapping(model.canonical_payload, "audit snapshot")
    expected_keys = {
        "schema",
        "snapshot_id",
        "snapshot_version",
        "as_of",
        "created_at",
        "entries",
        "internal_audit_only",
        "research_only",
        "must_not_use_for_decision",
        "must_not_execute",
        "content_hash",
    }
    if set(payload) != expected_keys or payload["schema"] != _SNAPSHOT_SCHEMA:
        raise R7ResultLifecycleCorruption("R7 audit snapshot payload schema is invalid")
    raw_entries = payload["entries"]
    if not isinstance(raw_entries, list):
        raise R7ResultLifecycleCorruption("R7 audit snapshot entries are invalid")
    entries = tuple(_decode_audit_entry(item) for item in raw_entries)
    snapshot = _AuditSnapshot(
        snapshot_id=_payload_string(payload, "snapshot_id"),
        snapshot_version=_payload_string(payload, "snapshot_version"),
        as_of=_payload_datetime(payload, "as_of"),
        created_at=_payload_datetime(payload, "created_at"),
        entries=entries,
        internal_audit_only=_payload_bool(payload, "internal_audit_only"),
        research_only=_payload_bool(payload, "research_only"),
        must_not_use_for_decision=_payload_bool(payload, "must_not_use_for_decision"),
        must_not_execute=_payload_bool(payload, "must_not_execute"),
        content_hash=_payload_string(payload, "content_hash"),
    )
    require_token(snapshot.snapshot_id, "R7 audit snapshot_id", maximum=192)
    require_token(snapshot.snapshot_version, "R7 audit snapshot_version", maximum=192)
    require_sha256(snapshot.content_hash, "R7 audit snapshot content_hash")
    if snapshot.as_of > snapshot.created_at:
        raise R7ResultLifecycleCorruption("R7 audit snapshot clocks are invalid")
    if not (
        snapshot.internal_audit_only
        and snapshot.research_only
        and snapshot.must_not_use_for_decision
        and snapshot.must_not_execute
    ):
        raise R7ResultLifecycleCorruption("R7 audit snapshot safety is relaxed")
    ordering = tuple(
        (entry.recorded_at, entry.result_ref.result_id, entry.result_ref.result_version)
        for entry in snapshot.entries
    )
    if ordering != tuple(sorted(ordering)) or len(ordering) != len(set(ordering)):
        raise R7ResultLifecycleCorruption("R7 audit snapshot ordering is invalid")
    if any(entry.recorded_at > snapshot.as_of for entry in snapshot.entries):
        raise R7ResultLifecycleCorruption("R7 audit snapshot contains future results")
    expected_hash = _audit_snapshot_hash(
        snapshot_id=snapshot.snapshot_id,
        snapshot_version=snapshot.snapshot_version,
        as_of=snapshot.as_of,
        created_at=snapshot.created_at,
        entries=snapshot.entries,
    )
    if snapshot.content_hash != expected_hash:
        raise R7ResultLifecycleCorruption("R7 audit snapshot content_hash mismatch")
    model_headers = (
        model.snapshot_id,
        model.snapshot_version,
        model.as_of,
        model.created_at,
        model.entry_count,
        model.internal_audit_only,
        model.research_only,
        model.must_not_use_for_decision,
        model.must_not_execute,
        model.content_hash,
    )
    snapshot_headers = (
        snapshot.snapshot_id,
        snapshot.snapshot_version,
        snapshot.as_of,
        snapshot.created_at,
        len(snapshot.entries),
        snapshot.internal_audit_only,
        snapshot.research_only,
        snapshot.must_not_use_for_decision,
        snapshot.must_not_execute,
        snapshot.content_hash,
    )
    if model_headers != snapshot_headers:
        raise R7ResultLifecycleCorruption("R7 audit snapshot header mismatch")
    return snapshot


def _audit_snapshot_hash(
    *,
    snapshot_id: str,
    snapshot_version: str,
    as_of: datetime,
    created_at: datetime,
    entries: tuple[R7ResearchResultAuditEntry, ...],
) -> str:
    body: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "snapshot_version": snapshot_version,
        "as_of": as_of.astimezone(UTC).isoformat(),
        "created_at": created_at.astimezone(UTC).isoformat(),
        "entries": [_encode_audit_entry(entry) for entry in entries],
        "internal_audit_only": True,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    return sha256(_canonical_json(body).encode()).hexdigest()


def _encode_audit_entry(entry: R7ResearchResultAuditEntry) -> dict[str, object]:
    return {
        "result_id": entry.result_ref.result_id,
        "result_version": entry.result_ref.result_version,
        "result_content_hash": entry.result_ref.content_hash,
        "policy_id": entry.policy_id,
        "policy_version": entry.policy_version,
        "policy_record_hash": entry.policy_record_hash,
        "scope_content_hash": entry.scope_content_hash,
        "evaluated_at": entry.evaluated_at.astimezone(UTC).isoformat(),
        "recorded_at": entry.recorded_at.astimezone(UTC).isoformat(),
        "result_persisted_at": entry.result_persisted_at.astimezone(UTC).isoformat(),
        "subjective_calibration_status": entry.subjective_calibration_status.value,
        "model_inferred_calibration_status": entry.model_inferred_calibration_status.value,
        "historical_analogy_status": entry.historical_analogy_status.value,
        "path_research_status": entry.path_research_status.value,
        "blocker_codes": list(entry.blocker_codes),
        "lifecycle_status": entry.lifecycle_status.value,
        "lifecycle_sequence": entry.lifecycle_sequence,
        "head_event_hash": entry.head_event_hash,
        "promoted_at": _optional_clock(entry.promoted_at),
        "retired_at": _optional_clock(entry.retired_at),
        "research_only": entry.research_only,
        "must_not_use_for_decision": entry.must_not_use_for_decision,
        "must_not_execute": entry.must_not_execute,
    }


def _decode_audit_entry(payload: object) -> R7ResearchResultAuditEntry:
    mapping = _payload_mapping(payload, "audit snapshot entry")
    expected_keys = {
        "result_id",
        "result_version",
        "result_content_hash",
        "policy_id",
        "policy_version",
        "policy_record_hash",
        "scope_content_hash",
        "evaluated_at",
        "recorded_at",
        "result_persisted_at",
        "subjective_calibration_status",
        "model_inferred_calibration_status",
        "historical_analogy_status",
        "path_research_status",
        "blocker_codes",
        "lifecycle_status",
        "lifecycle_sequence",
        "head_event_hash",
        "promoted_at",
        "retired_at",
        "research_only",
        "must_not_use_for_decision",
        "must_not_execute",
    }
    if set(mapping) != expected_keys:
        raise R7ResultLifecycleCorruption("R7 audit snapshot entry fields are invalid")
    result_ref = R7ResearchResultRef(
        _payload_string(mapping, "result_id"),
        _payload_string(mapping, "result_version"),
        _payload_string(mapping, "result_content_hash"),
    )
    policy_id = _payload_string(mapping, "policy_id")
    policy_version = _payload_string(mapping, "policy_version")
    policy_hash = _payload_string(mapping, "policy_record_hash")
    scope_hash = _payload_string(mapping, "scope_content_hash")
    require_token(policy_id, "R7 audit policy_id", maximum=192)
    require_token(policy_version, "R7 audit policy_version", maximum=192)
    require_sha256(policy_hash, "R7 audit policy_record_hash")
    require_sha256(scope_hash, "R7 audit scope_content_hash")
    raw_blockers = mapping["blocker_codes"]
    if not isinstance(raw_blockers, list) or any(
        not isinstance(item, str) for item in raw_blockers
    ):
        raise R7ResultLifecycleCorruption("R7 audit blocker codes are invalid")
    blocker_codes = tuple(raw_blockers)
    if blocker_codes != tuple(sorted(set(blocker_codes))):
        raise R7ResultLifecycleCorruption("R7 audit blocker codes are noncanonical")
    for blocker_code in blocker_codes:
        require_token(blocker_code, "R7 audit blocker code", maximum=192)
    head_hash = _payload_optional_string(mapping, "head_event_hash")
    if head_hash is not None:
        require_sha256(head_hash, "R7 audit head_event_hash")
    try:
        entry = R7ResearchResultAuditEntry(
            result_ref=result_ref,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_record_hash=policy_hash,
            scope_content_hash=scope_hash,
            evaluated_at=_payload_datetime(mapping, "evaluated_at"),
            recorded_at=_payload_datetime(mapping, "recorded_at"),
            result_persisted_at=_payload_datetime(mapping, "result_persisted_at"),
            subjective_calibration_status=ResearchEvidenceStatus(
                _payload_string(mapping, "subjective_calibration_status")
            ),
            model_inferred_calibration_status=ResearchEvidenceStatus(
                _payload_string(mapping, "model_inferred_calibration_status")
            ),
            historical_analogy_status=ResearchEvidenceStatus(
                _payload_string(mapping, "historical_analogy_status")
            ),
            path_research_status=ResearchEvidenceStatus(
                _payload_string(mapping, "path_research_status")
            ),
            blocker_codes=blocker_codes,
            lifecycle_status=R7ResultLifecycleStatus(_payload_string(mapping, "lifecycle_status")),
            lifecycle_sequence=_payload_int(mapping, "lifecycle_sequence"),
            head_event_hash=head_hash,
            promoted_at=_payload_optional_datetime(mapping, "promoted_at"),
            retired_at=_payload_optional_datetime(mapping, "retired_at"),
            research_only=_payload_bool(mapping, "research_only"),
            must_not_use_for_decision=_payload_bool(mapping, "must_not_use_for_decision"),
            must_not_execute=_payload_bool(mapping, "must_not_execute"),
        )
    except ValueError as error:
        raise R7ResultLifecycleCorruption("R7 audit snapshot entry is invalid") from error
    _validate_audit_entry(entry)
    return entry


def _validate_audit_entry(entry: R7ResearchResultAuditEntry) -> None:
    if entry.evaluated_at > entry.recorded_at:
        raise R7ResultLifecycleCorruption("R7 audit entry clocks are invalid")
    if not (entry.research_only and entry.must_not_use_for_decision and entry.must_not_execute):
        raise R7ResultLifecycleCorruption("R7 audit entry safety is relaxed")
    if entry.lifecycle_status is R7ResultLifecycleStatus.UNPROMOTED:
        valid = (
            entry.lifecycle_sequence == 0
            and entry.head_event_hash is None
            and entry.promoted_at is None
            and entry.retired_at is None
        )
    elif entry.lifecycle_status is R7ResultLifecycleStatus.PROMOTED:
        valid = (
            entry.lifecycle_sequence >= 1
            and entry.head_event_hash is not None
            and entry.promoted_at is not None
            and entry.retired_at is None
        )
    else:
        valid = (
            entry.lifecycle_sequence >= 2
            and entry.head_event_hash is not None
            and entry.promoted_at is not None
            and entry.retired_at is not None
        )
    if not valid:
        raise R7ResultLifecycleCorruption("R7 audit lifecycle projection is invalid")


def _encode_cursor(*, snapshot: _AuditSnapshot, next_offset: int) -> str:
    body: dict[str, object] = {
        "schema": _CURSOR_SCHEMA,
        "snapshot_as_of": snapshot.as_of.astimezone(UTC).isoformat(),
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "snapshot_hash": snapshot.content_hash,
        "next_offset": next_offset,
    }
    return signing.dumps(body, salt=_CURSOR_SALT, compress=True)


def _decode_cursor(cursor: str | None) -> _AuditCursor | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
        raise ValueError("R7 result audit cursor is invalid")
    try:
        payload = signing.loads(cursor, salt=_CURSOR_SALT)
    except signing.BadSignature as error:
        raise ValueError("R7 result audit cursor signature is invalid") from error
    mapping = _payload_mapping(payload, "audit cursor")
    if (
        set(mapping)
        != {
            "schema",
            "snapshot_as_of",
            "snapshot_id",
            "snapshot_version",
            "snapshot_hash",
            "next_offset",
        }
        or mapping["schema"] != _CURSOR_SCHEMA
    ):
        raise ValueError("R7 result audit cursor fields are invalid")
    snapshot_id = _payload_string(mapping, "snapshot_id")
    snapshot_version = _payload_string(mapping, "snapshot_version")
    snapshot_hash = _payload_string(mapping, "snapshot_hash")
    require_token(snapshot_id, "R7 audit cursor snapshot_id", maximum=192)
    require_token(snapshot_version, "R7 audit cursor snapshot_version", maximum=192)
    require_sha256(snapshot_hash, "R7 audit cursor snapshot_hash")
    next_offset = _payload_int(mapping, "next_offset")
    if next_offset < 1:
        raise ValueError("R7 result audit cursor offset is invalid")
    return _AuditCursor(
        snapshot_as_of=_payload_datetime(mapping, "snapshot_as_of"),
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        snapshot_hash=snapshot_hash,
        next_offset=next_offset,
    )


def _payload_mapping(payload: object, label: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
        raise R7ResultLifecycleCorruption(f"R7 {label} must be a mapping")
    return payload


def _payload_string(mapping: Mapping[str, object], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str):
        raise R7ResultLifecycleCorruption(f"R7 audit {key} must be a string")
    return value


def _payload_optional_string(mapping: Mapping[str, object], key: str) -> str | None:
    value = mapping[key]
    if value is not None and not isinstance(value, str):
        raise R7ResultLifecycleCorruption(f"R7 audit {key} is invalid")
    return value


def _payload_bool(mapping: Mapping[str, object], key: str) -> bool:
    value = mapping[key]
    if not isinstance(value, bool):
        raise R7ResultLifecycleCorruption(f"R7 audit {key} must be boolean")
    return value


def _payload_int(mapping: Mapping[str, object], key: str) -> int:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise R7ResultLifecycleCorruption(f"R7 audit {key} must be non-negative")
    return value


def _payload_datetime(mapping: Mapping[str, object], key: str) -> datetime:
    return _decode_datetime(_payload_string(mapping, key), key)


def _payload_optional_datetime(mapping: Mapping[str, object], key: str) -> datetime | None:
    raw = _payload_optional_string(mapping, key)
    return _decode_datetime(raw, key) if raw is not None else None


def _optional_clock(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _decode_datetime(raw: str, label: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise R7ResultLifecycleCorruption(f"R7 audit {label} clock is invalid") from error
    if (
        value.tzinfo is None
        or value.utcoffset() is None
        or value.astimezone(UTC).isoformat() != raw
    ):
        raise R7ResultLifecycleCorruption(f"R7 audit {label} clock is noncanonical")
    return value


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
