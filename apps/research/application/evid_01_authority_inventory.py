"""Strict, read-only EVID-01 authority inventory evidence contract.

The contract consumes an externally captured PostgreSQL inventory only.  It
does not connect to a database, inspect Django users, create authority rows,
or infer an owner/tenant authority from mutable application state.  Every
report is deliberately non-production and keeps runtime enablement disabled.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, cast

EVID_01_INVENTORY_INPUT_FORMAT: Final[str] = "evid-01-authority-inventory-snapshot.v1"
EVID_01_INVENTORY_REPORT_FORMAT: Final[str] = "evid-01-authority-inventory-report.v1"
EVID_01_INVENTORY_ENVIRONMENT: Final[str] = "production"
EVID_01_INVENTORY_BACKEND: Final[str] = "postgresql"
EVID_01_INVENTORY_SCHEMA: Final[str] = "public"
EVID_01_INVENTORY_MIGRATIONS: Final[tuple[str, ...]] = (
    "0050_account_owner_assignment_evidence_v3_ledgers",
    "0051_actor_authority_source_v3_ledgers",
    "0052_account_actor_authority_raw_source_v3_ledgers",
    "0053_account_rbac_authority_mutation_binding_v3",
)
EVID_01_INVENTORY_TABLES: Final[tuple[str, ...]] = (
    "account_auth_context_source_v3_anchor",
    "account_auth_context_source_v3_ledger",
    "account_user_authority_source_v3_anchor",
    "account_user_authority_source_v3_ledger",
    "account_rbac_authority_source_v3_anchor",
    "account_rbac_authority_source_v3_ledger",
    "account_actor_authority_source_v3_root_lock",
    "account_actor_authority_source_v3_ledger",
    "research_evidence_scope_source_v1",
    "account_owner_assignment_subject_v3_ledger",
    "account_owner_assignment_evidence_v3_ledger",
    "account_owner_assignment_provenance_receipt_v3_ledger",
)

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_UTC_TEXT_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_FORBIDDEN_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "session",
    "token",
)
_MAX_PAYLOAD_BYTES: Final[int] = 2 * 1024 * 1024


class Evid01AuthorityInventoryError(ValueError):
    """Raised when an inventory snapshot is not a strict canonical payload."""


class Evid01AuthorityInventoryOutcome(StrEnum):
    """Derived, fail-closed inventory outcomes."""

    BLOCKED_ZERO_SEED_AUTHORITY = "blocked_zero_seed_authority"
    BLOCKED_UNVERIFIED_AUTHORITY = "blocked_unverified_authority"


@dataclass(frozen=True, slots=True)
class Evid01InventoryCandidate:
    """Immutable candidate identity captured with the inventory."""

    stable_version: str
    source_commit: str
    release: str

    def __post_init__(self) -> None:
        _token(self.stable_version, "candidate.stable_version")
        _commit(self.source_commit, "candidate.source_commit")
        _token(self.release, "candidate.release")


@dataclass(frozen=True, slots=True)
class Evid01InventoryMigration:
    """One account migration state observation."""

    app: str
    name: str
    applied_at: datetime

    def __post_init__(self) -> None:
        if self.app != "account":
            raise Evid01AuthorityInventoryError("migration app must be account")
        if self.name not in EVID_01_INVENTORY_MIGRATIONS:
            raise Evid01AuthorityInventoryError("migration name is not canonical")
        _utc(self.applied_at, "migration.applied_at")


@dataclass(frozen=True, slots=True)
class Evid01InventoryDatabase:
    """Database backend, schema, and required migration observations."""

    backend: str
    schema: str
    migrations: tuple[Evid01InventoryMigration, ...]

    def __post_init__(self) -> None:
        if self.backend != EVID_01_INVENTORY_BACKEND:
            raise Evid01AuthorityInventoryError("database backend must be PostgreSQL")
        if self.schema != EVID_01_INVENTORY_SCHEMA:
            raise Evid01AuthorityInventoryError("database schema must be public")
        if type(self.migrations) is not tuple or len(self.migrations) != len(
            EVID_01_INVENTORY_MIGRATIONS
        ):
            raise Evid01AuthorityInventoryError("all required migrations are required")
        if any(type(item) is not Evid01InventoryMigration for item in self.migrations):
            raise Evid01AuthorityInventoryError("migration type is invalid")
        if tuple(item.name for item in self.migrations) != EVID_01_INVENTORY_MIGRATIONS:
            raise Evid01AuthorityInventoryError("migration order or uniqueness is invalid")


@dataclass(frozen=True, slots=True)
class Evid01AuthorityInventorySnapshot:
    """Validated external snapshot; no production claim is attached."""

    captured_at: datetime
    candidate: Evid01InventoryCandidate
    read_only: bool
    database: Evid01InventoryDatabase
    row_counts: tuple[tuple[str, int], ...]
    source_payload_sha256: str

    def __post_init__(self) -> None:
        _utc(self.captured_at, "captured_at")
        if type(self.candidate) is not Evid01InventoryCandidate:
            raise Evid01AuthorityInventoryError("candidate type is invalid")
        if type(self.read_only) is not bool or not self.read_only:
            raise Evid01AuthorityInventoryError("inventory must be read-only")
        if type(self.database) is not Evid01InventoryDatabase:
            raise Evid01AuthorityInventoryError("database type is invalid")
        _validate_row_counts(self.row_counts)
        _sha256(self.source_payload_sha256, "source_payload_sha256")


@dataclass(frozen=True, slots=True)
class Evid01AuthorityInventoryReport:
    """Canonical report derived from a snapshot with production disabled."""

    captured_at: datetime
    candidate: Evid01InventoryCandidate
    database: Evid01InventoryDatabase
    row_counts: tuple[tuple[str, int], ...]
    source_payload_sha256: str
    outcome: Evid01AuthorityInventoryOutcome
    production_claim: bool = False
    production_ready: bool = False
    authority_ready: bool = False
    runtime_enablement: str = "not_authorized"

    def __post_init__(self) -> None:
        _utc(self.captured_at, "captured_at")
        if type(self.candidate) is not Evid01InventoryCandidate:
            raise Evid01AuthorityInventoryError("candidate type is invalid")
        if type(self.database) is not Evid01InventoryDatabase:
            raise Evid01AuthorityInventoryError("database type is invalid")
        _validate_row_counts(self.row_counts)
        _sha256(self.source_payload_sha256, "source_payload_sha256")
        if type(self.outcome) is not Evid01AuthorityInventoryOutcome:
            raise Evid01AuthorityInventoryError("outcome type is invalid")
        if type(self.production_claim) is not bool or self.production_claim:
            raise Evid01AuthorityInventoryError("production_claim must remain false")
        if type(self.production_ready) is not bool or self.production_ready:
            raise Evid01AuthorityInventoryError("production_ready must remain false")
        if type(self.authority_ready) is not bool or self.authority_ready:
            raise Evid01AuthorityInventoryError("authority_ready must remain false")
        if self.runtime_enablement != "not_authorized":
            raise Evid01AuthorityInventoryError("runtime_enablement must remain not_authorized")


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise Evid01AuthorityInventoryError(f"{field_name} is not a canonical token")
    return value


def _commit(value: object, field_name: str) -> str:
    if type(value) is not str or _COMMIT_RE.fullmatch(value) is None:
        raise Evid01AuthorityInventoryError(f"{field_name} is not a full commit identity")
    return value


def _sha256(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Evid01AuthorityInventoryError(f"{field_name} must be lowercase SHA-256")
    return value


def _utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise Evid01AuthorityInventoryError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise Evid01AuthorityInventoryError(f"{field_name} must be UTC")
    return value


def _parse_utc(value: object, field_name: str) -> datetime:
    if type(value) is not str or _UTC_TEXT_RE.fullmatch(value) is None:
        raise Evid01AuthorityInventoryError(f"{field_name} is not canonical UTC-Z text")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Evid01AuthorityInventoryError(f"{field_name} is not a valid timestamp") from exc
    return _utc(parsed, field_name)


def _utc_text(value: datetime) -> str:
    """Serialize an aware UTC timestamp in the fixed microsecond form."""

    _utc(value, "timestamp")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_keys(value: Mapping[str, object], expected: frozenset[str], context: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise Evid01AuthorityInventoryError(
            f"{context} keys mismatch; missing={missing}, unknown={unknown}"
        )


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Evid01AuthorityInventoryError(f"{context} must be an object with string keys")
    return cast(Mapping[str, object], value)


def _reject_forbidden_keys(value: object, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if type(key) is not str:
                raise Evid01AuthorityInventoryError(f"{path} contains a non-string key")
            lowered = key.lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise Evid01AuthorityInventoryError(f"forbidden field at {path}.{key}")
            _reject_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, f"{path}[{index}]")


def _parse_candidate(value: object) -> Evid01InventoryCandidate:
    raw = _mapping(value, "candidate")
    _require_keys(raw, frozenset({"stable_version", "source_commit", "release"}), "candidate")
    return Evid01InventoryCandidate(
        stable_version=_token(raw["stable_version"], "candidate.stable_version"),
        source_commit=_commit(raw["source_commit"], "candidate.source_commit"),
        release=_token(raw["release"], "candidate.release"),
    )


def _parse_database(value: object) -> Evid01InventoryDatabase:
    raw = _mapping(value, "database")
    _require_keys(raw, frozenset({"backend", "schema", "migrations"}), "database")
    migrations_raw = raw["migrations"]
    if type(migrations_raw) is not list:
        raise Evid01AuthorityInventoryError("database.migrations must be a list")
    migrations: list[Evid01InventoryMigration] = []
    for index, item in enumerate(migrations_raw):
        migration = _mapping(item, f"database.migrations[{index}]")
        _require_keys(migration, frozenset({"app", "name", "applied_at"}), "migration")
        migrations.append(
            Evid01InventoryMigration(
                app=_token(migration["app"], "migration.app"),
                name=_token(migration["name"], "migration.name"),
                applied_at=_parse_utc(migration["applied_at"], "migration.applied_at"),
            )
        )
    return Evid01InventoryDatabase(
        backend=_token(raw["backend"], "database.backend"),
        schema=_token(raw["schema"], "database.schema"),
        migrations=tuple(migrations),
    )


def _parse_row_counts(value: object) -> tuple[tuple[str, int], ...]:
    raw = _mapping(value, "row_counts")
    if frozenset(raw) != frozenset(EVID_01_INVENTORY_TABLES):
        raise Evid01AuthorityInventoryError(
            "row_counts must contain exactly the 12 expected tables"
        )
    result: list[tuple[str, int]] = []
    for table in EVID_01_INVENTORY_TABLES:
        count = raw[table]
        if type(count) is not int or count < 0:
            raise Evid01AuthorityInventoryError(f"row_counts.{table} must be non-negative int")
        result.append((table, count))
    return tuple(result)


def _validate_row_counts(value: tuple[tuple[str, int], ...]) -> None:
    if type(value) is not tuple or len(value) != len(EVID_01_INVENTORY_TABLES):
        raise Evid01AuthorityInventoryError("row_counts shape is invalid")
    if tuple(item[0] for item in value) != EVID_01_INVENTORY_TABLES:
        raise Evid01AuthorityInventoryError("row_counts order is not canonical")
    if any(type(item) is not tuple or len(item) != 2 for item in value):
        raise Evid01AuthorityInventoryError("row_counts item shape is invalid")
    if any(type(item[0]) is not str or type(item[1]) is not int or item[1] < 0 for item in value):
        raise Evid01AuthorityInventoryError("row_counts values are invalid")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _snapshot_payload(snapshot: Evid01AuthorityInventorySnapshot) -> dict[str, object]:
    return {
        "version": EVID_01_INVENTORY_INPUT_FORMAT,
        "environment": EVID_01_INVENTORY_ENVIRONMENT,
        "captured_at": _utc_text(snapshot.captured_at),
        "candidate": {
            "stable_version": snapshot.candidate.stable_version,
            "source_commit": snapshot.candidate.source_commit,
            "release": snapshot.candidate.release,
        },
        "read_only": True,
        "database": {
            "backend": snapshot.database.backend,
            "schema": snapshot.database.schema,
            "migrations": [
                {
                    "app": item.app,
                    "name": item.name,
                    "applied_at": _utc_text(item.applied_at),
                }
                for item in snapshot.database.migrations
            ],
        },
        "row_counts": dict(snapshot.row_counts),
    }


def parse_evid_01_authority_inventory_snapshot(payload: bytes) -> Evid01AuthorityInventorySnapshot:
    """Parse one strict external EVID-01 snapshot without external I/O."""

    if type(payload) is not bytes or not payload or len(payload) > _MAX_PAYLOAD_BYTES:
        raise Evid01AuthorityInventoryError("snapshot payload size is invalid")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Evid01AuthorityInventoryError("snapshot is not valid UTF-8 JSON") from exc
    _reject_forbidden_keys(decoded)
    raw = _mapping(decoded, "snapshot")
    _require_keys(
        raw,
        frozenset(
            {
                "version",
                "environment",
                "captured_at",
                "candidate",
                "read_only",
                "database",
                "row_counts",
            }
        ),
        "snapshot",
    )
    if raw["version"] != EVID_01_INVENTORY_INPUT_FORMAT:
        raise Evid01AuthorityInventoryError("snapshot version is not canonical")
    if raw["environment"] != EVID_01_INVENTORY_ENVIRONMENT:
        raise Evid01AuthorityInventoryError("snapshot environment must be production")
    return Evid01AuthorityInventorySnapshot(
        captured_at=_parse_utc(raw["captured_at"], "captured_at"),
        candidate=_parse_candidate(raw["candidate"]),
        read_only=raw["read_only"] if type(raw["read_only"]) is bool else False,
        database=_parse_database(raw["database"]),
        row_counts=_parse_row_counts(raw["row_counts"]),
        source_payload_sha256=hashlib.sha256(payload).hexdigest(),
    )


def build_evid_01_authority_inventory_report(
    snapshot: Evid01AuthorityInventorySnapshot,
) -> Evid01AuthorityInventoryReport:
    """Derive a permanently non-production report from a validated snapshot."""

    _validate_row_counts(snapshot.row_counts)
    outcome = (
        Evid01AuthorityInventoryOutcome.BLOCKED_ZERO_SEED_AUTHORITY
        if all(count == 0 for _, count in snapshot.row_counts)
        else Evid01AuthorityInventoryOutcome.BLOCKED_UNVERIFIED_AUTHORITY
    )
    return Evid01AuthorityInventoryReport(
        captured_at=snapshot.captured_at,
        candidate=snapshot.candidate,
        database=snapshot.database,
        row_counts=snapshot.row_counts,
        source_payload_sha256=snapshot.source_payload_sha256,
        outcome=outcome,
    )


def _report_payload(report: Evid01AuthorityInventoryReport) -> dict[str, object]:
    return {
        "version": EVID_01_INVENTORY_REPORT_FORMAT,
        "captured_at": _utc_text(report.captured_at),
        "candidate": {
            "stable_version": report.candidate.stable_version,
            "source_commit": report.candidate.source_commit,
            "release": report.candidate.release,
        },
        "database": {
            "backend": report.database.backend,
            "schema": report.database.schema,
            "migrations": [
                {
                    "app": item.app,
                    "name": item.name,
                    "applied_at": _utc_text(item.applied_at),
                }
                for item in report.database.migrations
            ],
        },
        "row_counts": dict(report.row_counts),
        "source_payload_sha256": report.source_payload_sha256,
        "outcome": report.outcome.value,
        "production_claim": False,
        "production_ready": False,
        "authority_ready": False,
        "runtime_enablement": "not_authorized",
    }


def serialize_evid_01_authority_inventory_report(report: Evid01AuthorityInventoryReport) -> bytes:
    """Serialize a report into deterministic canonical UTF-8 JSON bytes."""

    return _canonical_json(_report_payload(report))


def evid_01_authority_inventory_artifact_sha256(payload: bytes) -> str:
    """Return the content address of canonical report bytes."""

    if type(payload) is not bytes or not payload:
        raise Evid01AuthorityInventoryError("report payload must be non-empty bytes")
    return hashlib.sha256(payload).hexdigest()


def evid_01_authority_inventory_snapshot_payload(
    snapshot: Evid01AuthorityInventorySnapshot,
) -> bytes:
    """Serialize a validated snapshot for deterministic fixture construction."""

    return _canonical_json(_snapshot_payload(snapshot))
