"""Immutable snapshot and signed cursor codec for R8 monitoring audit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast

from django.core import signing

from apps.portfolio.application.governed_optimization_monitoring_persistence import (
    GovernedOptimizationMonitoringAuditEntry,
    GovernedOptimizationMonitoringPersistenceCorruption,
    GovernedOptimizationMonitoringPersistenceUnavailable,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_codec import (
    GovernedOptimizationMonitoringCodecError,
    decode_monitoring_audit_entry,
    encode_monitoring_audit_entry,
)

_CURSOR_SALT = "apps.portfolio.governed-optimization-monitoring-audit-cursor.v1"


@dataclass(frozen=True)
class _GovernedOptimizationMonitoringAuditCursor:
    snapshot_id: str
    snapshot_version: str
    snapshot_hash: str
    snapshot_as_of: datetime
    next_offset: int


@dataclass(frozen=True)
class _GovernedOptimizationMonitoringAuditSnapshot:
    snapshot_id: str
    snapshot_version: str
    as_of: datetime
    created_at: datetime
    entries: tuple[GovernedOptimizationMonitoringAuditEntry, ...]
    content_hash: str


def create_monitoring_audit_snapshot(
    *,
    as_of: datetime,
    created_at: datetime,
    entries: tuple[GovernedOptimizationMonitoringAuditEntry, ...],
) -> _GovernedOptimizationMonitoringAuditSnapshot:
    """Create one deterministic immutable manifest from exact entries."""

    cutoff = _aware_utc(as_of, "audit snapshot as_of")
    recorded = _aware_utc(created_at, "audit snapshot created_at")
    if cutoff > recorded or not entries:
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            "R8 monitoring audit snapshot clocks are invalid"
        )
    identity: dict[str, object] = {
        "schema": "governed-optimization-monitoring-audit-snapshot-identity.v1",
        "as_of": cutoff.isoformat(),
        "created_at": recorded.isoformat(),
        "entries": [encode_monitoring_audit_entry(item) for item in entries],
    }
    snapshot_id = f"r8-monitoring-audit:{_hash_payload(identity)}"
    draft = _GovernedOptimizationMonitoringAuditSnapshot(
        snapshot_id=snapshot_id,
        snapshot_version="snapshot.v1",
        as_of=cutoff,
        created_at=recorded,
        entries=entries,
        content_hash="0" * 64,
    )
    return _GovernedOptimizationMonitoringAuditSnapshot(
        snapshot_id=draft.snapshot_id,
        snapshot_version=draft.snapshot_version,
        as_of=draft.as_of,
        created_at=draft.created_at,
        entries=draft.entries,
        content_hash=_snapshot_hash(draft),
    )


def encode_monitoring_audit_snapshot(
    snapshot: _GovernedOptimizationMonitoringAuditSnapshot,
) -> dict[str, object]:
    """Encode one snapshot with exact keys and content seal."""

    return {
        "schema": "governed-optimization-monitoring-audit-snapshot.v1",
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "as_of": _aware_utc(snapshot.as_of, "audit snapshot as_of").isoformat(),
        "created_at": _aware_utc(
            snapshot.created_at,
            "audit snapshot created_at",
        ).isoformat(),
        "entries": [encode_monitoring_audit_entry(item) for item in snapshot.entries],
        "content_hash": snapshot.content_hash,
    }


def decode_monitoring_audit_snapshot(
    payload: object,
) -> _GovernedOptimizationMonitoringAuditSnapshot:
    """Strictly restore and reseal one immutable audit snapshot."""

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
    if value["schema"] != "governed-optimization-monitoring-audit-snapshot.v1":
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            "R8 monitoring audit snapshot schema differs"
        )
    raw_entries = value["entries"]
    if type(raw_entries) is not list or not raw_entries:
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            "R8 monitoring audit entries are invalid"
        )
    try:
        entries = tuple(
            decode_monitoring_audit_entry(item) for item in cast(list[object], raw_entries)
        )
    except GovernedOptimizationMonitoringCodecError as exc:
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            "R8 monitoring audit entry payload is invalid"
        ) from exc
    snapshot = _GovernedOptimizationMonitoringAuditSnapshot(
        snapshot_id=_token(value["snapshot_id"], "snapshot_id"),
        snapshot_version=_token(value["snapshot_version"], "snapshot_version"),
        as_of=_timestamp(value["as_of"], "as_of"),
        created_at=_timestamp(value["created_at"], "created_at"),
        entries=entries,
        content_hash=_hash(value["content_hash"], "content_hash"),
    )
    if (
        snapshot.as_of > snapshot.created_at
        or snapshot.snapshot_version != "snapshot.v1"
        or _snapshot_hash(snapshot) != snapshot.content_hash
        or encode_monitoring_audit_snapshot(snapshot) != value
    ):
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            "R8 monitoring audit snapshot seal differs"
        )
    return snapshot


def encode_monitoring_audit_cursor(
    *,
    snapshot: _GovernedOptimizationMonitoringAuditSnapshot,
    next_offset: int,
) -> str:
    """Sign one exact snapshot offset with an R8-specific salt."""

    if type(next_offset) is not int or not 0 < next_offset < len(snapshot.entries):
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            "R8 monitoring audit offset is invalid"
        )
    payload = {
        "schema": "governed-optimization-monitoring-audit-cursor.v1",
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "snapshot_hash": snapshot.content_hash,
        "snapshot_as_of": snapshot.as_of.isoformat(),
        "next_offset": next_offset,
    }
    return signing.Signer(salt=_CURSOR_SALT).sign_object(payload, compress=False)


def decode_monitoring_audit_cursor(
    cursor: str | None,
) -> _GovernedOptimizationMonitoringAuditCursor | None:
    """Verify signature, exact keys, canonical encoding, and offset type."""

    if cursor is None:
        return None
    if type(cursor) is not str or not cursor or len(cursor) > 4096:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring audit cursor is invalid"
        )
    try:
        raw = signing.Signer(salt=_CURSOR_SALT).unsign_object(cursor)
    except signing.BadSignature as exc:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring audit cursor signature is invalid"
        ) from exc
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
    if value["schema"] != "governed-optimization-monitoring-audit-cursor.v1":
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring audit cursor schema differs"
        )
    result = _GovernedOptimizationMonitoringAuditCursor(
        snapshot_id=_token(value["snapshot_id"], "snapshot_id", unavailable=True),
        snapshot_version=_token(value["snapshot_version"], "snapshot_version", unavailable=True),
        snapshot_hash=_hash(value["snapshot_hash"], "snapshot_hash", unavailable=True),
        snapshot_as_of=_timestamp(value["snapshot_as_of"], "snapshot_as_of", unavailable=True),
        next_offset=_integer(value["next_offset"], "next_offset"),
    )
    if result.next_offset < 1:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring audit cursor offset is invalid"
        )
    canonical = signing.Signer(salt=_CURSOR_SALT).sign_object(
        {
            "schema": "governed-optimization-monitoring-audit-cursor.v1",
            "snapshot_id": result.snapshot_id,
            "snapshot_version": result.snapshot_version,
            "snapshot_hash": result.snapshot_hash,
            "snapshot_as_of": result.snapshot_as_of.isoformat(),
            "next_offset": result.next_offset,
        },
        compress=False,
    )
    if canonical != cursor:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring audit cursor is noncanonical"
        )
    return result


def _snapshot_hash(snapshot: _GovernedOptimizationMonitoringAuditSnapshot) -> str:
    return _hash_payload(
        {
            "schema": "governed-optimization-monitoring-audit-snapshot-content.v1",
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_version": snapshot.snapshot_version,
            "as_of": snapshot.as_of.isoformat(),
            "created_at": snapshot.created_at.isoformat(),
            "entries": [encode_monitoring_audit_entry(item) for item in snapshot.entries],
        }
    )


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _strict_object(
    value: object,
    expected: set[str],
    *,
    unavailable: bool = False,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or any(type(key) is not str for key in cast(dict[object, object], value))
        or set(cast(dict[object, object], value)) != expected
    ):
        error = (
            GovernedOptimizationMonitoringPersistenceUnavailable
            if unavailable
            else GovernedOptimizationMonitoringPersistenceCorruption
        )
        raise error("R8 monitoring audit payload keys are invalid")
    return cast(dict[str, object], value)


def _aware_utc(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise GovernedOptimizationMonitoringPersistenceCorruption(
            f"R8 monitoring {label} must be aware"
        )
    return value.astimezone(UTC)


def _timestamp(
    value: object,
    label: str,
    *,
    unavailable: bool = False,
) -> datetime:
    error = (
        GovernedOptimizationMonitoringPersistenceUnavailable
        if unavailable
        else GovernedOptimizationMonitoringPersistenceCorruption
    )
    if type(value) is not str:
        raise error(f"R8 monitoring {label} must be a timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise error(f"R8 monitoring {label} is invalid") from exc
    if (
        result.tzinfo is None
        or result.utcoffset() is None
        or result.astimezone(UTC).isoformat() != value
    ):
        raise error(f"R8 monitoring {label} is noncanonical")
    return result.astimezone(UTC)


def _token(value: object, label: str, *, unavailable: bool = False) -> str:
    error = (
        GovernedOptimizationMonitoringPersistenceUnavailable
        if unavailable
        else GovernedOptimizationMonitoringPersistenceCorruption
    )
    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise error(f"R8 monitoring {label} is invalid")
    return value


def _hash(value: object, label: str, *, unavailable: bool = False) -> str:
    error = (
        GovernedOptimizationMonitoringPersistenceUnavailable
        if unavailable
        else GovernedOptimizationMonitoringPersistenceCorruption
    )
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise error(f"R8 monitoring {label} is invalid")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            f"R8 monitoring {label} must be an exact integer"
        )
    return value


__all__: list[str] = []
