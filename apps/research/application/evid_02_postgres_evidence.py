"""Strict offline evidence contract for the EVID-02 PostgreSQL collector.

This module packages facts emitted by an explicitly isolated PostgreSQL
concurrency harness.  It deliberately does not connect to a database, create
approval records, inspect production, or infer human approval.  A successful
report therefore remains software evidence for the disposable harness and
never becomes a production EVID-02 decision by itself.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

EVID_02_REPORT_FORMAT: Final[str] = "evid-02-postgres-concurrency-evidence.v1"
EVID_02_INPUT_FORMAT: Final[str] = "evid-02-postgres-concurrency-run.v1"
EVID_02_LEDGER_IDENTITY: Final[str] = "research.evidence_scope_source_v1"
EVID_02_HARNESS_SUITE: Final[str] = (
    "tests/component/research/test_evidence_scope_source_v1_postgres_concurrency.py"
)
EVID_02_REQUIRED_CASES: Final[tuple[str, ...]] = (
    "empty_root_first_winner",
    "same_predecessor_successor_first_winner",
    "outer_transaction_rollback",
)
_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {"localhost", "127.0.0.1", "::1", "postgres", "postgresql", "db"}
)
_UNSAFE_TOKENS: Final[tuple[str, ...]] = ("prod", "production", "primary", "live")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DATABASE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
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
    "session",
    "token",
)


class Evid02EvidenceError(ValueError):
    """Raised when offline EVID-02 evidence violates its strict contract."""


class Evid02CaseStatus(StrEnum):
    """Outcomes allowed for one harness case."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class Evid02CollectionStatus(StrEnum):
    """Derived outcome of the disposable harness package."""

    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class Evid02DatabaseBinding:
    """Safe identity of the isolated PostgreSQL database used by a harness."""

    vendor: str
    host: str
    database_name: str
    disposable: bool
    empty_before: bool

    def __post_init__(self) -> None:
        if self.vendor != "postgresql":
            raise Evid02EvidenceError("database vendor must be postgresql")
        if self.host.lower() not in _ALLOWED_HOSTS:
            raise Evid02EvidenceError("database host must be local or a test service")
        database_name = self.database_name.lower()
        if _DATABASE_RE.fullmatch(self.database_name) is None:
            raise Evid02EvidenceError("database name is not canonical")
        if "evidence" not in database_name or "test" not in database_name:
            raise Evid02EvidenceError(
                "database name must contain evidence and test for disposable evidence"
            )
        if any(token in database_name for token in _UNSAFE_TOKENS):
            raise Evid02EvidenceError("production-like database name is forbidden")
        if type(self.disposable) is not bool or not self.disposable:
            raise Evid02EvidenceError("database must be explicitly disposable")
        if type(self.empty_before) is not bool or not self.empty_before:
            raise Evid02EvidenceError("database must be empty before the harness")


@dataclass(frozen=True)
class Evid02HarnessRun:
    """Identity and timing facts for one fixed harness invocation."""

    run_id: str
    suite: str
    started_at: datetime
    finished_at: datetime
    pytest_exit_code: int

    def __post_init__(self) -> None:
        _require_token(self.run_id, "run_id")
        if type(self.suite) is not str or self.suite != EVID_02_HARNESS_SUITE:
            raise Evid02EvidenceError("harness suite is not the canonical EVID-02 suite")
        _require_utc(self.started_at, "started_at")
        _require_utc(self.finished_at, "finished_at")
        if self.finished_at < self.started_at:
            raise Evid02EvidenceError("harness finished_at precedes started_at")
        if type(self.pytest_exit_code) is not int or self.pytest_exit_code < 0:
            raise Evid02EvidenceError("pytest_exit_code must be a non-negative integer")


@dataclass(frozen=True)
class Evid02CaseResult:
    """One fixed, independently reported concurrency case."""

    case_id: str
    status: Evid02CaseStatus
    winner_count: int
    conflict_count: int
    row_count: int
    duration_seconds: float

    def __post_init__(self) -> None:
        if self.case_id not in EVID_02_REQUIRED_CASES:
            raise Evid02EvidenceError("unknown EVID-02 harness case")
        if type(self.status) is not Evid02CaseStatus:
            raise Evid02EvidenceError("case status is invalid")
        for field_name in ("winner_count", "conflict_count", "row_count"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise Evid02EvidenceError(f"{field_name} must be a non-negative integer")
        if type(self.duration_seconds) is not float or not math.isfinite(self.duration_seconds):
            raise Evid02EvidenceError("case duration must be a finite float")
        if self.duration_seconds < 0:
            raise Evid02EvidenceError("case duration cannot be negative")
        expected = _EXPECTED_CASE_FACTS[self.case_id]
        observed = (self.winner_count, self.conflict_count, self.row_count)
        if observed != expected:
            raise Evid02EvidenceError("case facts do not match the canonical harness contract")


@dataclass(frozen=True)
class Evid02HeadAudit:
    """Explicitly record whether read-only current-head audit was collected."""

    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status != "not_collected":
            raise Evid02EvidenceError(
                "this offline contract cannot invent current-head audit evidence"
            )
        if self.reason != "local_harness_does_not_query_existing_ledgers":
            raise Evid02EvidenceError("head audit missing the canonical not-collected reason")


@dataclass(frozen=True)
class Evid02HumanApproval:
    """Human approval is always external to this automated evidence package."""

    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status != "not_collected":
            raise Evid02EvidenceError("automation cannot report a human approval decision")
        if self.reason != "automation_must_not_invent_human_approval":
            raise Evid02EvidenceError("approval missing the canonical not-collected reason")


@dataclass(frozen=True)
class Evid02PostgresEvidenceReport:
    """Canonical, non-production EVID-02 package assembled from harness facts."""

    database: Evid02DatabaseBinding
    run: Evid02HarnessRun
    cases: tuple[Evid02CaseResult, ...]
    head_audit: Evid02HeadAudit
    human_approval: Evid02HumanApproval
    collection_status: Evid02CollectionStatus
    source_kind: str
    source_payload_sha256: str

    def __post_init__(self) -> None:
        if type(self.database) is not Evid02DatabaseBinding:
            raise Evid02EvidenceError("database binding type is invalid")
        if type(self.run) is not Evid02HarnessRun:
            raise Evid02EvidenceError("harness run type is invalid")
        if type(self.cases) is not tuple:
            raise Evid02EvidenceError("cases must be a tuple")
        if len(self.cases) != len(EVID_02_REQUIRED_CASES):
            raise Evid02EvidenceError("all canonical harness cases are required")
        case_ids = tuple(case.case_id for case in self.cases)
        if case_ids != tuple(sorted(EVID_02_REQUIRED_CASES)):
            raise Evid02EvidenceError("case set or order is not canonical")
        if any(type(case) is not Evid02CaseResult for case in self.cases):
            raise Evid02EvidenceError("case result type is invalid")
        if type(self.head_audit) is not Evid02HeadAudit:
            raise Evid02EvidenceError("head audit type is invalid")
        if type(self.human_approval) is not Evid02HumanApproval:
            raise Evid02EvidenceError("human approval type is invalid")
        if type(self.collection_status) is not Evid02CollectionStatus:
            raise Evid02EvidenceError("collection status is invalid")
        _require_token(self.source_kind, "source_kind")
        _require_sha256(self.source_payload_sha256, "source_payload_sha256")
        derived_status = _derive_collection_status(self.cases, self.run.pytest_exit_code)
        if self.collection_status is not derived_status:
            raise Evid02EvidenceError("collection status is not derived from case outcomes")

    @property
    def production_ready(self) -> bool:
        """Return the fixed production-gate result for this offline artifact."""

        return False


_EXPECTED_CASE_FACTS: Final[dict[str, tuple[int, int, int]]] = {
    "empty_root_first_winner": (1, 1, 1),
    "same_predecessor_successor_first_winner": (1, 1, 2),
    "outer_transaction_rollback": (0, 0, 0),
}


def _require_token(value: object, field_name: str) -> str:
    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise Evid02EvidenceError(f"{field_name} is not a bounded canonical token")
    return value


def _require_suite(value: object) -> str:
    if type(value) is not str or value != EVID_02_HARNESS_SUITE:
        raise Evid02EvidenceError("harness suite is not the canonical EVID-02 suite")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Evid02EvidenceError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise Evid02EvidenceError(f"{field_name} must be timezone-aware")
    if value.astimezone(UTC) != value or value.isoformat(timespec="microseconds").endswith(
        "+00:00"
    ):
        # Accept any aware UTC value in the typed contract; JSON parsing below
        # enforces the canonical Z representation.
        if value.utcoffset() != UTC.utcoffset(value):
            raise Evid02EvidenceError(f"{field_name} must be UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise Evid02EvidenceError(f"{field_name} must be UTC")
    return value


def _utc_text(value: datetime) -> str:
    """Encode one aware timestamp as canonical UTC-Z text."""

    _require_utc(value, "timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: object, field_name: str) -> datetime:
    if type(value) is not str or _UTC_TEXT_RE.fullmatch(value) is None:
        raise Evid02EvidenceError(f"{field_name} must use canonical UTC-Z microseconds")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise Evid02EvidenceError(f"{field_name} is not a valid UTC timestamp") from error
    return _require_utc(parsed, field_name)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise Evid02EvidenceError(f"{field_name} must be an object")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise Evid02EvidenceError(f"{field_name} must be an array")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    if frozenset(value) != expected:
        raise Evid02EvidenceError(f"{field_name} key set is not canonical")


def _reject_forbidden_keys(value: object) -> None:
    """Reject secret-bearing keys without echoing their values."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise Evid02EvidenceError("secret-bearing fields are forbidden")
            _reject_forbidden_keys(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            _reject_forbidden_keys(nested)


def _int_field(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise Evid02EvidenceError(f"{field_name} must be a non-negative integer")
    return value


def _float_field(value: object, field_name: str) -> float:
    if type(value) is not float or not math.isfinite(value) or value < 0:
        raise Evid02EvidenceError(f"{field_name} must be a finite non-negative float")
    return value


def _bool_field(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise Evid02EvidenceError(f"{field_name} must be a boolean")
    return value


def _case_from_payload(value: object) -> Evid02CaseResult:
    mapping = _mapping(value, "case")
    _exact_keys(
        mapping,
        frozenset(
            {
                "case_id",
                "status",
                "winner_count",
                "conflict_count",
                "row_count",
                "duration_seconds",
            }
        ),
        "case",
    )
    try:
        status = Evid02CaseStatus(str(mapping["status"]))
    except (TypeError, ValueError) as error:
        raise Evid02EvidenceError("case status is invalid") from error
    return Evid02CaseResult(
        case_id=_require_token(mapping["case_id"], "case_id"),
        status=status,
        winner_count=_int_field(mapping["winner_count"], "winner_count"),
        conflict_count=_int_field(mapping["conflict_count"], "conflict_count"),
        row_count=_int_field(mapping["row_count"], "row_count"),
        duration_seconds=_float_field(mapping["duration_seconds"], "duration_seconds"),
    )


def _derive_collection_status(
    cases: tuple[Evid02CaseResult, ...], pytest_exit_code: int
) -> Evid02CollectionStatus:
    statuses = {case.status for case in cases}
    if pytest_exit_code == 0 and statuses == {Evid02CaseStatus.PASSED}:
        return Evid02CollectionStatus.PASSED
    if Evid02CaseStatus.SKIPPED in statuses:
        return Evid02CollectionStatus.INCOMPLETE
    return Evid02CollectionStatus.FAILED


def parse_evid_02_run_payload(payload: bytes, *, source_kind: str) -> Evid02PostgresEvidenceReport:
    """Parse and validate one raw, offline harness result payload."""

    if type(payload) is not bytes or not payload:
        raise Evid02EvidenceError("raw harness payload must be non-empty bytes")
    if len(payload) > 2 * 1024 * 1024:
        raise Evid02EvidenceError("raw harness payload exceeds 2 MiB")
    _require_token(source_kind, "source_kind")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Evid02EvidenceError("raw harness payload is not valid UTF-8 JSON") from error
    _reject_forbidden_keys(decoded)
    root = _mapping(decoded, "raw harness payload")
    _exact_keys(
        root,
        frozenset({"format", "database", "run", "cases", "head_audit", "human_approval"}),
        "raw harness payload",
    )
    if root["format"] != EVID_02_INPUT_FORMAT:
        raise Evid02EvidenceError("raw harness format is not canonical")

    database_payload = _mapping(root["database"], "database")
    _exact_keys(
        database_payload,
        frozenset({"vendor", "host", "database_name", "disposable", "empty_before"}),
        "database",
    )
    database = Evid02DatabaseBinding(
        vendor=str(database_payload["vendor"]),
        host=_require_token(database_payload["host"], "database.host"),
        database_name=_require_token(database_payload["database_name"], "database.database_name"),
        disposable=_bool_field(database_payload["disposable"], "database.disposable"),
        empty_before=_bool_field(database_payload["empty_before"], "database.empty_before"),
    )

    run_payload = _mapping(root["run"], "run")
    _exact_keys(
        run_payload,
        frozenset({"run_id", "suite", "started_at", "finished_at", "pytest_exit_code"}),
        "run",
    )
    run = Evid02HarnessRun(
        run_id=_require_token(run_payload["run_id"], "run.run_id"),
        suite=_require_suite(run_payload["suite"]),
        started_at=_parse_utc(run_payload["started_at"], "run.started_at"),
        finished_at=_parse_utc(run_payload["finished_at"], "run.finished_at"),
        pytest_exit_code=_int_field(run_payload["pytest_exit_code"], "run.pytest_exit_code"),
    )
    raw_cases = _sequence(root["cases"], "cases")
    cases = tuple(
        sorted((_case_from_payload(item) for item in raw_cases), key=lambda item: item.case_id)
    )

    head_payload = _mapping(root["head_audit"], "head_audit")
    _exact_keys(head_payload, frozenset({"status", "reason"}), "head_audit")
    head_audit = Evid02HeadAudit(
        status=_require_token(head_payload["status"], "head_audit.status"),
        reason=_require_token(head_payload["reason"], "head_audit.reason"),
    )

    approval_payload = _mapping(root["human_approval"], "human_approval")
    _exact_keys(approval_payload, frozenset({"status", "reason"}), "human_approval")
    human_approval = Evid02HumanApproval(
        status=_require_token(approval_payload["status"], "human_approval.status"),
        reason=_require_token(approval_payload["reason"], "human_approval.reason"),
    )

    return Evid02PostgresEvidenceReport(
        database=database,
        run=run,
        cases=cases,
        head_audit=head_audit,
        human_approval=human_approval,
        collection_status=_derive_collection_status(cases, run.pytest_exit_code),
        source_kind=source_kind,
        source_payload_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _case_payload(case: Evid02CaseResult) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "conflict_count": case.conflict_count,
        "duration_seconds": case.duration_seconds,
        "row_count": case.row_count,
        "status": case.status.value,
        "winner_count": case.winner_count,
    }


def serialize_evid_02_report(report: Evid02PostgresEvidenceReport) -> bytes:
    """Serialize one validated offline report into deterministic JSON bytes."""

    if type(report) is not Evid02PostgresEvidenceReport:
        raise Evid02EvidenceError("report type is invalid")
    report.__post_init__()
    payload: dict[str, object] = {
        "collection_status": report.collection_status.value,
        "database": {
            "database_name": report.database.database_name,
            "disposable": report.database.disposable,
            "empty_before": report.database.empty_before,
            "host": report.database.host,
            "vendor": report.database.vendor,
        },
        "evidence_scope": "offline_disposable_postgresql_software",
        "format": EVID_02_REPORT_FORMAT,
        "head_audit": {
            "reason": report.head_audit.reason,
            "status": report.head_audit.status,
        },
        "human_approval": {
            "reason": report.human_approval.reason,
            "status": report.human_approval.status,
        },
        "production_claim": False,
        "production_ready": report.production_ready,
        "run": {
            "finished_at": _utc_text(report.run.finished_at),
            "pytest_exit_code": report.run.pytest_exit_code,
            "run_id": report.run.run_id,
            "started_at": _utc_text(report.run.started_at),
            "suite": report.run.suite,
        },
        "runtime_enablement": "not_authorized",
        "source": {
            "kind": report.source_kind,
            "payload_sha256": report.source_payload_sha256,
        },
        "target_ledger": EVID_02_LEDGER_IDENTITY,
        "cases": [_case_payload(case) for case in report.cases],
    }
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def evid_02_artifact_sha256(payload: bytes) -> str:
    """Return the content address of one serialized EVID-02 artifact."""

    if type(payload) is not bytes or not payload:
        raise Evid02EvidenceError("artifact payload must be non-empty bytes")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "EVID_02_HARNESS_SUITE",
    "EVID_02_INPUT_FORMAT",
    "EVID_02_LEDGER_IDENTITY",
    "EVID_02_REPORT_FORMAT",
    "EVID_02_REQUIRED_CASES",
    "Evid02CaseResult",
    "Evid02CaseStatus",
    "Evid02CollectionStatus",
    "Evid02DatabaseBinding",
    "Evid02EvidenceError",
    "Evid02HarnessRun",
    "Evid02HeadAudit",
    "Evid02HumanApproval",
    "Evid02PostgresEvidenceReport",
    "evid_02_artifact_sha256",
    "parse_evid_02_run_payload",
    "serialize_evid_02_report",
]
