"""Fail-closed contract for DATA-01 isolated PostgreSQL restore evidence.

The parser consumes an externally produced, read-only restore snapshot.  It
does not connect to PostgreSQL, inspect a dump, or decide whether a production
maintenance window is safe.  Its only purpose is to make the source/restore
comparison and timing facts immutable and machine-checkable before they are
packaged as local evidence.
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


class Data01RestoreEvidenceError(ValueError):
    """Raised when an isolated restore snapshot is malformed or substituted."""


_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")
_PATH_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/\\-]{1,512}$")
_TABLE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_]{1,128}$")

_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "canonical_schema",
        "dump_path",
        "dump_sha256",
        "dump_sha256_after",
        "dump_sha256_before",
        "dump_size_bytes",
        "finished_at",
        "outcome",
        "pg_restore_client",
        "restore_database",
        "restore_entries",
        "restore_seconds",
        "restored_snapshot",
        "rto_seconds",
        "snapshot_difference",
        "source_database",
        "source_snapshot",
        "started_at",
        "total_seconds",
        "verification_seconds",
    }
)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    """Reject omitted and smuggled keys at every JSON boundary."""

    if frozenset(value) != expected:
        missing = sorted(expected - frozenset(value))
        extra = sorted(frozenset(value) - expected)
        raise Data01RestoreEvidenceError(
            f"{field_name} keys changed (missing={missing}, extra={extra})"
        )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow a decoded JSON object without accepting non-string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Data01RestoreEvidenceError(f"{field_name} must be an object")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    """Narrow a decoded JSON array."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise Data01RestoreEvidenceError(f"{field_name} must be an array")
    return value


def _string(value: object, field_name: str, pattern: re.Pattern[str] = _TOKEN_RE) -> str:
    """Require a bounded token from a fixed, non-secret schema field."""

    if type(value) is not str or pattern.fullmatch(value) is None:
        raise Data01RestoreEvidenceError(f"{field_name} must be a bounded token")
    return value


def _sha256(value: object, field_name: str) -> str:
    """Require a lowercase SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Data01RestoreEvidenceError(f"{field_name} must be a lowercase SHA-256")
    return value


def _positive_int(value: object, field_name: str) -> int:
    """Require a positive integer while rejecting bool-as-int values."""

    if type(value) is not int or value <= 0:
        raise Data01RestoreEvidenceError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    """Require a non-negative integer while rejecting bool-as-int values."""

    if type(value) is not int or value < 0:
        raise Data01RestoreEvidenceError(f"{field_name} must be a non-negative integer")
    return value


def _seconds(value: object, field_name: str) -> float:
    """Require a finite non-negative duration."""

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise Data01RestoreEvidenceError(f"{field_name} must be a finite duration")
    duration = float(value)
    if not math.isfinite(duration) or duration < 0:
        raise Data01RestoreEvidenceError(f"{field_name} must be a finite duration")
    return duration


def _utc(value: object, field_name: str) -> datetime:
    """Parse an aware UTC timestamp in ISO-8601 form."""

    if type(value) is not str:
        raise Data01RestoreEvidenceError(f"{field_name} must be an ISO timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise Data01RestoreEvidenceError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Data01RestoreEvidenceError(f"{field_name} must use UTC")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    """Serialize a UTC timestamp canonically."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class Data01TableSnapshot:
    """One table's row count and content digest."""

    name: str
    rows: int
    content_sha256: str

    def __post_init__(self) -> None:
        """Validate table identity and immutable comparison facts."""

        _string(self.name, "table.name", _TABLE_RE)
        _non_negative_int(self.rows, "table.rows")
        _sha256(self.content_sha256, "table.content_sha256")


@dataclass(frozen=True, slots=True)
class Data01SequenceSnapshot:
    """One PostgreSQL sequence's state."""

    name: str
    is_called: bool
    last_value: int

    def __post_init__(self) -> None:
        """Validate sequence identity and value."""

        _string(self.name, "sequence.name", _TABLE_RE)
        if type(self.is_called) is not bool:
            raise Data01RestoreEvidenceError("sequence.is_called must be bool")
        _non_negative_int(self.last_value, "sequence.last_value")


@dataclass(frozen=True, slots=True)
class Data01DatabaseSnapshot:
    """Canonical schema, migration, table and sequence snapshot."""

    data_center_migrations: tuple[str, ...]
    schema_sha256: str
    tables: tuple[Data01TableSnapshot, ...]
    sequences: tuple[Data01SequenceSnapshot, ...]

    def __post_init__(self) -> None:
        """Validate uniqueness and canonical ordering of all snapshot members."""

        if not self.data_center_migrations:
            raise Data01RestoreEvidenceError("snapshot migrations must be non-empty")
        migrations = tuple(
            _string(value, "snapshot.data_center_migrations[]")
            for value in self.data_center_migrations
        )
        if migrations != tuple(sorted(migrations)) or len(set(migrations)) != len(migrations):
            raise Data01RestoreEvidenceError("snapshot migrations must be sorted and unique")
        _sha256(self.schema_sha256, "snapshot.schema_sha256")
        if not self.tables or not self.sequences:
            raise Data01RestoreEvidenceError("snapshot tables and sequences must be non-empty")
        table_names = tuple(item.name for item in self.tables)
        sequence_names = tuple(item.name for item in self.sequences)
        if table_names != tuple(sorted(table_names)) or len(set(table_names)) != len(table_names):
            raise Data01RestoreEvidenceError("snapshot tables must be sorted and unique")
        if sequence_names != tuple(sorted(sequence_names)) or len(set(sequence_names)) != len(
            sequence_names
        ):
            raise Data01RestoreEvidenceError("snapshot sequences must be sorted and unique")


@dataclass(frozen=True, slots=True)
class Data01RestoreEvidenceReport:
    """Validated isolated restore facts; never a production readiness claim."""

    dump_path: str
    dump_sha256: str
    dump_size_bytes: int
    source_database: str
    restore_database: str
    pg_restore_client: str
    restore_entries: int
    started_at: datetime
    finished_at: datetime
    total_seconds: float
    restore_seconds: float
    rto_seconds: float
    verification_seconds: float
    source_snapshot: Data01DatabaseSnapshot
    restored_snapshot: Data01DatabaseSnapshot

    def __post_init__(self) -> None:
        """Validate timing, identity and exact source/restore equality."""

        _string(self.dump_path, "dump_path", _PATH_RE)
        _sha256(self.dump_sha256, "dump_sha256")
        _positive_int(self.dump_size_bytes, "dump_size_bytes")
        _string(self.source_database, "source_database")
        _string(self.restore_database, "restore_database")
        if self.source_database == self.restore_database:
            raise Data01RestoreEvidenceError("source and restore databases must be distinct")
        _string(self.pg_restore_client, "pg_restore_client")
        _positive_int(self.restore_entries, "restore_entries")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() != timedelta(0):
            raise Data01RestoreEvidenceError("started_at must use UTC")
        if self.finished_at.tzinfo is None or self.finished_at.utcoffset() != timedelta(0):
            raise Data01RestoreEvidenceError("finished_at must use UTC")
        if self.finished_at < self.started_at:
            raise Data01RestoreEvidenceError("finished_at precedes started_at")
        for field_name, value in (
            ("total_seconds", self.total_seconds),
            ("restore_seconds", self.restore_seconds),
            ("rto_seconds", self.rto_seconds),
            ("verification_seconds", self.verification_seconds),
        ):
            _seconds(value, field_name)
        if self.total_seconds < max(
            self.restore_seconds, self.rto_seconds, self.verification_seconds
        ):
            raise Data01RestoreEvidenceError("timing components exceed total_seconds")
        if self.source_snapshot != self.restored_snapshot:
            raise Data01RestoreEvidenceError("source and restored snapshots differ")

    @property
    def isolated_restore_verified(self) -> bool:
        """Return true for exact isolated source/restore comparison only."""

        return self.source_snapshot == self.restored_snapshot


def _parse_table_snapshots(value: object, field_name: str) -> tuple[Data01TableSnapshot, ...]:
    """Parse and canonicalize a table mapping."""

    raw = _mapping(value, field_name)
    items: list[Data01TableSnapshot] = []
    for name, item in raw.items():
        table = _mapping(item, f"{field_name}.{name}")
        _exact_keys(table, frozenset({"content_sha256", "rows"}), f"{field_name}.{name}")
        items.append(
            Data01TableSnapshot(
                name=_string(name, f"{field_name}.name", _TABLE_RE),
                rows=_non_negative_int(table["rows"], f"{field_name}.{name}.rows"),
                content_sha256=_sha256(
                    table["content_sha256"], f"{field_name}.{name}.content_sha256"
                ),
            )
        )
    return tuple(sorted(items, key=lambda item: item.name))


def _parse_sequence_snapshots(value: object, field_name: str) -> tuple[Data01SequenceSnapshot, ...]:
    """Parse and canonicalize a sequence mapping."""

    raw = _mapping(value, field_name)
    items: list[Data01SequenceSnapshot] = []
    for name, item in raw.items():
        sequence = _mapping(item, f"{field_name}.{name}")
        _exact_keys(sequence, frozenset({"is_called", "last_value"}), f"{field_name}.{name}")
        is_called = sequence["is_called"]
        if type(is_called) is not bool:
            raise Data01RestoreEvidenceError(f"{field_name}.{name}.is_called must be bool")
        items.append(
            Data01SequenceSnapshot(
                name=_string(name, f"{field_name}.name", _TABLE_RE),
                is_called=is_called,
                last_value=_non_negative_int(
                    sequence["last_value"], f"{field_name}.{name}.last_value"
                ),
            )
        )
    return tuple(sorted(items, key=lambda item: item.name))


def _parse_snapshot(value: object, field_name: str) -> Data01DatabaseSnapshot:
    """Parse one source or restored database snapshot."""

    raw = _mapping(value, field_name)
    _exact_keys(
        raw,
        frozenset({"data_center_migrations", "schema_sha256", "sequences", "tables"}),
        field_name,
    )
    migrations = tuple(
        sorted(
            _string(item, f"{field_name}.data_center_migrations[]")
            for item in _sequence(
                raw["data_center_migrations"], f"{field_name}.data_center_migrations"
            )
        )
    )
    return Data01DatabaseSnapshot(
        data_center_migrations=migrations,
        schema_sha256=_sha256(raw["schema_sha256"], f"{field_name}.schema_sha256"),
        tables=_parse_table_snapshots(raw["tables"], f"{field_name}.tables"),
        sequences=_parse_sequence_snapshots(raw["sequences"], f"{field_name}.sequences"),
    )


def parse_data01_restore_snapshot(
    payload: bytes,
    *,
    as_of: datetime | None = None,
) -> Data01RestoreEvidenceReport:
    """Parse a strict external restore snapshot without touching a database."""

    if type(payload) is not bytes or not payload:
        raise Data01RestoreEvidenceError("payload must be non-empty bytes")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Data01RestoreEvidenceError("payload must be UTF-8 JSON") from exc
    raw = _mapping(decoded, "evidence")
    _exact_keys(raw, _TOP_LEVEL_KEYS, "evidence")
    if raw["outcome"] != "success":
        raise Data01RestoreEvidenceError("restore outcome is not success")
    started_at = _utc(raw["started_at"], "started_at")
    finished_at = _utc(raw["finished_at"], "finished_at")
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(0):
        raise Data01RestoreEvidenceError("as_of must use UTC")
    if started_at > cutoff or finished_at > cutoff:
        raise Data01RestoreEvidenceError("restore evidence is from the future")
    source_snapshot = _parse_snapshot(raw["source_snapshot"], "source_snapshot")
    restored_snapshot = _parse_snapshot(raw["restored_snapshot"], "restored_snapshot")
    canonical_schema = _mapping(raw["canonical_schema"], "canonical_schema")
    _exact_keys(
        canonical_schema, frozenset({"missing_migrations", "missing_tables"}), "canonical_schema"
    )
    for key in ("missing_migrations", "missing_tables"):
        if tuple(_sequence(canonical_schema[key], f"canonical_schema.{key}")):
            raise Data01RestoreEvidenceError("canonical schema has missing objects")
    difference = _mapping(raw["snapshot_difference"], "snapshot_difference")
    _exact_keys(
        difference,
        frozenset(
            {
                "changed_sequences",
                "changed_tables",
                "extra_migrations",
                "extra_sequences",
                "extra_tables",
                "missing_migrations",
                "missing_sequences",
                "missing_tables",
                "schema_sha256",
            }
        ),
        "snapshot_difference",
    )
    for key in (
        "changed_sequences",
        "changed_tables",
        "extra_migrations",
        "extra_sequences",
        "extra_tables",
        "missing_migrations",
        "missing_sequences",
        "missing_tables",
    ):
        value = difference[key]
        if isinstance(value, Mapping) and value:
            raise Data01RestoreEvidenceError("snapshot comparison contains differences")
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) and value:
            raise Data01RestoreEvidenceError("snapshot comparison contains differences")
    if difference["schema_sha256"] is not None:
        raise Data01RestoreEvidenceError("snapshot schema digest differs")
    dump_sha_before = _sha256(raw["dump_sha256_before"], "dump_sha256_before")
    dump_sha_after = _sha256(raw["dump_sha256_after"], "dump_sha256_after")
    dump_sha = _sha256(raw["dump_sha256"], "dump_sha256")
    if not (dump_sha_before == dump_sha_after == dump_sha):
        raise Data01RestoreEvidenceError("dump SHA-256 changed during restore evidence")
    return Data01RestoreEvidenceReport(
        dump_path=_string(raw["dump_path"], "dump_path", _PATH_RE),
        dump_sha256=dump_sha,
        dump_size_bytes=_positive_int(raw["dump_size_bytes"], "dump_size_bytes"),
        source_database=_string(raw["source_database"], "source_database"),
        restore_database=_string(raw["restore_database"], "restore_database"),
        pg_restore_client=_string(raw["pg_restore_client"], "pg_restore_client"),
        restore_entries=_positive_int(raw["restore_entries"], "restore_entries"),
        started_at=started_at,
        finished_at=finished_at,
        total_seconds=_seconds(raw["total_seconds"], "total_seconds"),
        restore_seconds=_seconds(raw["restore_seconds"], "restore_seconds"),
        rto_seconds=_seconds(raw["rto_seconds"], "rto_seconds"),
        verification_seconds=_seconds(raw["verification_seconds"], "verification_seconds"),
        source_snapshot=source_snapshot,
        restored_snapshot=restored_snapshot,
    )


def _snapshot_payload(snapshot: Data01DatabaseSnapshot) -> dict[str, object]:
    """Serialize one canonical database snapshot."""

    return {
        "data_center_migrations": list(snapshot.data_center_migrations),
        "schema_sha256": snapshot.schema_sha256,
        "sequences": {
            item.name: {"is_called": item.is_called, "last_value": item.last_value}
            for item in snapshot.sequences
        },
        "tables": {
            item.name: {"content_sha256": item.content_sha256, "rows": item.rows}
            for item in snapshot.tables
        },
    }


def serialize_data01_restore_evidence(report: Data01RestoreEvidenceReport) -> bytes:
    """Serialize validated isolated restore facts into canonical evidence bytes."""

    if type(report) is not Data01RestoreEvidenceReport:
        raise Data01RestoreEvidenceError("report type is invalid")
    report.__post_init__()
    payload: dict[str, object] = {
        "artifact_type": "data01_isolated_restore_evidence",
        "backup": {
            "dump_path": report.dump_path,
            "dump_sha256": report.dump_sha256,
            "dump_size_bytes": report.dump_size_bytes,
            "pg_restore_client": report.pg_restore_client,
            "restore_entries": report.restore_entries,
        },
        "comparison": {
            "source_snapshot": _snapshot_payload(report.source_snapshot),
            "restored_snapshot": _snapshot_payload(report.restored_snapshot),
            "snapshots_equal": report.isolated_restore_verified,
        },
        "databases": {
            "restore": report.restore_database,
            "source": report.source_database,
        },
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "schema": "data01-isolated-restore-evidence.v1",
        "timing": {
            "finished_at": _utc_text(report.finished_at),
            "restore_seconds": report.restore_seconds,
            "rto_seconds": report.rto_seconds,
            "started_at": _utc_text(report.started_at),
            "total_seconds": report.total_seconds,
            "verification_seconds": report.verification_seconds,
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def data01_restore_artifact_sha256(payload: bytes) -> str:
    """Return the content address for canonical DATA-01 evidence bytes."""

    if type(payload) is not bytes or not payload:
        raise Data01RestoreEvidenceError("artifact payload must be non-empty bytes")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "Data01DatabaseSnapshot",
    "Data01RestoreEvidenceError",
    "Data01RestoreEvidenceReport",
    "Data01SequenceSnapshot",
    "Data01TableSnapshot",
    "data01_restore_artifact_sha256",
    "parse_data01_restore_snapshot",
    "serialize_data01_restore_evidence",
]
