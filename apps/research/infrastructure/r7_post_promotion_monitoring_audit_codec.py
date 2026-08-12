"""Immutable snapshot and signed cursor codec for R7 monitoring audit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from django.core import signing

from apps.research.application.r7_post_promotion_monitoring_persistence import (
    R7MonitoringAssessmentRef,
    R7MonitoringAuditEntry,
    R7MonitoringPersistenceCorruption,
    R7MonitoringPersistenceUnavailable,
)
from apps.research.domain.r7_post_promotion_monitoring import R7MonitoringStatus

_CURSOR_SALT = "apps.research.r7-monitoring-audit-cursor.v1"


@dataclass(frozen=True)
class _R7MonitoringAuditCursor:
    snapshot_id: str
    snapshot_version: str
    snapshot_hash: str
    snapshot_as_of: datetime
    next_offset: int


@dataclass(frozen=True)
class _R7MonitoringAuditSnapshot:
    snapshot_id: str
    snapshot_version: str
    as_of: datetime
    created_at: datetime
    entries: tuple[R7MonitoringAuditEntry, ...]
    content_hash: str


def create_r7_monitoring_audit_snapshot(
    *,
    as_of: datetime,
    created_at: datetime,
    entries: tuple[R7MonitoringAuditEntry, ...],
) -> _R7MonitoringAuditSnapshot:
    """Create one deterministic immutable manifest from exact audit entries."""

    cutoff = _aware(as_of, "audit snapshot as_of")
    recorded = _aware(created_at, "audit snapshot created_at")
    if cutoff > recorded or not entries:
        raise R7MonitoringPersistenceCorruption(
            "R7 monitoring audit snapshot clocks or entries are invalid"
        )
    identity: dict[str, object] = {
        "schema": "research-r7-monitoring-audit-snapshot-identity.v1",
        "as_of": cutoff.isoformat(),
        "created_at": recorded.isoformat(),
        "entries": [encode_r7_monitoring_audit_entry(item) for item in entries],
    }
    snapshot_id = f"r7-monitoring-audit:{_hash_payload(identity)}"
    draft = _R7MonitoringAuditSnapshot(
        snapshot_id=snapshot_id,
        snapshot_version="snapshot.v1",
        as_of=cutoff,
        created_at=recorded,
        entries=entries,
        content_hash="0" * 64,
    )
    return _R7MonitoringAuditSnapshot(
        snapshot_id=draft.snapshot_id,
        snapshot_version=draft.snapshot_version,
        as_of=draft.as_of,
        created_at=draft.created_at,
        entries=draft.entries,
        content_hash=_snapshot_hash(draft),
    )


def encode_r7_monitoring_audit_entry(
    entry: R7MonitoringAuditEntry,
) -> dict[str, object]:
    """Encode one exact research-only audit projection."""

    if type(entry) is not R7MonitoringAuditEntry:
        raise R7MonitoringPersistenceCorruption("R7 monitoring audit entry type differs")
    return {
        "assessment_id": entry.reference.assessment_id,
        "assessment_version": entry.reference.assessment_version,
        "content_hash": entry.reference.content_hash,
        "policy_id": entry.policy_id,
        "policy_version": entry.policy_version,
        "result_id": entry.result_id,
        "result_hash": entry.result_hash,
        "period_id": entry.period_id,
        "evaluated_at": _aware(entry.evaluated_at, "evaluated_at").isoformat(),
        "ledger_recorded_at": _aware(
            entry.ledger_recorded_at,
            "ledger_recorded_at",
        ).isoformat(),
        "status": entry.status.value,
        "observation_count": entry.observation_count,
        "blocker_codes": list(entry.blocker_codes),
        "manual_retirement_review_required": (entry.manual_retirement_review_required),
    }


def decode_r7_monitoring_audit_entry(payload: object) -> R7MonitoringAuditEntry:
    """Strictly restore one audit entry and its exact reference."""

    value = _strict_object(
        payload,
        {
            "assessment_id",
            "assessment_version",
            "content_hash",
            "policy_id",
            "policy_version",
            "result_id",
            "result_hash",
            "period_id",
            "evaluated_at",
            "ledger_recorded_at",
            "status",
            "observation_count",
            "blocker_codes",
            "manual_retirement_review_required",
        },
    )
    blockers = value["blocker_codes"]
    if not isinstance(blockers, list) or any(type(item) is not str for item in blockers):
        raise R7MonitoringPersistenceCorruption("R7 monitoring audit blockers are invalid")
    try:
        entry = R7MonitoringAuditEntry(
            reference=R7MonitoringAssessmentRef(
                assessment_id=_token(value["assessment_id"], "assessment_id"),
                assessment_version=_token(
                    value["assessment_version"],
                    "assessment_version",
                ),
                content_hash=_hash(value["content_hash"], "content_hash"),
            ),
            policy_id=_token(value["policy_id"], "policy_id"),
            policy_version=_token(value["policy_version"], "policy_version"),
            result_id=_token(value["result_id"], "result_id"),
            result_hash=_hash(value["result_hash"], "result_hash"),
            period_id=_token(value["period_id"], "period_id"),
            evaluated_at=_datetime(value["evaluated_at"], "evaluated_at"),
            ledger_recorded_at=_datetime(
                value["ledger_recorded_at"],
                "ledger_recorded_at",
            ),
            status=R7MonitoringStatus(_token(value["status"], "status")),
            observation_count=_integer(
                value["observation_count"],
                "observation_count",
            ),
            blocker_codes=tuple(blockers),
            manual_retirement_review_required=_boolean(
                value["manual_retirement_review_required"],
                "manual_retirement_review_required",
            ),
        )
    except (TypeError, ValueError) as error:
        raise R7MonitoringPersistenceCorruption("R7 monitoring audit entry is invalid") from error
    if encode_r7_monitoring_audit_entry(entry) != value:
        raise R7MonitoringPersistenceCorruption("R7 monitoring audit entry is non-canonical")
    return entry


def encode_r7_monitoring_audit_snapshot(
    snapshot: _R7MonitoringAuditSnapshot,
) -> dict[str, object]:
    """Encode one snapshot with exact keys and its content seal."""

    return {
        "schema": "research-r7-monitoring-audit-snapshot.v1",
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": snapshot.as_of.isoformat(),
        "created_at": snapshot.created_at.isoformat(),
        "entries": [encode_r7_monitoring_audit_entry(item) for item in snapshot.entries],
        "content_hash": snapshot.content_hash,
    }


def decode_r7_monitoring_audit_snapshot(
    payload: object,
) -> _R7MonitoringAuditSnapshot:
    """Strictly restore and reseal an immutable snapshot."""

    value = _strict_object(
        payload,
        {
            "schema",
            "snapshot_id",
            "snapshot_version",
            "as_of",
            "created_at",
            "entries",
            "content_hash",
        },
    )
    if value["schema"] != "research-r7-monitoring-audit-snapshot.v1":
        raise R7MonitoringPersistenceCorruption("R7 monitoring audit snapshot schema differs")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise R7MonitoringPersistenceCorruption("R7 monitoring audit entries are invalid")
    snapshot = _R7MonitoringAuditSnapshot(
        snapshot_id=_token(value["snapshot_id"], "snapshot_id"),
        snapshot_version=_token(value["snapshot_version"], "snapshot_version"),
        as_of=_datetime(value["as_of"], "as_of"),
        created_at=_datetime(value["created_at"], "created_at"),
        entries=tuple(decode_r7_monitoring_audit_entry(item) for item in raw_entries),
        content_hash=_hash(value["content_hash"], "content_hash"),
    )
    if (
        snapshot.as_of > snapshot.created_at
        or snapshot.snapshot_version != "snapshot.v1"
        or snapshot.content_hash != _snapshot_hash(snapshot)
        or encode_r7_monitoring_audit_snapshot(snapshot) != value
    ):
        raise R7MonitoringPersistenceCorruption("R7 monitoring audit snapshot seal differs")
    return snapshot


def encode_r7_monitoring_audit_cursor(
    *,
    snapshot: _R7MonitoringAuditSnapshot,
    next_offset: int,
) -> str:
    """Sign one exact snapshot offset with an R7-specific salt."""

    if type(next_offset) is not int or not 0 < next_offset < len(snapshot.entries):
        raise R7MonitoringPersistenceCorruption("R7 monitoring audit offset is invalid")
    payload = {
        "schema": "research-r7-monitoring-audit-cursor.v1",
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "snapshot_hash": snapshot.content_hash,
        "snapshot_as_of": snapshot.as_of.isoformat(),
        "next_offset": next_offset,
    }
    return signing.Signer(salt=_CURSOR_SALT).sign_object(payload, compress=False)


def decode_r7_monitoring_audit_cursor(
    cursor: str | None,
) -> _R7MonitoringAuditCursor | None:
    """Verify signature, exact keys, canonical encoding, and offset type."""

    if cursor is None:
        return None
    if type(cursor) is not str or not cursor or len(cursor) > 4096:
        raise R7MonitoringPersistenceUnavailable("R7 monitoring audit cursor is invalid")
    try:
        raw = signing.Signer(salt=_CURSOR_SALT).unsign_object(cursor)
    except signing.BadSignature as error:
        raise R7MonitoringPersistenceUnavailable(
            "R7 monitoring audit cursor signature is invalid"
        ) from error
    value = _strict_object(
        raw,
        {
            "schema",
            "snapshot_id",
            "snapshot_version",
            "snapshot_hash",
            "snapshot_as_of",
            "next_offset",
        },
        unavailable=True,
    )
    if value["schema"] != "research-r7-monitoring-audit-cursor.v1":
        raise R7MonitoringPersistenceUnavailable("R7 monitoring audit cursor schema differs")
    result = _R7MonitoringAuditCursor(
        snapshot_id=_token(value["snapshot_id"], "snapshot_id", unavailable=True),
        snapshot_version=_token(
            value["snapshot_version"],
            "snapshot_version",
            unavailable=True,
        ),
        snapshot_hash=_hash(
            value["snapshot_hash"],
            "snapshot_hash",
            unavailable=True,
        ),
        snapshot_as_of=_datetime(
            value["snapshot_as_of"],
            "snapshot_as_of",
            unavailable=True,
        ),
        next_offset=_integer(
            value["next_offset"],
            "next_offset",
            unavailable=True,
        ),
    )
    if result.next_offset < 1:
        raise R7MonitoringPersistenceUnavailable("R7 monitoring audit cursor offset is invalid")
    canonical = signing.Signer(salt=_CURSOR_SALT).sign_object(
        {
            "schema": "research-r7-monitoring-audit-cursor.v1",
            "snapshot_id": result.snapshot_id,
            "snapshot_version": result.snapshot_version,
            "snapshot_hash": result.snapshot_hash,
            "snapshot_as_of": result.snapshot_as_of.isoformat(),
            "next_offset": result.next_offset,
        },
        compress=False,
    )
    if canonical != cursor:
        raise R7MonitoringPersistenceUnavailable("R7 monitoring audit cursor is non-canonical")
    return result


def _snapshot_hash(snapshot: _R7MonitoringAuditSnapshot) -> str:
    return _hash_payload(
        {
            "schema": "research-r7-monitoring-audit-snapshot-content.v1",
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_version": snapshot.snapshot_version,
            "as_of": snapshot.as_of.isoformat(),
            "created_at": snapshot.created_at.isoformat(),
            "entries": [encode_r7_monitoring_audit_entry(item) for item in snapshot.entries],
        }
    )


def _hash_payload(payload: dict[str, object]) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _strict_object(
    value: object,
    expected: set[str],
    *,
    unavailable: bool = False,
) -> dict[str, object]:
    error_type = (
        R7MonitoringPersistenceUnavailable if unavailable else R7MonitoringPersistenceCorruption
    )
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise error_type("R7 monitoring audit payload must be an object")
    if set(value) != expected:
        raise error_type("R7 monitoring audit payload fields differ")
    return value


def _token(value: object, label: str, *, unavailable: bool = False) -> str:
    error_type = (
        R7MonitoringPersistenceUnavailable if unavailable else R7MonitoringPersistenceCorruption
    )
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 300
        or any(character.isspace() for character in value)
    ):
        raise error_type(f"R7 monitoring audit {label} is invalid")
    return value


def _hash(value: object, label: str, *, unavailable: bool = False) -> str:
    error_type = (
        R7MonitoringPersistenceUnavailable if unavailable else R7MonitoringPersistenceCorruption
    )
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise error_type(f"R7 monitoring audit {label} is invalid")
    return value


def _datetime(value: object, label: str, *, unavailable: bool = False) -> datetime:
    error_type = (
        R7MonitoringPersistenceUnavailable if unavailable else R7MonitoringPersistenceCorruption
    )
    if type(value) is not str:
        raise error_type(f"R7 monitoring audit {label} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise error_type(f"R7 monitoring audit {label} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.isoformat() != value:
        raise error_type(f"R7 monitoring audit {label} is invalid")
    return parsed


def _integer(value: object, label: str, *, unavailable: bool = False) -> int:
    error_type = (
        R7MonitoringPersistenceUnavailable if unavailable else R7MonitoringPersistenceCorruption
    )
    if type(value) is not int or value < 0:
        raise error_type(f"R7 monitoring audit {label} is invalid")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise R7MonitoringPersistenceCorruption(f"R7 monitoring audit {label} is invalid")
    return value


def _aware(value: datetime, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R7MonitoringPersistenceCorruption(f"R7 monitoring audit {label} is invalid")
    return value


__all__ = [
    "create_r7_monitoring_audit_snapshot",
    "decode_r7_monitoring_audit_cursor",
    "decode_r7_monitoring_audit_snapshot",
    "encode_r7_monitoring_audit_cursor",
    "encode_r7_monitoring_audit_snapshot",
]
