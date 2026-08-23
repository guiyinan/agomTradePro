"""Strict offline STRAT-01 owner-ledger inventory evidence contract.

The application accepts only an externally captured, SELECT-only inventory.
It never connects to Django, PostgreSQL, a VPS, or a production writer.  A
non-zero row count is deliberately reported as ``nonzero_unverified``: rows
alone do not establish an owner, policy, scope, promotion, or decision
authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, cast

STRAT_01_SNAPSHOT_SCHEMAS: Final[frozenset[str]] = frozenset(
    {
        "strat-01-owner-ledger-readonly-recheck.v1",
        "strat-01-owner-ledger-readonly-recheck.v2",
    }
)
STRAT_01_REPORT_SCHEMA: Final[str] = "strat-01-owner-ledger-inventory-report.v1"
STRAT_01_DATABASE_ALIAS: Final[str] = "default"
STRAT_01_READ_MODE: Final[str] = "select_only"
STRAT_01_OBSERVATION_KIND: Final[str] = "candidate_bound_read_only_inventory"
STRAT_01_MAX_PAYLOAD_BYTES: Final[int] = 2 * 1024 * 1024

_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{14}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/^*-]{1,256}$")
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
_V1_INVENTORY_KEYS: Final[tuple[str, ...]] = (
    "research_r1_to_r8",
    "portfolio_r4_r5_r8",
    "account_owner_assignment",
    "explicit_owner_policy_operator",
)
_V2_INVENTORY_KEYS: Final[tuple[str, ...]] = (
    "research_r1_to_r8",
    "portfolio_r4_r5_r8",
    "account_authority_assignment_broad",
    "explicit_owner_policy_operator_assignment_broad",
)
_V2_SELECTOR_KEYS: Final[frozenset[str]] = frozenset(
    {
        "research_r1_to_r8",
        "portfolio_r4_r5_r8",
        "account_authority_assignment",
        "explicit_owner_policy_operator_assignment",
    }
)


class Strat01OwnerLedgerInventoryError(ValueError):
    """Raised when a STRAT-01 snapshot or report violates its contract."""


class Strat01OwnerLedgerInventoryOutcome(StrEnum):
    """Fail-closed outcomes derived from the observed row counts."""

    ZERO_SEED = "zero_seed"
    NONZERO_UNVERIFIED = "nonzero_unverified"


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Strat01OwnerLedgerInventoryError(f"{context} must be an object with string keys")
    return cast(Mapping[str, object], value)


def _require_keys(value: Mapping[str, object], expected: frozenset[str], context: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise Strat01OwnerLedgerInventoryError(
            f"{context} keys mismatch; missing={missing}, unknown={unknown}"
        )


def _text(value: object, field_name: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value or value.strip() != value or len(value) > 256:
        raise Strat01OwnerLedgerInventoryError(f"{field_name} must be a bounded text token")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise Strat01OwnerLedgerInventoryError(f"{field_name} has an invalid format")
    return value


def _sha256(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Strat01OwnerLedgerInventoryError(f"{field_name} must be lowercase SHA-256")
    return value


def _utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise Strat01OwnerLedgerInventoryError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise Strat01OwnerLedgerInventoryError(f"{field_name} must be UTC")
    return value


def _parse_utc(value: object, field_name: str) -> datetime:
    if type(value) is not str or _UTC_TEXT_RE.fullmatch(value) is None:
        raise Strat01OwnerLedgerInventoryError(f"{field_name} is not canonical UTC-Z text")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise Strat01OwnerLedgerInventoryError(f"{field_name} is not a valid timestamp") from error
    parsed = _utc(parsed, field_name)
    if parsed > datetime.now(UTC) + timedelta(minutes=5):
        raise Strat01OwnerLedgerInventoryError(f"{field_name} is from the future")
    return parsed


def _utc_text(value: datetime) -> str:
    _utc(value, "timestamp")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _reject_forbidden_keys(value: object, path: str = "snapshot") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if type(key) is not str:
                raise Strat01OwnerLedgerInventoryError(f"{path} contains a non-string key")
            lowered = key.lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise Strat01OwnerLedgerInventoryError(f"forbidden field at {path}.{key}")
            _reject_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class Strat01Candidate:
    """Immutable deployment identity captured with one inventory."""

    source_commit: str
    release_tag: str
    image_tag: str
    runtime_revision_match: bool
    image_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.source_commit, "candidate.source_commit", pattern=_COMMIT_RE)
        _text(self.release_tag, "candidate.release_tag", pattern=_RELEASE_RE)
        expected_image = f"agomtradepro-web:{self.release_tag}"
        if self.image_tag != expected_image:
            raise Strat01OwnerLedgerInventoryError(
                "candidate.image_tag must match candidate.release_tag"
            )
        if self.image_id is not None:
            _sha256(self.image_id.removeprefix("sha256:"), "candidate.image_id")
        if type(self.runtime_revision_match) is not bool or not self.runtime_revision_match:
            raise Strat01OwnerLedgerInventoryError("candidate.runtime_revision_match must be true")


@dataclass(frozen=True, slots=True)
class Strat01InventoryGroup:
    """One exact table-count projection from the SELECT-only inventory."""

    table_count: int
    row_count_total: int
    nonzero_table_count: int
    tables: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = (self.table_count, self.row_count_total, self.nonzero_table_count)
        if any(type(value) is not int or value < 0 for value in values):
            raise Strat01OwnerLedgerInventoryError("inventory counts must be non-negative integers")
        if self.nonzero_table_count > self.table_count:
            raise Strat01OwnerLedgerInventoryError("nonzero_table_count exceeds table_count")
        if type(self.tables) is not tuple or len(set(self.tables)) != len(self.tables):
            raise Strat01OwnerLedgerInventoryError("inventory tables must be unique")
        if len(self.tables) and len(self.tables) != self.table_count:
            raise Strat01OwnerLedgerInventoryError("inventory tables length must equal table_count")
        for table in self.tables:
            _text(table, "inventory.tables[]", pattern=_TOKEN_RE)


@dataclass(frozen=True, slots=True)
class Strat01QueryScope:
    """The bounded selector description used for a v2 inventory capture."""

    source: str
    schema: str
    selectors: tuple[tuple[str, str], ...]
    query_kind: str

    def __post_init__(self) -> None:
        _text(self.source, "query_scope.source")
        if self.schema != "public":
            raise Strat01OwnerLedgerInventoryError("query_scope.schema must be public")
        if tuple(key for key, _ in self.selectors) != tuple(sorted(_V2_SELECTOR_KEYS)):
            raise Strat01OwnerLedgerInventoryError("query_scope selectors are not canonical")
        for key, value in self.selectors:
            _text(key, "query_scope.selectors.key", pattern=_TOKEN_RE)
            _text(value, f"query_scope.selectors.{key}")
        if self.query_kind != "table inventory plus SELECT COUNT(*) per selected table":
            raise Strat01OwnerLedgerInventoryError("query_scope.query_kind is not canonical")


@dataclass(frozen=True, slots=True)
class Strat01OwnerLedgerSnapshot:
    """Validated external snapshot with no authority or production claim."""

    schema: str
    observed_at: datetime
    observation_kind: str
    candidate: Strat01Candidate
    database_alias: str
    read_mode: str
    inventory: tuple[tuple[str, Strat01InventoryGroup], ...]
    database: str | None
    query_scope: Strat01QueryScope | None
    limitations: tuple[str, ...]
    source_payload_sha256: str

    def __post_init__(self) -> None:
        if self.schema not in STRAT_01_SNAPSHOT_SCHEMAS:
            raise Strat01OwnerLedgerInventoryError("snapshot schema is not canonical")
        _utc(self.observed_at, "observed_at")
        if self.observation_kind != STRAT_01_OBSERVATION_KIND:
            raise Strat01OwnerLedgerInventoryError("observation_kind is not canonical")
        if type(self.candidate) is not Strat01Candidate:
            raise Strat01OwnerLedgerInventoryError("candidate type is invalid")
        if self.database_alias != STRAT_01_DATABASE_ALIAS:
            raise Strat01OwnerLedgerInventoryError("database_alias must be default")
        if self.read_mode != STRAT_01_READ_MODE:
            raise Strat01OwnerLedgerInventoryError("read_mode must be select_only")
        expected_keys = _V1_INVENTORY_KEYS if self.schema.endswith(".v1") else _V2_INVENTORY_KEYS
        if tuple(key for key, _ in self.inventory) != expected_keys:
            raise Strat01OwnerLedgerInventoryError("inventory groups are not canonical")
        if self.schema.endswith(".v2"):
            if self.database != "agomtradepro" or type(self.query_scope) is not Strat01QueryScope:
                raise Strat01OwnerLedgerInventoryError("v2 database/query_scope is required")
        elif self.database is not None or self.query_scope is not None:
            raise Strat01OwnerLedgerInventoryError("v1 cannot contain v2 query metadata")
        if (
            type(self.limitations) is not tuple
            or not self.limitations
            or any(type(item) is not str or not item for item in self.limitations)
        ):
            raise Strat01OwnerLedgerInventoryError("limitations must be non-empty text")
        _sha256(self.source_payload_sha256, "source_payload_sha256")


@dataclass(frozen=True, slots=True)
class Strat01OwnerLedgerReport:
    """Canonical report that permanently keeps production enablement closed."""

    snapshot: Strat01OwnerLedgerSnapshot
    outcome: Strat01OwnerLedgerInventoryOutcome

    def __post_init__(self) -> None:
        if type(self.snapshot) is not Strat01OwnerLedgerSnapshot:
            raise Strat01OwnerLedgerInventoryError("snapshot type is invalid")
        if type(self.outcome) is not Strat01OwnerLedgerInventoryOutcome:
            raise Strat01OwnerLedgerInventoryError("outcome type is invalid")

    @property
    def production_claim(self) -> bool:
        """Return the permanently false production-claim flag."""

        return False

    @property
    def production_ready(self) -> bool:
        """Return the permanently false production-readiness flag."""

        return False

    @property
    def runtime_enablement(self) -> str:
        """Return the stable disabled runtime state."""

        return "not_authorized"


def _parse_candidate(value: object, *, schema: str) -> Strat01Candidate:
    raw = _mapping(value, "candidate")
    expected = frozenset({"source_commit", "release_tag", "image_tag", "runtime_revision_match"})
    if schema.endswith(".v2"):
        expected = expected | {"image_id"}
    _require_keys(raw, expected, "candidate")
    return Strat01Candidate(
        source_commit=_text(raw["source_commit"], "candidate.source_commit", pattern=_COMMIT_RE),
        release_tag=_text(raw["release_tag"], "candidate.release_tag", pattern=_RELEASE_RE),
        image_tag=_text(raw["image_tag"], "candidate.image_tag", pattern=_TOKEN_RE),
        runtime_revision_match=(
            raw["runtime_revision_match"] if type(raw["runtime_revision_match"]) is bool else False
        ),
        image_id=(
            _text(raw["image_id"], "candidate.image_id", pattern=_TOKEN_RE)
            if schema.endswith(".v2")
            else None
        ),
    )


def _parse_group(value: object, *, key: str, schema: str) -> Strat01InventoryGroup:
    raw = _mapping(value, f"inventory.{key}")
    expected = frozenset({"table_count", "row_count_total", "nonzero_table_count"})
    has_tables = schema.endswith(".v1") and key == "portfolio_r4_r5_r8"
    if has_tables:
        expected = expected | {"tables"}
    _require_keys(raw, expected, f"inventory.{key}")
    tables: tuple[str, ...] = ()
    if has_tables:
        raw_tables = raw["tables"]
        if type(raw_tables) is not list or any(type(item) is not str for item in raw_tables):
            raise Strat01OwnerLedgerInventoryError(f"inventory.{key}.tables must be a string list")
        tables = tuple(raw_tables)
    return Strat01InventoryGroup(
        table_count=raw["table_count"] if type(raw["table_count"]) is int else -1,
        row_count_total=raw["row_count_total"] if type(raw["row_count_total"]) is int else -1,
        nonzero_table_count=(
            raw["nonzero_table_count"] if type(raw["nonzero_table_count"]) is int else -1
        ),
        tables=tables,
    )


def _parse_query_scope(value: object) -> Strat01QueryScope:
    raw = _mapping(value, "query_scope")
    _require_keys(raw, frozenset({"source", "schema", "selectors", "query_kind"}), "query_scope")
    selectors_raw = _mapping(raw["selectors"], "query_scope.selectors")
    _require_keys(selectors_raw, _V2_SELECTOR_KEYS, "query_scope.selectors")
    selectors = tuple(
        (key, _text(selectors_raw[key], f"query_scope.selectors.{key}"))
        for key in sorted(_V2_SELECTOR_KEYS)
    )
    return Strat01QueryScope(
        source=_text(raw["source"], "query_scope.source"),
        schema=_text(raw["schema"], "query_scope.schema", pattern=_TOKEN_RE),
        selectors=selectors,
        query_kind=_text(raw["query_kind"], "query_scope.query_kind"),
    )


def parse_strat_01_owner_ledger_snapshot(payload: bytes) -> Strat01OwnerLedgerSnapshot:
    """Parse one strict external STRAT-01 snapshot without external I/O."""

    if type(payload) is not bytes or not payload or len(payload) > STRAT_01_MAX_PAYLOAD_BYTES:
        raise Strat01OwnerLedgerInventoryError("snapshot payload size is invalid")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Strat01OwnerLedgerInventoryError("snapshot is not valid UTF-8 JSON") from error
    _reject_forbidden_keys(decoded)
    raw = _mapping(decoded, "snapshot")
    schema = _text(raw.get("schema"), "schema", pattern=_TOKEN_RE)
    if schema not in STRAT_01_SNAPSHOT_SCHEMAS:
        raise Strat01OwnerLedgerInventoryError("snapshot schema is not canonical")
    expected = {
        "schema",
        "observed_at",
        "observation_kind",
        "candidate",
        "database_alias",
        "read_mode",
        "inventory",
        "decision",
        "limitations",
    }
    if schema.endswith(".v2"):
        expected |= {"database", "query_scope"}
    _require_keys(raw, frozenset(expected), "snapshot")
    decision = _mapping(raw["decision"], "decision")
    _require_keys(
        decision,
        frozenset(
            {
                "strat_01",
                "production_claim",
                "production_ready",
                "runtime_enablement",
                "human_approval_status",
            }
        ),
        "decision",
    )
    if (
        decision["strat_01"] != "awaiting_production"
        or decision["production_claim"] is not False
        or decision["production_ready"] is not False
        or decision["runtime_enablement"] != "not_authorized"
        or decision["human_approval_status"] != "not_collected"
    ):
        raise Strat01OwnerLedgerInventoryError("decision must remain fail-closed")
    inventory_raw = _mapping(raw["inventory"], "inventory")
    inventory_keys = _V1_INVENTORY_KEYS if schema.endswith(".v1") else _V2_INVENTORY_KEYS
    _require_keys(inventory_raw, frozenset(inventory_keys), "inventory")
    inventory = tuple(
        (key, _parse_group(inventory_raw[key], key=key, schema=schema)) for key in inventory_keys
    )
    limitations_raw = raw["limitations"]
    if type(limitations_raw) is not list or any(
        type(item) is not str or not item.strip() for item in limitations_raw
    ):
        raise Strat01OwnerLedgerInventoryError("limitations must be a non-empty string list")
    return Strat01OwnerLedgerSnapshot(
        schema=schema,
        observed_at=_parse_utc(raw["observed_at"], "observed_at"),
        observation_kind=_text(raw["observation_kind"], "observation_kind", pattern=_TOKEN_RE),
        candidate=_parse_candidate(raw["candidate"], schema=schema),
        database_alias=_text(raw["database_alias"], "database_alias", pattern=_TOKEN_RE),
        read_mode=_text(raw["read_mode"], "read_mode", pattern=_TOKEN_RE),
        inventory=inventory,
        database=(
            _text(raw["database"], "database", pattern=_TOKEN_RE)
            if schema.endswith(".v2")
            else None
        ),
        query_scope=_parse_query_scope(raw["query_scope"]) if schema.endswith(".v2") else None,
        limitations=tuple(limitations_raw),
        source_payload_sha256=hashlib.sha256(payload).hexdigest(),
    )


def build_strat_01_owner_ledger_report(
    snapshot: Strat01OwnerLedgerSnapshot,
) -> Strat01OwnerLedgerReport:
    """Derive a non-production report from one validated snapshot."""

    if type(snapshot) is not Strat01OwnerLedgerSnapshot:
        raise Strat01OwnerLedgerInventoryError("snapshot must be exact Strat01OwnerLedgerSnapshot")
    outcome = (
        Strat01OwnerLedgerInventoryOutcome.ZERO_SEED
        if all(group.row_count_total == 0 for _, group in snapshot.inventory)
        else Strat01OwnerLedgerInventoryOutcome.NONZERO_UNVERIFIED
    )
    return Strat01OwnerLedgerReport(snapshot=snapshot, outcome=outcome)


def _group_payload(group: Strat01InventoryGroup) -> dict[str, object]:
    payload: dict[str, object] = {
        "table_count": group.table_count,
        "row_count_total": group.row_count_total,
        "nonzero_table_count": group.nonzero_table_count,
    }
    if group.tables:
        payload["tables"] = list(group.tables)
    return payload


def _query_scope_payload(scope: Strat01QueryScope) -> dict[str, object]:
    return {
        "source": scope.source,
        "schema": scope.schema,
        "selectors": dict(scope.selectors),
        "query_kind": scope.query_kind,
    }


def serialize_strat_01_owner_ledger_report(report: Strat01OwnerLedgerReport) -> bytes:
    """Serialize a report into deterministic canonical UTF-8 JSON bytes."""

    snapshot = report.snapshot
    candidate_payload: dict[str, object] = {
        "source_commit": snapshot.candidate.source_commit,
        "release_tag": snapshot.candidate.release_tag,
        "image_tag": snapshot.candidate.image_tag,
        "runtime_revision_match": snapshot.candidate.runtime_revision_match,
    }
    payload: dict[str, object] = {
        "schema": STRAT_01_REPORT_SCHEMA,
        "source_schema": snapshot.schema,
        "observed_at": _utc_text(snapshot.observed_at),
        "observation_kind": snapshot.observation_kind,
        "candidate": candidate_payload,
        "database_alias": snapshot.database_alias,
        "read_mode": snapshot.read_mode,
        "inventory": {key: _group_payload(group) for key, group in snapshot.inventory},
        "limitations": list(snapshot.limitations),
        "source_payload_sha256": snapshot.source_payload_sha256,
        "outcome": report.outcome.value,
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
    }
    if snapshot.database is not None and snapshot.query_scope is not None:
        candidate_payload["image_id"] = snapshot.candidate.image_id
        payload["database"] = snapshot.database
        payload["query_scope"] = _query_scope_payload(snapshot.query_scope)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def strat_01_owner_ledger_artifact_sha256(payload: bytes) -> str:
    """Return the content address of canonical report bytes."""

    if type(payload) is not bytes or not payload:
        raise Strat01OwnerLedgerInventoryError("report payload must be non-empty bytes")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "STRAT_01_REPORT_SCHEMA",
    "STRAT_01_SNAPSHOT_SCHEMAS",
    "Strat01Candidate",
    "Strat01InventoryGroup",
    "Strat01OwnerLedgerInventoryError",
    "Strat01OwnerLedgerInventoryOutcome",
    "Strat01OwnerLedgerReport",
    "Strat01OwnerLedgerSnapshot",
    "Strat01QueryScope",
    "build_strat_01_owner_ledger_report",
    "parse_strat_01_owner_ledger_snapshot",
    "serialize_strat_01_owner_ledger_report",
    "strat_01_owner_ledger_artifact_sha256",
]
