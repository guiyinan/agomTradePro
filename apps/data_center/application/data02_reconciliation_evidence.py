"""Fail-closed DATA-02 reconciliation evidence for externally captured snapshots.

The parser consumes two read-only snapshots produced by an owning collector.  It
does not connect to PostgreSQL, run a backfill, change maintenance state, or
infer a production gate.  Both source observation times and source identities
are retained so that a later operator can bind the report to an authorized
batch without timestamp substitution.
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

from apps.data_center.application.reconciliation import (
    ReconciliationSnapshotExport,
    export_reconciliation_snapshot,
)


class Data02ReconciliationEvidenceError(ValueError):
    """Raised when an external DATA-02 snapshot envelope is malformed."""


_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")
_NATURAL_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/|=-]{1,512}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "canonical",
        "candidate",
        "code_defect_keys",
        "dataset_key",
        "expected_difference_keys",
        "legacy",
        "read_mode",
    }
)
_SNAPSHOT_KEYS: Final[frozenset[str]] = frozenset({"observed_at", "records", "source"})
_CANDIDATE_KEYS: Final[frozenset[str]] = frozenset(
    {"commit", "matrix_sha256", "oci_revision", "version"}
)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow a decoded JSON object and reject non-string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Data02ReconciliationEvidenceError(f"{field_name} must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    """Reject omitted and smuggled keys at every envelope boundary."""

    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise Data02ReconciliationEvidenceError(
            f"{field_name} keys changed (missing={missing}, extra={extra})"
        )


def _token(value: object, field_name: str) -> str:
    """Require a bounded non-secret identity token."""

    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise Data02ReconciliationEvidenceError(f"{field_name} must be a bounded token")
    return value


def _digest(value: object, field_name: str) -> str:
    """Require a lowercase SHA-256 candidate identity digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Data02ReconciliationEvidenceError(f"{field_name} must be a lowercase SHA-256")
    return value


def _utc(value: object, field_name: str) -> datetime:
    """Parse an explicit UTC timestamp without accepting local time."""

    if type(value) is not str or not value.endswith("Z"):
        raise Data02ReconciliationEvidenceError(f"{field_name} must use UTC-Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Data02ReconciliationEvidenceError(f"{field_name} must be ISO-8601 UTC-Z") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Data02ReconciliationEvidenceError(f"{field_name} must use UTC-Z")
    return parsed.astimezone(UTC)


def _json_value(value: object, field_name: str) -> object:
    """Validate JSON values without allowing NaN, infinity, or smuggled objects."""

    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise Data02ReconciliationEvidenceError(f"{field_name} must be finite JSON")
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise Data02ReconciliationEvidenceError(f"{field_name} object keys must be strings")
        return {
            key: _json_value(item, f"{field_name}.{key}") for key, item in sorted(value.items())
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item, f"{field_name}[]") for item in value]
    raise Data02ReconciliationEvidenceError(f"{field_name} must be JSON-compatible")


def _record_map(value: object, field_name: str) -> dict[str, object]:
    """Validate one natural-key to JSON-value snapshot map."""

    raw = _mapping(value, field_name)
    records: dict[str, object] = {}
    for key, item in raw.items():
        if not key.strip():
            raise Data02ReconciliationEvidenceError(f"{field_name} keys cannot be empty")
        records[key] = _json_value(item, f"{field_name}.{key}")
    return records


def _string_list(value: object, field_name: str) -> tuple[str, ...]:
    """Validate a sorted, unique list of natural keys."""

    if not isinstance(value, list):
        raise Data02ReconciliationEvidenceError(f"{field_name} must be an array")
    items: tuple[str, ...] = tuple(
        (
            item
            if type(item) is str and _NATURAL_KEY_RE.fullmatch(item) is not None
            else (_raise_invalid_natural_key(field_name))
        )
        for item in value
    )
    if items != tuple(sorted(items)) or len(set(items)) != len(items):
        raise Data02ReconciliationEvidenceError(f"{field_name} must be sorted and unique")
    return items


def _raise_invalid_natural_key(field_name: str) -> str:
    """Raise the stable error used for classification natural keys."""

    raise Data02ReconciliationEvidenceError(f"{field_name}[] must be a bounded natural key")


@dataclass(frozen=True, slots=True)
class Data02Snapshot:
    """One externally captured snapshot with its source observation boundary."""

    source: str
    observed_at: datetime
    records: dict[str, object]


@dataclass(frozen=True, slots=True)
class Data02ReconciliationEvidence:
    """Canonical reconciliation output that cannot claim production readiness."""

    dataset_key: str
    candidate: dict[str, str]
    read_mode: str
    legacy: Data02Snapshot
    canonical: Data02Snapshot
    export: ReconciliationSnapshotExport

    @property
    def production_ready(self) -> bool:
        """DATA-02 evidence never enables production by itself."""

        return False

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic, JSON-safe evidence payload."""

        return {
            "canonical": {
                "observed_at": _utc_text(self.canonical.observed_at),
                "record_count": len(self.canonical.records),
                "snapshot_sha256": self.export.canonical_snapshot_hash,
                "source": self.canonical.source,
            },
            "classification_evidence": [dict(row) for row in self.export.classification_evidence],
            "counts": self.export.report.counts,
            "candidate": dict(self.candidate),
            "dataset_key": self.dataset_key,
            "evidence_scope": "data02_external_snapshot_reconciliation",
            "legacy": {
                "observed_at": _utc_text(self.legacy.observed_at),
                "record_count": len(self.legacy.records),
                "snapshot_sha256": self.export.legacy_snapshot_hash,
                "source": self.legacy.source,
            },
            "production_claim": False,
            "production_ready": False,
            "read_mode": self.read_mode,
            "reconciliation_clean": self.export.report.is_clean,
            "runtime_enablement": "not_authorized",
            "schema_version": "data02-reconciliation-readonly.v1",
        }


def _utc_text(value: datetime) -> str:
    """Serialize a timestamp in the canonical UTC-Z form."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_data02_reconciliation_snapshot(
    payload: bytes,
    *,
    as_of: datetime | None = None,
) -> Data02ReconciliationEvidence:
    """Parse an externally captured snapshot pair without touching a database."""

    if type(payload) is not bytes or not payload:
        raise Data02ReconciliationEvidenceError("payload must be non-empty bytes")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Data02ReconciliationEvidenceError("payload must be UTF-8 JSON") from exc
    raw = _mapping(decoded, "evidence")
    _exact_keys(raw, _TOP_LEVEL_KEYS, "evidence")
    dataset_key = _token(raw["dataset_key"], "dataset_key")
    if raw["read_mode"] != "select_only":
        raise Data02ReconciliationEvidenceError("read_mode must be select_only")
    candidate_raw = _mapping(raw["candidate"], "candidate")
    _exact_keys(candidate_raw, _CANDIDATE_KEYS, "candidate")
    commit = candidate_raw["commit"]
    if type(commit) is not str or _COMMIT_RE.fullmatch(commit) is None:
        raise Data02ReconciliationEvidenceError("candidate.commit must be a 40-character SHA")
    candidate = {
        "commit": commit,
        "matrix_sha256": _digest(candidate_raw["matrix_sha256"], "candidate.matrix_sha256"),
        "oci_revision": _token(candidate_raw["oci_revision"], "candidate.oci_revision"),
        "version": _token(candidate_raw["version"], "candidate.version"),
    }

    snapshots: dict[str, Data02Snapshot] = {}
    for name in ("legacy", "canonical"):
        snapshot_record = _mapping(raw[name], name)
        _exact_keys(snapshot_record, _SNAPSHOT_KEYS, name)
        snapshots[name] = Data02Snapshot(
            source=_token(snapshot_record["source"], f"{name}.source"),
            observed_at=_utc(snapshot_record["observed_at"], f"{name}.observed_at"),
            records=_record_map(snapshot_record["records"], f"{name}.records"),
        )
    if snapshots["legacy"].source == snapshots["canonical"].source:
        raise Data02ReconciliationEvidenceError("legacy and canonical sources must differ")
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(0):
        raise Data02ReconciliationEvidenceError("as_of must use UTC")
    for name, captured in snapshots.items():
        if captured.observed_at > cutoff:
            raise Data02ReconciliationEvidenceError(f"{name}.observed_at is from the future")

    expected = _string_list(raw["expected_difference_keys"], "expected_difference_keys")
    defects = _string_list(raw["code_defect_keys"], "code_defect_keys")
    all_keys = set(snapshots["legacy"].records) | set(snapshots["canonical"].records)
    unknown_expected = sorted(set(expected) - all_keys)
    unknown_defects = sorted(set(defects) - all_keys)
    if unknown_expected or unknown_defects:
        raise Data02ReconciliationEvidenceError(
            f"classification keys not present in snapshots (expected={unknown_expected}, "
            f"defects={unknown_defects})"
        )
    exported = export_reconciliation_snapshot(
        dataset_key,
        snapshots["legacy"].records,
        snapshots["canonical"].records,
        expected_difference_keys=expected,
        code_defect_keys=defects,
    )
    return Data02ReconciliationEvidence(
        dataset_key=dataset_key,
        candidate=candidate,
        read_mode="select_only",
        legacy=snapshots["legacy"],
        canonical=snapshots["canonical"],
        export=exported,
    )


def serialize_data02_reconciliation_evidence(report: Data02ReconciliationEvidence) -> bytes:
    """Serialize canonical DATA-02 evidence with stable JSON bytes."""

    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def data02_reconciliation_artifact_sha256(payload: bytes) -> str:
    """Return the content address for one canonical DATA-02 artifact."""

    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "Data02ReconciliationEvidence",
    "Data02ReconciliationEvidenceError",
    "Data02Snapshot",
    "data02_reconciliation_artifact_sha256",
    "parse_data02_reconciliation_snapshot",
    "serialize_data02_reconciliation_evidence",
]
