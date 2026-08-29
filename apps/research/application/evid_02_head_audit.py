"""Read-only EVID-02 approval/current-head audit contract.

This module validates a bounded, externally captured snapshot of the
append-only approval and activation ledgers.  It never opens a database,
creates approval records, or turns an empty/invalid ledger into production
evidence.  The resulting report is deliberately marked non-production and
keeps human approval unavailable.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

EVID_02_HEAD_AUDIT_INPUT_FORMAT: Final[str] = "evid-02-head-audit-snapshot.v1"
EVID_02_HEAD_AUDIT_REPORT_FORMAT: Final[str] = "evid-02-head-audit-report.v1"
EVID_02_HEAD_AUDIT_SOURCE_KIND: Final[str] = "readonly_ledger_snapshot"
EVID_02_HEAD_AUDIT_LEDGER_KINDS: Final[tuple[str, ...]] = ("approval", "activation")
EVID_02_SELECT_ONLY_SNAPSHOT_FORMAT: Final[str] = "evid-02-select-only-ledger-snapshot.v1"
EVID_02_SELECT_ONLY_READ_MODE: Final[str] = "select_only"
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_UTC_TEXT_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_MAX_PAYLOAD_BYTES: Final[int] = 2 * 1024 * 1024
_FORBIDDEN_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "session",
    "token",
)


class Evid02HeadAuditError(ValueError):
    """Raised when a head-audit snapshot is not an exact canonical payload."""


class Evid02HeadAuditStatus(StrEnum):
    """Derived status for one ledger snapshot."""

    OK = "ok"
    EMPTY = "empty"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class Evid02SelectOnlyCapture:
    """Provenance bound to one externally captured SELECT-only snapshot."""

    environment: str
    database_alias: str
    candidate_commit: str
    candidate_release: str
    query_digest: str
    read_mode: str = EVID_02_SELECT_ONLY_READ_MODE

    def __post_init__(self) -> None:
        if type(self.environment) is not str or self.environment not in {
            "production",
            "staging",
            "local_disposable",
        }:
            raise Evid02HeadAuditError("capture environment is unsupported")
        _token(self.database_alias, "database_alias")
        if (
            type(self.candidate_commit) is not str
            or _COMMIT_RE.fullmatch(self.candidate_commit) is None
        ):
            raise Evid02HeadAuditError("candidate_commit must be a lowercase git SHA-1")
        _token(self.candidate_release, "candidate_release")
        _sha256(self.query_digest, "query_digest")
        if self.read_mode != EVID_02_SELECT_ONLY_READ_MODE:
            raise Evid02HeadAuditError("capture read_mode must be select_only")


@dataclass(frozen=True, slots=True)
class Evid02SelectOnlySnapshot:
    """Canonicalized snapshot plus non-production capture provenance."""

    capture: Evid02SelectOnlyCapture
    canonical_payload: bytes
    source_payload_sha256: str

    def __post_init__(self) -> None:
        if type(self.canonical_payload) is not bytes or not self.canonical_payload:
            raise Evid02HeadAuditError("canonical snapshot payload must be non-empty bytes")
        _sha256(self.source_payload_sha256, "source_payload_sha256")


@dataclass(frozen=True, slots=True)
class Evid02HeadAuditRow:
    """Safe immutable projection of one approval or activation ledger row."""

    ledger_kind: str
    record_id: str
    record_version: str
    content_hash: str
    predecessor_hash: str | None
    recorded_at: datetime
    valid_until: datetime
    operator_id: str
    operator_version: str
    definition_hash: str
    approval_hash: str | None

    def __post_init__(self) -> None:
        if self.ledger_kind not in EVID_02_HEAD_AUDIT_LEDGER_KINDS:
            raise Evid02HeadAuditError("ledger kind is not canonical")
        _token(self.record_id, "record_id")
        _token(self.record_version, "record_version")
        _sha256(self.content_hash, "content_hash")
        if self.predecessor_hash is not None:
            _sha256(self.predecessor_hash, "predecessor_hash")
        _utc(self.recorded_at, "recorded_at")
        _utc(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise Evid02HeadAuditError("recorded_at must precede valid_until")
        _token(self.operator_id, "operator_id")
        _token(self.operator_version, "operator_version")
        _sha256(self.definition_hash, "definition_hash")
        if self.approval_hash is not None:
            _sha256(self.approval_hash, "approval_hash")
        if self.ledger_kind == "approval" and self.approval_hash is not None:
            raise Evid02HeadAuditError("approval row cannot reference an approval hash")
        if self.ledger_kind == "activation" and self.approval_hash is None:
            raise Evid02HeadAuditError("activation row must reference an approval hash")


@dataclass(frozen=True, slots=True)
class Evid02HeadAuditSummary:
    """Read-only chain result for one ledger kind."""

    ledger_kind: str
    status: Evid02HeadAuditStatus
    row_count: int
    root_count: int
    head_hash: str | None
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.ledger_kind not in EVID_02_HEAD_AUDIT_LEDGER_KINDS:
            raise Evid02HeadAuditError("summary ledger kind is not canonical")
        if type(self.status) is not Evid02HeadAuditStatus:
            raise Evid02HeadAuditError("summary status is invalid")
        if type(self.row_count) is not int or self.row_count < 0:
            raise Evid02HeadAuditError("row_count must be a non-negative integer")
        if type(self.root_count) is not int or self.root_count < 0:
            raise Evid02HeadAuditError("root_count must be a non-negative integer")
        if self.head_hash is not None:
            _sha256(self.head_hash, "head_hash")
        if type(self.issues) is not tuple or any(type(item) is not str for item in self.issues):
            raise Evid02HeadAuditError("issues must be a tuple of strings")
        if self.status is Evid02HeadAuditStatus.OK and self.issues:
            raise Evid02HeadAuditError("ok summary cannot contain issues")
        if self.status is Evid02HeadAuditStatus.EMPTY and self.row_count != 0:
            raise Evid02HeadAuditError("empty summary must contain no rows")
        if self.status is Evid02HeadAuditStatus.CORRUPT and not self.issues:
            raise Evid02HeadAuditError("corrupt summary must explain an issue")


@dataclass(frozen=True, slots=True)
class Evid02HeadAuditReport:
    """Canonical non-production report derived from a read-only snapshot."""

    captured_at: datetime
    as_of: datetime
    source_kind: str
    source_payload_sha256: str
    summaries: tuple[Evid02HeadAuditSummary, ...]
    production_claim: bool = False
    production_ready: bool = False
    human_approval_status: str = "not_collected"
    capture: Evid02SelectOnlyCapture | None = None

    def __post_init__(self) -> None:
        _utc(self.captured_at, "captured_at")
        _utc(self.as_of, "as_of")
        if self.captured_at < self.as_of:
            raise Evid02HeadAuditError("captured_at cannot precede as_of")
        _token(self.source_kind, "source_kind")
        _sha256(self.source_payload_sha256, "source_payload_sha256")
        if type(self.summaries) is not tuple or len(self.summaries) != 2:
            raise Evid02HeadAuditError("both approval and activation summaries are required")
        if tuple(item.ledger_kind for item in self.summaries) != EVID_02_HEAD_AUDIT_LEDGER_KINDS:
            raise Evid02HeadAuditError("summary order is not canonical")
        if any(type(item) is not Evid02HeadAuditSummary for item in self.summaries):
            raise Evid02HeadAuditError("summary type is invalid")
        if type(self.production_claim) is not bool or self.production_claim:
            raise Evid02HeadAuditError("production_claim must remain false")
        if type(self.production_ready) is not bool or self.production_ready:
            raise Evid02HeadAuditError("production_ready must remain false")
        if self.human_approval_status != "not_collected":
            raise Evid02HeadAuditError("automation cannot invent human approval")
        if self.capture is not None and type(self.capture) is not Evid02SelectOnlyCapture:
            raise Evid02HeadAuditError("capture type is invalid")


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise Evid02HeadAuditError(f"{field_name} is not a canonical token")
    return value


def _sha256(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Evid02HeadAuditError(f"{field_name} must be lowercase SHA-256")
    return value


def _utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise Evid02HeadAuditError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise Evid02HeadAuditError(f"{field_name} must be UTC")
    return value


def _utc_text(value: datetime) -> str:
    _utc(value, "timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: object, field_name: str) -> datetime:
    if type(value) is not str or _UTC_TEXT_RE.fullmatch(value) is None:
        raise Evid02HeadAuditError(f"{field_name} must use UTC-Z microseconds")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Evid02HeadAuditError(f"{field_name} is invalid") from exc
    return _utc(parsed, field_name)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Evid02HeadAuditError(f"{field_name} must be an object with string keys")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    if frozenset(value) != expected:
        raise Evid02HeadAuditError(f"{field_name} key set is not canonical")


def _reject_forbidden(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if type(key) is not str:
                raise Evid02HeadAuditError("snapshot contains a non-string key")
            normalized = key.casefold().replace("-", "_")
            if any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise Evid02HeadAuditError("snapshot contains a forbidden field")
            _reject_forbidden(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden(nested)


def _row(value: object, ledger_kind: str) -> Evid02HeadAuditRow:
    raw = _mapping(value, f"{ledger_kind} row")
    _exact_keys(
        raw,
        frozenset(
            {
                "record_id",
                "record_version",
                "content_hash",
                "predecessor_hash",
                "recorded_at",
                "valid_until",
                "operator_id",
                "operator_version",
                "definition_hash",
                "approval_hash",
            }
        ),
        f"{ledger_kind} row",
    )
    predecessor = raw["predecessor_hash"]
    approval = raw["approval_hash"]
    if predecessor is not None and type(predecessor) is not str:
        raise Evid02HeadAuditError("predecessor_hash must be a string or null")
    if approval is not None and type(approval) is not str:
        raise Evid02HeadAuditError("approval_hash must be a string or null")
    return Evid02HeadAuditRow(
        ledger_kind=ledger_kind,
        record_id=_token(raw["record_id"], "record_id"),
        record_version=_token(raw["record_version"], "record_version"),
        content_hash=_sha256(raw["content_hash"], "content_hash"),
        predecessor_hash=predecessor,
        recorded_at=_parse_utc(raw["recorded_at"], "recorded_at"),
        valid_until=_parse_utc(raw["valid_until"], "valid_until"),
        operator_id=_token(raw["operator_id"], "operator_id"),
        operator_version=_token(raw["operator_version"], "operator_version"),
        definition_hash=_sha256(raw["definition_hash"], "definition_hash"),
        approval_hash=approval,
    )


def _row_payload(row: Evid02HeadAuditRow) -> dict[str, object]:
    """Serialize one validated row for the canonical snapshot shape."""

    return {
        "approval_hash": row.approval_hash,
        "content_hash": row.content_hash,
        "definition_hash": row.definition_hash,
        "operator_id": row.operator_id,
        "operator_version": row.operator_version,
        "predecessor_hash": row.predecessor_hash,
        "record_id": row.record_id,
        "record_version": row.record_version,
        "recorded_at": _utc_text(row.recorded_at),
        "valid_until": _utc_text(row.valid_until),
    }


def _select_only_capture(value: object) -> Evid02SelectOnlyCapture:
    """Validate the provenance envelope emitted by a SELECT-only collector."""

    raw = _mapping(value, "capture")
    _exact_keys(
        raw,
        frozenset(
            {
                "candidate_commit",
                "candidate_release",
                "database_alias",
                "environment",
                "query_digest",
                "read_mode",
            }
        ),
        "capture",
    )
    environment = raw["environment"]
    if type(environment) is not str:
        raise Evid02HeadAuditError("capture environment must be a string")
    return Evid02SelectOnlyCapture(
        environment=environment,
        database_alias=_token(raw["database_alias"], "database_alias"),
        candidate_commit=_token(raw["candidate_commit"], "candidate_commit"),
        candidate_release=_token(raw["candidate_release"], "candidate_release"),
        query_digest=_sha256(raw["query_digest"], "query_digest"),
        read_mode=_token(raw["read_mode"], "read_mode"),
    )


def normalize_evid_02_select_only_snapshot(payload: bytes) -> Evid02SelectOnlySnapshot:
    """Normalize an external SELECT-only ledger capture to the strict audit input.

    The input is a transport envelope, not production authority.  It contains
    only already-captured rows and immutable candidate/query identifiers; this
    function never opens a database, infers approval, or accepts mutation or
    human-approval claims.
    """

    if type(payload) is not bytes or not payload or len(payload) > _MAX_PAYLOAD_BYTES:
        raise Evid02HeadAuditError("select-only payload must be bounded non-empty bytes")
    source_payload_sha256 = hashlib.sha256(payload).hexdigest()
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Evid02HeadAuditError("select-only payload is not UTF-8 JSON") from exc
    _reject_forbidden(decoded)
    root = _mapping(decoded, "select-only snapshot")
    _exact_keys(
        root,
        frozenset(
            {"format", "captured_at", "as_of", "capture", "approval_rows", "activation_rows"}
        ),
        "select-only snapshot",
    )
    if root["format"] != EVID_02_SELECT_ONLY_SNAPSHOT_FORMAT:
        raise Evid02HeadAuditError("select-only snapshot format is unsupported")
    captured_at = _parse_utc(root["captured_at"], "captured_at")
    as_of = _parse_utc(root["as_of"], "as_of")
    if captured_at < as_of:
        raise Evid02HeadAuditError("captured_at cannot precede as_of")
    capture = _select_only_capture(root["capture"])
    canonical_rows: dict[str, list[dict[str, object]]] = {}
    for kind in EVID_02_HEAD_AUDIT_LEDGER_KINDS:
        raw_rows = root[f"{kind}_rows"]
        if isinstance(raw_rows, (str, bytes, bytearray)) or not isinstance(raw_rows, Sequence):
            raise Evid02HeadAuditError(f"{kind}_rows must be an array")
        rows = tuple(_row(item, kind) for item in raw_rows)
        if tuple(sorted(rows, key=lambda item: (item.recorded_at, item.content_hash))) != rows:
            raise Evid02HeadAuditError(f"{kind}_rows must be ordered by recorded_at/content_hash")
        if any(row.recorded_at > as_of for row in rows):
            raise Evid02HeadAuditError(f"{kind}_rows contains a future row beyond the PIT cutoff")
        canonical_rows[f"{kind}_rows"] = [_row_payload(row) for row in rows]
    canonical_root: dict[str, object] = {
        "activation_rows": canonical_rows["activation_rows"],
        "approval_rows": canonical_rows["approval_rows"],
        "as_of": _utc_text(as_of),
        "captured_at": _utc_text(captured_at),
        "format": EVID_02_HEAD_AUDIT_INPUT_FORMAT,
    }
    canonical_payload = json.dumps(
        canonical_root,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    parse_evid_02_head_audit_snapshot(canonical_payload)
    return Evid02SelectOnlySnapshot(
        capture=capture,
        canonical_payload=canonical_payload,
        source_payload_sha256=source_payload_sha256,
    )


def _audit_chain(
    ledger_kind: str,
    rows: tuple[Evid02HeadAuditRow, ...],
    approval_rows: Mapping[str, Evid02HeadAuditRow],
) -> Evid02HeadAuditSummary:
    if not rows:
        return Evid02HeadAuditSummary(
            ledger_kind=ledger_kind,
            status=Evid02HeadAuditStatus.EMPTY,
            row_count=0,
            root_count=0,
            head_hash=None,
            issues=(),
        )
    issues: list[str] = []
    by_hash: dict[str, Evid02HeadAuditRow] = {}
    for row in rows:
        if row.content_hash in by_hash:
            issues.append("duplicate_content_hash")
        by_hash[row.content_hash] = row
        if row.ledger_kind != ledger_kind:
            issues.append("ledger_kind_substitution")
        if ledger_kind == "activation":
            approval = approval_rows.get(row.approval_hash or "")
            if approval is None:
                issues.append("missing_approval_reference")
            elif (
                row.operator_id != approval.operator_id
                or row.operator_version != approval.operator_version
                or row.definition_hash != approval.definition_hash
            ):
                issues.append("approval_identity_drift")
    roots = tuple(row for row in rows if row.predecessor_hash is None)
    if len(roots) != 1:
        issues.append("root_count_invalid")
    children: dict[str, list[Evid02HeadAuditRow]] = {}
    for row in rows:
        predecessor = row.predecessor_hash
        if predecessor is None:
            continue
        parent = by_hash.get(predecessor)
        if parent is None:
            issues.append("orphan_predecessor")
            continue
        if row.recorded_at <= parent.recorded_at:
            issues.append("recorded_clock_not_increasing")
        children.setdefault(predecessor, []).append(row)
    current = roots[0] if len(roots) == 1 else None
    visited: set[str] = set()
    terminal: Evid02HeadAuditRow | None = None
    while current is not None:
        if current.content_hash in visited:
            issues.append("cycle")
            break
        visited.add(current.content_hash)
        candidates = children.get(current.content_hash, [])
        if len(candidates) > 1:
            issues.append("fork")
            break
        if not candidates:
            terminal = current
            current = None
        else:
            current = candidates[0]
    if len(visited) != len(rows):
        issues.append("disconnected_chain")
    unique_issues = tuple(dict.fromkeys(issues))
    return Evid02HeadAuditSummary(
        ledger_kind=ledger_kind,
        status=Evid02HeadAuditStatus.CORRUPT if unique_issues else Evid02HeadAuditStatus.OK,
        row_count=len(rows),
        root_count=len(roots),
        head_hash=None if unique_issues or terminal is None else terminal.content_hash,
        issues=unique_issues,
    )


def parse_evid_02_head_audit_snapshot(payload: bytes) -> Evid02HeadAuditReport:
    """Parse and audit one strict read-only approval/activation snapshot."""

    if type(payload) is not bytes or not payload or len(payload) > _MAX_PAYLOAD_BYTES:
        raise Evid02HeadAuditError("snapshot payload must be bounded non-empty bytes")
    source_payload_sha256 = hashlib.sha256(payload).hexdigest()
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Evid02HeadAuditError("snapshot is not UTF-8 JSON") from exc
    _reject_forbidden(decoded)
    root = _mapping(decoded, "snapshot")
    _exact_keys(
        root,
        frozenset({"format", "captured_at", "as_of", "approval_rows", "activation_rows"}),
        "snapshot",
    )
    if root["format"] != EVID_02_HEAD_AUDIT_INPUT_FORMAT:
        raise Evid02HeadAuditError("snapshot format is unsupported")
    captured_at = _parse_utc(root["captured_at"], "captured_at")
    as_of = _parse_utc(root["as_of"], "as_of")
    if captured_at < as_of:
        raise Evid02HeadAuditError("captured_at cannot precede as_of")
    rows_by_kind: dict[str, tuple[Evid02HeadAuditRow, ...]] = {}
    for kind, key in (("approval", "approval_rows"), ("activation", "activation_rows")):
        raw_rows = root[key]
        if isinstance(raw_rows, (str, bytes, bytearray)) or not isinstance(raw_rows, Sequence):
            raise Evid02HeadAuditError(f"{key} must be an array")
        rows = tuple(_row(item, kind) for item in raw_rows)
        if tuple(sorted(rows, key=lambda item: (item.recorded_at, item.content_hash))) != rows:
            raise Evid02HeadAuditError(f"{key} must be ordered by recorded_at/content_hash")
        if any(row.recorded_at > as_of for row in rows):
            raise Evid02HeadAuditError(f"{key} contains a future row beyond the PIT cutoff")
        rows_by_kind[kind] = rows
    approval_rows = {row.content_hash: row for row in rows_by_kind["approval"]}
    summaries = tuple(
        _audit_chain(kind, rows_by_kind[kind], approval_rows)
        for kind in EVID_02_HEAD_AUDIT_LEDGER_KINDS
    )
    return Evid02HeadAuditReport(
        captured_at=captured_at,
        as_of=as_of,
        source_kind=EVID_02_HEAD_AUDIT_SOURCE_KIND,
        source_payload_sha256=source_payload_sha256,
        summaries=summaries,
    )


def build_evid_02_select_only_head_audit_report(
    snapshot: Evid02SelectOnlySnapshot,
) -> Evid02HeadAuditReport:
    """Build a report while retaining the external capture provenance."""

    if type(snapshot) is not Evid02SelectOnlySnapshot:
        raise Evid02HeadAuditError("select-only snapshot type is invalid")
    report = parse_evid_02_head_audit_snapshot(snapshot.canonical_payload)
    return Evid02HeadAuditReport(
        captured_at=report.captured_at,
        as_of=report.as_of,
        source_kind=report.source_kind,
        source_payload_sha256=snapshot.source_payload_sha256,
        summaries=report.summaries,
        capture=snapshot.capture,
    )


def _summary_payload(summary: Evid02HeadAuditSummary) -> dict[str, object]:
    return {
        "head_hash": summary.head_hash,
        "issues": list(summary.issues),
        "ledger_kind": summary.ledger_kind,
        "root_count": summary.root_count,
        "row_count": summary.row_count,
        "status": summary.status.value,
    }


def _capture_payload(capture: Evid02SelectOnlyCapture) -> dict[str, str]:
    """Serialize capture provenance without adding host or credential fields."""

    return {
        "candidate_commit": capture.candidate_commit,
        "candidate_release": capture.candidate_release,
        "database_alias": capture.database_alias,
        "environment": capture.environment,
        "query_digest": capture.query_digest,
        "read_mode": capture.read_mode,
    }


def serialize_evid_02_head_audit_report(report: Evid02HeadAuditReport) -> bytes:
    """Serialize a validated report as deterministic canonical JSON bytes."""

    if type(report) is not Evid02HeadAuditReport:
        raise Evid02HeadAuditError("report type is invalid")
    report.__post_init__()
    source: dict[str, object] = {
        "kind": report.source_kind,
        "payload_sha256": report.source_payload_sha256,
    }
    if report.capture is not None:
        source["capture"] = _capture_payload(report.capture)
    payload: dict[str, object] = {
        "as_of": _utc_text(report.as_of),
        "captured_at": _utc_text(report.captured_at),
        "format": EVID_02_HEAD_AUDIT_REPORT_FORMAT,
        "human_approval_status": report.human_approval_status,
        "ledgers": [_summary_payload(item) for item in report.summaries],
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "source": source,
    }
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def evid_02_head_audit_artifact_sha256(payload: bytes) -> str:
    """Return the content address of one canonical head-audit report."""

    if type(payload) is not bytes or not payload:
        raise Evid02HeadAuditError("artifact payload must be non-empty bytes")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "EVID_02_HEAD_AUDIT_INPUT_FORMAT",
    "EVID_02_HEAD_AUDIT_REPORT_FORMAT",
    "EVID_02_HEAD_AUDIT_SOURCE_KIND",
    "EVID_02_SELECT_ONLY_READ_MODE",
    "EVID_02_SELECT_ONLY_SNAPSHOT_FORMAT",
    "Evid02HeadAuditError",
    "Evid02HeadAuditReport",
    "Evid02HeadAuditRow",
    "Evid02HeadAuditStatus",
    "Evid02HeadAuditSummary",
    "Evid02SelectOnlyCapture",
    "Evid02SelectOnlySnapshot",
    "build_evid_02_select_only_head_audit_report",
    "evid_02_head_audit_artifact_sha256",
    "normalize_evid_02_select_only_snapshot",
    "parse_evid_02_head_audit_snapshot",
    "serialize_evid_02_head_audit_report",
]
