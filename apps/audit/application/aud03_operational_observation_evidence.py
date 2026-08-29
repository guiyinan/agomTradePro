"""Fail-closed AUD-03 operational observation evidence.

This module parses externally captured, read-only operational snapshots.  It
does not query Django, claim or publish audit events, run migrations, invoke
Celery, or infer that production acceptance passed.  Every sample repeats the
immutable candidate identity, and unavailable sections remain unavailable
instead of being converted to zeroes.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final


class Aud03OperationalObservationError(ValueError):
    """Raised when an AUD-03 observation envelope is malformed."""


AUD03_REPORT_SCHEMA: Final[str] = "aud03-operational-observation-readonly.v1"
AUD03_READ_MODE: Final[str] = "select_only"
AUD03_MAX_PAYLOAD_BYTES: Final[int] = 4 * 1024 * 1024

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")
_METRIC_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_KEYS: Final[frozenset[str]] = frozenset(
    {"commit", "matrix_sha256", "oci_revision", "version"}
)
_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset({"candidate", "observations", "read_mode"})
_OBSERVATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "archive",
        "alerts",
        "candidate",
        "metrics",
        "migration",
        "observed_at",
        "outbox",
        "recovery",
        "tui",
    }
)
_MIGRATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "applied_count",
        "availability",
        "failed_count",
        "graph_sha256",
        "pending_count",
        "reason_code",
        "status",
    }
)
_OUTBOX_KEYS: Final[frozenset[str]] = frozenset(
    {
        "availability",
        "claimed_count",
        "delivered_count",
        "due_pending_count",
        "expired_claimed_count",
        "failed_count",
        "oldest_backlog_at",
        "oldest_claimed_at",
        "pending_count",
        "reason_code",
    }
)
_METRICS_KEYS: Final[frozenset[str]] = frozenset({"availability", "reason_code", "values"})
_ALERT_KEYS: Final[frozenset[str]] = frozenset(
    {"active_codes", "availability", "critical_codes", "reason_code"}
)
_TUI_KEYS: Final[frozenset[str]] = frozenset({"availability", "reason_code", "status"})
_RECOVERY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "availability",
        "completed_at",
        "duplicate_count",
        "loss_count",
        "reason_code",
        "started_at",
        "status",
    }
)
_ARCHIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "availability",
        "manifest_sha256",
        "member_count",
        "reason_code",
        "restored_sha256",
        "source_sha256",
    }
)
_FORBIDDEN_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "connection",
    "password",
    "payload",
    "private_key",
    "prompt",
    "raw",
    "secret",
    "session",
    "token",
)
_AVAILABILITY: Final[frozenset[str]] = frozenset({"available", "unavailable"})
_MIGRATION_STATUS: Final[frozenset[str]] = frozenset({"failed", "ok", "pending", "unknown"})
_TUI_STATUS: Final[frozenset[str]] = frozenset({"blocked", "error", "ok", "warning"})
_RECOVERY_STATUS: Final[frozenset[str]] = frozenset({"failed", "in_progress", "ok"})


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow a decoded JSON object and reject non-string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Aud03OperationalObservationError(f"{field_name} must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    """Reject omitted and smuggled keys at every envelope boundary."""

    actual = frozenset(value)
    if actual != expected:
        raise Aud03OperationalObservationError(
            f"{field_name} keys changed (missing={sorted(expected - actual)}, extra={sorted(actual - expected)})"
        )


def _token(value: object, field_name: str, *, pattern: re.Pattern[str] = _TOKEN_RE) -> str:
    """Require a bounded non-secret token."""

    if type(value) is not str or pattern.fullmatch(value) is None:
        raise Aud03OperationalObservationError(f"{field_name} must be a bounded token")
    return value


def _sha256(value: object, field_name: str) -> str:
    """Require a lowercase SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Aud03OperationalObservationError(f"{field_name} must be lowercase SHA-256")
    return value


def _utc(value: object, field_name: str) -> datetime:
    """Parse canonical UTC-Z text."""

    if type(value) is not str or not value.endswith("Z"):
        raise Aud03OperationalObservationError(f"{field_name} must use UTC-Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise Aud03OperationalObservationError(f"{field_name} must be ISO-8601 UTC-Z") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Aud03OperationalObservationError(f"{field_name} must use UTC-Z")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    """Serialize a timestamp in canonical UTC-Z form."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _non_negative_int(value: object, field_name: str) -> int:
    """Require an integer count without accepting booleans."""

    if type(value) is not int or value < 0:
        raise Aud03OperationalObservationError(f"{field_name} must be a non-negative integer")
    return value


def _optional_non_negative_int(value: object, field_name: str) -> int | None:
    """Allow an unavailable count only as explicit null."""

    if value is None:
        return None
    return _non_negative_int(value, field_name)


def _required_int(value: object, field_name: str) -> int:
    """Narrow an explicitly available count after null checks."""

    if value is None:
        raise Aud03OperationalObservationError(f"{field_name} is unavailable")
    return _non_negative_int(value, field_name)


def _candidate(value: object, field_name: str = "candidate") -> dict[str, str]:
    """Validate one immutable deployment candidate."""

    raw = _mapping(value, field_name)
    _exact_keys(raw, _CANDIDATE_KEYS, field_name)
    commit = raw["commit"]
    if type(commit) is not str or _COMMIT_RE.fullmatch(commit) is None:
        raise Aud03OperationalObservationError(f"{field_name}.commit must be a 40-character SHA")
    return {
        "commit": commit,
        "matrix_sha256": _sha256(raw["matrix_sha256"], f"{field_name}.matrix_sha256"),
        "oci_revision": _token(raw["oci_revision"], f"{field_name}.oci_revision"),
        "version": _token(raw["version"], f"{field_name}.version"),
    }


def _reject_forbidden_keys(value: object, path: str = "snapshot") -> None:
    """Reject raw logs and credential-shaped fields before normalization."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if type(key) is not str:
                raise Aud03OperationalObservationError(f"{path} contains a non-string key")
            lowered = key.lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise Aud03OperationalObservationError(f"forbidden field at {path}.{key}")
            _reject_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, f"{path}[{index}]")


def _availability(value: object, field_name: str) -> str:
    """Validate an explicit available/unavailable marker."""

    if type(value) is not str or value not in _AVAILABILITY:
        raise Aud03OperationalObservationError(f"{field_name} must be available or unavailable")
    return value


def _reason(value: object, field_name: str, availability: str) -> str | None:
    """Require a reason only when a section is unavailable."""

    if value is None:
        if availability == "unavailable":
            raise Aud03OperationalObservationError(f"{field_name} is required when unavailable")
        return None
    if availability == "available":
        raise Aud03OperationalObservationError(f"{field_name} must be null when available")
    return _token(value, field_name)


def _nullable_sha(value: object, field_name: str, availability: str) -> str | None:
    """Require a digest only for an available section."""

    if value is None:
        if availability == "available":
            raise Aud03OperationalObservationError(f"{field_name} is required when available")
        return None
    if availability == "unavailable":
        raise Aud03OperationalObservationError(f"{field_name} must be null when unavailable")
    return _sha256(value, field_name)


def _nullable_timestamp(
    value: object,
    field_name: str,
    *,
    availability: str,
    observed_at: datetime,
    required_when_available: bool = False,
) -> datetime | None:
    """Validate a section timestamp and preserve explicit absence."""

    if value is None:
        if availability == "available" and required_when_available:
            raise Aud03OperationalObservationError(f"{field_name} is required when available")
        if availability == "unavailable":
            return None
        return None
    if availability == "unavailable":
        raise Aud03OperationalObservationError(f"{field_name} must be null when unavailable")
    parsed = _utc(value, field_name)
    if parsed > observed_at:
        raise Aud03OperationalObservationError(f"{field_name} cannot be after observed_at")
    return parsed


def _section_base(raw: Mapping[str, object], field_name: str) -> tuple[str, str | None]:
    """Validate shared availability/reason fields."""

    availability = _availability(raw["availability"], f"{field_name}.availability")
    reason = _reason(raw["reason_code"], f"{field_name}.reason_code", availability)
    return availability, reason


def _migration(value: object, *, observed_at: datetime) -> dict[str, object]:
    """Validate migration state without accepting an unbounded command output."""

    raw = _mapping(value, "migration")
    _exact_keys(raw, _MIGRATION_KEYS, "migration")
    availability, reason = _section_base(raw, "migration")
    status = raw["status"]
    if type(status) is not str or status not in _MIGRATION_STATUS:
        raise Aud03OperationalObservationError("migration.status is invalid")
    graph = _nullable_sha(raw["graph_sha256"], "migration.graph_sha256", availability)
    counts = {
        name: _optional_non_negative_int(raw[name], f"migration.{name}")
        for name in ("applied_count", "pending_count", "failed_count")
    }
    if availability == "available":
        if any(value is None for value in counts.values()) or status == "unknown":
            raise Aud03OperationalObservationError("available migration requires complete state")
    else:
        if (
            any(value is not None for value in counts.values())
            or graph is not None
            or status != "unknown"
        ):
            raise Aud03OperationalObservationError("unavailable migration must remain unknown")
    return {
        **counts,
        "availability": availability,
        "graph_sha256": graph,
        "reason_code": reason,
        "status": status,
    }


def _outbox(value: object, *, observed_at: datetime) -> dict[str, object]:
    """Validate the credential-free outbox observation projection."""

    raw = _mapping(value, "outbox")
    _exact_keys(raw, _OUTBOX_KEYS, "outbox")
    availability, reason = _section_base(raw, "outbox")
    count_names = (
        "pending_count",
        "due_pending_count",
        "claimed_count",
        "expired_claimed_count",
        "failed_count",
        "delivered_count",
    )
    counts = {name: _optional_non_negative_int(raw[name], f"outbox.{name}") for name in count_names}
    oldest_backlog = _nullable_timestamp(
        raw["oldest_backlog_at"],
        "outbox.oldest_backlog_at",
        availability=availability,
        observed_at=observed_at,
    )
    oldest_claimed = _nullable_timestamp(
        raw["oldest_claimed_at"],
        "outbox.oldest_claimed_at",
        availability=availability,
        observed_at=observed_at,
    )
    if availability == "available":
        if any(value is None for value in counts.values()):
            raise Aud03OperationalObservationError("available outbox requires complete counts")
        due_pending_count = _required_int(counts["due_pending_count"], "outbox.due_pending_count")
        pending_count = _required_int(counts["pending_count"], "outbox.pending_count")
        expired_claimed_count = _required_int(
            counts["expired_claimed_count"], "outbox.expired_claimed_count"
        )
        claimed_count = _required_int(counts["claimed_count"], "outbox.claimed_count")
        if due_pending_count > pending_count:
            raise Aud03OperationalObservationError("outbox due_pending_count exceeds pending_count")
        if expired_claimed_count > claimed_count:
            raise Aud03OperationalObservationError(
                "outbox expired_claimed_count exceeds claimed_count"
            )
        if (pending_count + claimed_count > 0) != (oldest_backlog is not None):
            raise Aud03OperationalObservationError("outbox backlog timestamp does not match count")
        if (claimed_count > 0) != (oldest_claimed is not None):
            raise Aud03OperationalObservationError("outbox claim timestamp does not match count")
    else:
        if (
            any(value is not None for value in counts.values())
            or oldest_backlog is not None
            or oldest_claimed is not None
        ):
            raise Aud03OperationalObservationError("unavailable outbox must remain unknown")
    return {
        **counts,
        "availability": availability,
        "oldest_backlog_at": oldest_backlog,
        "oldest_claimed_at": oldest_claimed,
        "reason_code": reason,
    }


def _metrics(value: object) -> dict[str, object]:
    """Validate bounded metric values while rejecting raw telemetry blobs."""

    raw = _mapping(value, "metrics")
    _exact_keys(raw, _METRICS_KEYS, "metrics")
    availability, reason = _section_base(raw, "metrics")
    values_raw = _mapping(raw["values"], "metrics.values")
    if availability == "available" and not values_raw:
        raise Aud03OperationalObservationError("available metrics require values")
    if availability == "unavailable" and values_raw:
        raise Aud03OperationalObservationError("unavailable metrics must not carry values")
    values: dict[str, float | int] = {}
    for key, value_item in values_raw.items():
        _token(key, f"metrics.values.{key}", pattern=_METRIC_RE)
        if isinstance(value_item, bool) or not isinstance(value_item, (int, float)):
            raise Aud03OperationalObservationError(f"metrics.values.{key} must be finite numeric")
        numeric = value_item
        if not math.isfinite(float(numeric)):
            raise Aud03OperationalObservationError(f"metrics.values.{key} must be finite numeric")
        values[key] = numeric
    return {"availability": availability, "reason_code": reason, "values": values}


def _codes(value: object, field_name: str, *, availability: str) -> tuple[str, ...] | None:
    """Validate bounded, sorted alert codes."""

    if value is None:
        if availability == "available":
            raise Aud03OperationalObservationError(f"{field_name} is required when available")
        return None
    if availability == "unavailable" or not isinstance(value, list):
        raise Aud03OperationalObservationError(f"{field_name} must be a sorted array")
    codes = tuple(_token(item, f"{field_name}[]") for item in value)
    if codes != tuple(sorted(codes)) or len(set(codes)) != len(codes):
        raise Aud03OperationalObservationError(f"{field_name} must be sorted and unique")
    return codes


def _alerts(value: object) -> dict[str, object]:
    """Validate alert codes without accepting messages or raw log text."""

    raw = _mapping(value, "alerts")
    _exact_keys(raw, _ALERT_KEYS, "alerts")
    availability, reason = _section_base(raw, "alerts")
    active = _codes(raw["active_codes"], "alerts.active_codes", availability=availability)
    critical = _codes(raw["critical_codes"], "alerts.critical_codes", availability=availability)
    if availability == "available" and critical is not None and active is not None:
        if not set(critical).issubset(active):
            raise Aud03OperationalObservationError("critical alert codes must be active")
    return {
        "active_codes": active,
        "availability": availability,
        "critical_codes": critical,
        "reason_code": reason,
    }


def _tui(value: object) -> dict[str, object]:
    """Validate bounded admin TUI health status."""

    raw = _mapping(value, "tui")
    _exact_keys(raw, _TUI_KEYS, "tui")
    availability, reason = _section_base(raw, "tui")
    status = raw["status"]
    if type(status) is not str:
        raise Aud03OperationalObservationError("tui.status must be text")
    if availability == "available" and status not in _TUI_STATUS:
        raise Aud03OperationalObservationError("tui.status is invalid")
    if availability == "unavailable" and status != "unknown":
        raise Aud03OperationalObservationError("unavailable TUI status must be unknown")
    return {"availability": availability, "reason_code": reason, "status": status}


def _recovery(value: object, *, observed_at: datetime) -> dict[str, object]:
    """Validate optional recovery timeline and duplicate/loss counters."""

    raw = _mapping(value, "recovery")
    _exact_keys(raw, _RECOVERY_KEYS, "recovery")
    availability, reason = _section_base(raw, "recovery")
    status = raw["status"]
    if type(status) is not str:
        raise Aud03OperationalObservationError("recovery.status must be text")
    started = _nullable_timestamp(
        raw["started_at"],
        "recovery.started_at",
        availability=availability,
        observed_at=observed_at,
        required_when_available=True,
    )
    completed = _nullable_timestamp(
        raw["completed_at"],
        "recovery.completed_at",
        availability=availability,
        observed_at=observed_at,
    )
    duplicate_count = _optional_non_negative_int(raw["duplicate_count"], "recovery.duplicate_count")
    loss_count = _optional_non_negative_int(raw["loss_count"], "recovery.loss_count")
    if availability == "available":
        if status not in _RECOVERY_STATUS or duplicate_count is None or loss_count is None:
            raise Aud03OperationalObservationError("available recovery requires complete state")
        if status == "ok" and completed is None:
            raise Aud03OperationalObservationError("completed recovery must have completed_at")
        if status == "in_progress" and completed is not None:
            raise Aud03OperationalObservationError("in-progress recovery cannot be completed")
        if started is not None and completed is not None and completed < started:
            raise Aud03OperationalObservationError("recovery completed_at precedes started_at")
    else:
        if (
            any(value is not None for value in (started, completed, duplicate_count, loss_count))
            or status != "unknown"
        ):
            raise Aud03OperationalObservationError("unavailable recovery must remain unknown")
    return {
        "availability": availability,
        "completed_at": completed,
        "duplicate_count": duplicate_count,
        "loss_count": loss_count,
        "reason_code": reason,
        "started_at": started,
        "status": status,
    }


def _archive(value: object) -> dict[str, object]:
    """Validate archive hashes; integrity is derived from source/restore equality."""

    raw = _mapping(value, "archive")
    _exact_keys(raw, _ARCHIVE_KEYS, "archive")
    availability, reason = _section_base(raw, "archive")
    source = _nullable_sha(raw["source_sha256"], "archive.source_sha256", availability)
    restored = _nullable_sha(raw["restored_sha256"], "archive.restored_sha256", availability)
    manifest = _nullable_sha(raw["manifest_sha256"], "archive.manifest_sha256", availability)
    member_count = _optional_non_negative_int(raw["member_count"], "archive.member_count")
    if availability == "available" and member_count is None:
        raise Aud03OperationalObservationError("available archive requires member_count")
    if availability == "unavailable" and member_count is not None:
        raise Aud03OperationalObservationError("unavailable archive must not carry member_count")
    return {
        "availability": availability,
        "manifest_sha256": manifest,
        "member_count": member_count,
        "reason_code": reason,
        "restored_sha256": restored,
        "source_sha256": source,
    }


def _serialize_section(value: object) -> object:
    """Convert internal datetimes and tuples to JSON-safe values."""

    if isinstance(value, datetime):
        return _utc_text(value)
    if isinstance(value, Mapping):
        return {str(key): _serialize_section(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_serialize_section(item) for item in value]
    if isinstance(value, list):
        return [_serialize_section(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Aud03Observation:
    """One candidate-bound operational observation."""

    observed_at: datetime
    candidate: dict[str, str]
    migration: dict[str, object]
    outbox: dict[str, object]
    metrics: dict[str, object]
    alerts: dict[str, object]
    tui: dict[str, object]
    recovery: dict[str, object]
    archive: dict[str, object]


@dataclass(frozen=True, slots=True)
class Aud03OperationalObservationEvidence:
    """Canonical AUD-03 report which cannot enable production acceptance."""

    candidate: dict[str, str]
    read_mode: str
    observations: tuple[Aud03Observation, ...]

    @property
    def production_ready(self) -> bool:
        """Read-only observations never authorize migration or recovery."""

        return False

    def to_dict(self) -> dict[str, object]:
        """Return deterministic JSON-safe operational evidence."""

        first = self.observations[0].observed_at
        last = self.observations[-1].observed_at
        migration_available = [
            item.migration
            for item in self.observations
            if item.migration["availability"] == "available"
        ]
        outbox_available = [
            item.outbox for item in self.observations if item.outbox["availability"] == "available"
        ]
        metrics_available = [
            item.metrics
            for item in self.observations
            if item.metrics["availability"] == "available"
        ]
        alerts_available = [
            item.alerts for item in self.observations if item.alerts["availability"] == "available"
        ]
        recovery_available = [
            item.recovery
            for item in self.observations
            if item.recovery["availability"] == "available"
        ]
        archive_available = [
            item.archive
            for item in self.observations
            if item.archive["availability"] == "available"
        ]
        outbox_backlog = [
            _required_int(item["pending_count"], "outbox.pending_count")
            + _required_int(item["claimed_count"], "outbox.claimed_count")
            for item in outbox_available
        ]
        recovery_durations = [
            (item["completed_at"] - item["started_at"]).total_seconds()
            for item in recovery_available
            if isinstance(item["completed_at"], datetime)
            and isinstance(item["started_at"], datetime)
        ]
        archive_mismatches = sum(
            1 for item in archive_available if item["source_sha256"] != item["restored_sha256"]
        )
        missing_sections = sum(
            sum(
                1
                for section in (
                    item.migration,
                    item.outbox,
                    item.metrics,
                    item.alerts,
                    item.tui,
                    item.recovery,
                    item.archive,
                )
                if section["availability"] == "unavailable"
            )
            for item in self.observations
        )
        duplicate_count = (
            sum(
                _required_int(item["duplicate_count"], "recovery.duplicate_count")
                for item in recovery_available
            )
            if len(recovery_available) == len(self.observations)
            else None
        )
        loss_count = (
            sum(
                _required_int(item["loss_count"], "recovery.loss_count")
                for item in recovery_available
            )
            if len(recovery_available) == len(self.observations)
            else None
        )
        return {
            "candidate": dict(self.candidate),
            "checks": {
                "archive_integrity_mismatch_count": archive_mismatches,
                "alert_critical_sample_count": sum(
                    1 for item in alerts_available if item["critical_codes"]
                ),
                "migration_pending_sample_count": sum(
                    1
                    for item in migration_available
                    if _required_int(item["pending_count"], "migration.pending_count") > 0
                ),
                "missing_section_count": missing_sections,
                "outbox_recovery_sample_count": sum(
                    1
                    for item in outbox_available
                    if _required_int(item["expired_claimed_count"], "outbox.expired_claimed_count")
                    > 0
                    or _required_int(item["failed_count"], "outbox.failed_count") > 0
                ),
                "tui_issue_sample_count": sum(
                    1
                    for item in self.observations
                    if item.tui["availability"] == "available" and item.tui["status"] != "ok"
                ),
            },
            "evidence_scope": "aud03_external_operational_observation",
            "observation": {
                "first_observed_at": _utc_text(first),
                "last_observed_at": _utc_text(last),
                "observation_duration_seconds": (last - first).total_seconds(),
                "sample_count": len(self.observations),
            },
            "operational": {
                "archive_integrity_complete": len(archive_available) == len(self.observations),
                "archive_integrity_mismatch_count": archive_mismatches,
                "backlog_max_count": max(outbox_backlog) if outbox_backlog else None,
                "duplicate_count": duplicate_count,
                "metrics_available_samples": len(metrics_available),
                "migration_available_samples": len(migration_available),
                "recovery_duration_max_seconds": (
                    max(recovery_durations) if recovery_durations else None
                ),
                "recovery_available_samples": len(recovery_available),
                "loss_count": loss_count,
                "outbox_available_samples": len(outbox_available),
            },
            "production_claim": False,
            "production_ready": False,
            "read_mode": self.read_mode,
            "runtime_enablement": "not_authorized",
            "samples": [
                {
                    "archive": _serialize_section(item.archive),
                    "alerts": _serialize_section(item.alerts),
                    "candidate": dict(item.candidate),
                    "metrics": _serialize_section(item.metrics),
                    "migration": _serialize_section(item.migration),
                    "observed_at": _utc_text(item.observed_at),
                    "outbox": _serialize_section(item.outbox),
                    "recovery": _serialize_section(item.recovery),
                    "tui": _serialize_section(item.tui),
                }
                for item in self.observations
            ],
            "schema_version": AUD03_REPORT_SCHEMA,
        }


def parse_aud03_operational_observation(
    payload: bytes,
    *,
    as_of: datetime | None = None,
) -> Aud03OperationalObservationEvidence:
    """Parse external read-only operational observations without side effects."""

    if type(payload) is not bytes or not payload or len(payload) > AUD03_MAX_PAYLOAD_BYTES:
        raise Aud03OperationalObservationError("payload size is outside the allowed bound")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Aud03OperationalObservationError("payload must be UTF-8 JSON") from error
    _reject_forbidden_keys(decoded)
    raw = _mapping(decoded, "evidence")
    _exact_keys(raw, _TOP_LEVEL_KEYS, "evidence")
    if raw["read_mode"] != AUD03_READ_MODE:
        raise Aud03OperationalObservationError("read_mode must be select_only")
    candidate = _candidate(raw["candidate"])
    observations_raw = raw["observations"]
    if not isinstance(observations_raw, list) or not observations_raw:
        raise Aud03OperationalObservationError("observations must be a non-empty array")
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(0):
        raise Aud03OperationalObservationError("as_of must use UTC")
    observations: list[Aud03Observation] = []
    previous: datetime | None = None
    for index, item in enumerate(observations_raw):
        field_name = f"observations[{index}]"
        raw_observation = _mapping(item, field_name)
        _exact_keys(raw_observation, _OBSERVATION_KEYS, field_name)
        observed_at = _utc(raw_observation["observed_at"], f"{field_name}.observed_at")
        if observed_at > cutoff:
            raise Aud03OperationalObservationError(f"{field_name}.observed_at is from the future")
        if previous is not None and observed_at <= previous:
            raise Aud03OperationalObservationError("observations must be strictly chronological")
        previous = observed_at
        sample_candidate = _candidate(raw_observation["candidate"], f"{field_name}.candidate")
        if sample_candidate != candidate:
            raise Aud03OperationalObservationError("candidate drift detected across observations")
        observations.append(
            Aud03Observation(
                observed_at=observed_at,
                candidate=sample_candidate,
                migration=_migration(raw_observation["migration"], observed_at=observed_at),
                outbox=_outbox(raw_observation["outbox"], observed_at=observed_at),
                metrics=_metrics(raw_observation["metrics"]),
                alerts=_alerts(raw_observation["alerts"]),
                tui=_tui(raw_observation["tui"]),
                recovery=_recovery(raw_observation["recovery"], observed_at=observed_at),
                archive=_archive(raw_observation["archive"]),
            )
        )
    return Aud03OperationalObservationEvidence(
        candidate=candidate,
        read_mode=AUD03_READ_MODE,
        observations=tuple(observations),
    )


def serialize_aud03_operational_observation(
    report: Aud03OperationalObservationEvidence,
) -> bytes:
    """Serialize canonical AUD-03 evidence with stable JSON bytes."""

    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def aud03_operational_observation_artifact_sha256(payload: bytes) -> str:
    """Return the content address for one AUD-03 artifact."""

    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "AUD03_MAX_PAYLOAD_BYTES",
    "AUD03_READ_MODE",
    "AUD03_REPORT_SCHEMA",
    "Aud03Observation",
    "Aud03OperationalObservationError",
    "Aud03OperationalObservationEvidence",
    "aud03_operational_observation_artifact_sha256",
    "parse_aud03_operational_observation",
    "serialize_aud03_operational_observation",
]
