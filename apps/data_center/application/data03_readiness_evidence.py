"""Fail-closed DATA-03 readiness evidence for externally captured probes.

The parser consumes server-produced GET responses for the ordinary service
readiness endpoint and the stricter decision-readiness endpoint.  It never
opens a network connection, queries Django, changes maintenance state, or
claims that a cutover/observation gate passed.  Candidate identity is repeated
on every sample so drift cannot be hidden behind a top-level label.
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


class Data03ReadinessEvidenceError(ValueError):
    """Raised when a DATA-03 readiness observation envelope is malformed."""


_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_KEYS: Final[frozenset[str]] = frozenset(
    {"commit", "matrix_sha256", "oci_revision", "version"}
)
_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset({"candidate", "observations", "read_mode"})
_OBSERVATION_KEYS: Final[frozenset[str]] = frozenset(
    {"captured_at", "candidate", "decision", "service", "smoke_checks"}
)
_SERVICE_KEYS: Final[frozenset[str]] = frozenset(
    {"checks", "endpoint", "http_status", "status", "timestamp"}
)
_DECISION_KEYS: Final[frozenset[str]] = frozenset(
    {"checks", "endpoint", "http_status", "must_not_use_for_decision", "status", "timestamp"}
)
_SMOKE_KEYS: Final[frozenset[str]] = frozenset({"detail", "key", "observed_at", "status"})
_SERVICE_ENDPOINT: Final[str] = "/api/ready/"
_DECISION_ENDPOINT: Final[str] = "/api/decision-ready/"
_SMOKE_STATUSES: Final[frozenset[str]] = frozenset({"ok", "blocked", "failed", "unknown"})
_CHECK_OK_STATUSES: Final[frozenset[str]] = frozenset({"ok", "skipped", "warning"})
_CHECK_BLOCKING_STATUSES: Final[frozenset[str]] = frozenset(
    {"blocked", "error", "failed", "incomplete", "stale", "unknown"}
)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow a decoded JSON object and reject non-string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Data03ReadinessEvidenceError(f"{field_name} must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    """Reject omitted and smuggled keys at every envelope boundary."""

    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise Data03ReadinessEvidenceError(
            f"{field_name} keys changed (missing={missing}, extra={extra})"
        )


def _token(value: object, field_name: str) -> str:
    """Require a bounded non-secret identity token."""

    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise Data03ReadinessEvidenceError(f"{field_name} must be a bounded token")
    return value


def _utc(value: object, field_name: str) -> datetime:
    """Parse an explicit UTC timestamp without accepting local time."""

    if type(value) is not str or not value.endswith("Z"):
        raise Data03ReadinessEvidenceError(f"{field_name} must use UTC-Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Data03ReadinessEvidenceError(f"{field_name} must be ISO-8601 UTC-Z") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Data03ReadinessEvidenceError(f"{field_name} must use UTC-Z")
    return parsed.astimezone(UTC)


def _json_value(value: object, field_name: str) -> object:
    """Validate JSON values without allowing NaN, infinity, or smuggled objects."""

    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise Data03ReadinessEvidenceError(f"{field_name} must be finite JSON")
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise Data03ReadinessEvidenceError(f"{field_name} object keys must be strings")
        return {
            key: _json_value(item, f"{field_name}.{key}") for key, item in sorted(value.items())
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item, f"{field_name}[]") for item in value]
    raise Data03ReadinessEvidenceError(f"{field_name} must be JSON-compatible")


def _candidate(value: object, field_name: str = "candidate") -> dict[str, str]:
    """Validate one immutable candidate identity."""

    raw = _mapping(value, field_name)
    _exact_keys(raw, _CANDIDATE_KEYS, field_name)
    commit = raw["commit"]
    if type(commit) is not str or _COMMIT_RE.fullmatch(commit) is None:
        raise Data03ReadinessEvidenceError(f"{field_name}.commit must be a 40-character SHA")
    matrix_sha256 = raw["matrix_sha256"]
    if type(matrix_sha256) is not str or _SHA256_RE.fullmatch(matrix_sha256) is None:
        raise Data03ReadinessEvidenceError(f"{field_name}.matrix_sha256 must be lowercase SHA-256")
    return {
        "commit": commit,
        "matrix_sha256": matrix_sha256,
        "oci_revision": _token(raw["oci_revision"], f"{field_name}.oci_revision"),
        "version": _token(raw["version"], f"{field_name}.version"),
    }


def _status(value: object, allowed: frozenset[str], field_name: str) -> str:
    """Validate one bounded status token."""

    if type(value) is not str or value not in allowed:
        raise Data03ReadinessEvidenceError(f"{field_name} has an unsupported status")
    return value


def _http_status(value: object, field_name: str) -> int:
    """Validate a normal HTTP response status."""

    if type(value) is not int or not 100 <= value <= 599:
        raise Data03ReadinessEvidenceError(f"{field_name} must be an HTTP status")
    return value


def _check_defects(checks: Mapping[str, object], field_name: str) -> tuple[int, tuple[str, ...]]:
    """Derive blocking check facts without inventing missing check fields."""

    defect_count = 0
    blockers: set[str] = set()

    def visit(value: object, path: str) -> None:
        nonlocal defect_count
        if isinstance(value, Mapping):
            status = value.get("status")
            if type(status) is str and status in _CHECK_BLOCKING_STATUSES:
                defect_count += 1
                blockers.add(path)
            if value.get("must_not_use_for_decision") is True:
                blockers.add(path)
            reason = value.get("block_reason_code")
            if type(reason) is str and reason:
                blockers.add(reason)
            for key, child in value.items():
                if type(key) is str:
                    visit(child, f"{path}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(checks, field_name)
    return defect_count, tuple(sorted(blockers))


def _checks(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow a validated response checks object for report derivation."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Data03ReadinessEvidenceError(f"{field_name} must be an object")
    return value


@dataclass(frozen=True, slots=True)
class Data03Probe:
    """One validated service/decision probe and its canonical smoke checks."""

    captured_at: datetime
    candidate: dict[str, str]
    service: dict[str, object]
    decision: dict[str, object]
    smoke_checks: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class Data03ReadinessEvidence:
    """Canonical DATA-03 report that cannot enable production or decision use."""

    candidate: dict[str, str]
    read_mode: str
    probes: tuple[Data03Probe, ...]

    @property
    def production_ready(self) -> bool:
        """Read-only observations never enable a production cutover."""

        return False

    def to_dict(self) -> dict[str, object]:
        """Return deterministic JSON-safe readiness evidence."""

        first = self.probes[0].captured_at
        last = self.probes[-1].captured_at
        service_failures = sum(1 for probe in self.probes if probe.service["status"] != "ok")
        decision_blockers = sum(
            1
            for probe in self.probes
            if probe.decision["status"] != "ok"
            or probe.decision["must_not_use_for_decision"] is True
        )
        smoke_failures = sum(
            1 for probe in self.probes for check in probe.smoke_checks if check["status"] != "ok"
        )
        check_defects = 0
        for probe in self.probes:
            check_defects += _check_defects(
                _checks(probe.service["checks"], "service.checks"), "service.checks"
            )[0]
            check_defects += _check_defects(
                _checks(probe.decision["checks"], "decision.checks"), "decision.checks"
            )[0]
        source_latencies = [
            (probe.captured_at - _timestamp(probe.service, "service")) for probe in self.probes
        ] + [(probe.captured_at - _timestamp(probe.decision, "decision")) for probe in self.probes]
        max_source_age = max((latency.total_seconds() for latency in source_latencies), default=0.0)
        return {
            "candidate": dict(self.candidate),
            "checks": {
                "check_defect_count": check_defects,
                "decision_blocker_count": decision_blockers,
                "service_failure_count": service_failures,
                "smoke_failure_count": smoke_failures,
            },
            "evidence_scope": "data03_external_readiness_observation",
            "observation": {
                "first_captured_at": _utc_text(first),
                "last_captured_at": _utc_text(last),
                "max_source_age_seconds": max_source_age,
                "observation_duration_seconds": (last - first).total_seconds(),
                "sample_count": len(self.probes),
            },
            "production_claim": False,
            "production_ready": False,
            "read_mode": self.read_mode,
            "runtime_enablement": "not_authorized",
            "schema_version": "data03-readiness-readonly.v1",
            "samples": [
                {
                    "captured_at": _utc_text(probe.captured_at),
                    "candidate": dict(probe.candidate),
                    "decision": _serialized_probe_response(probe.decision),
                    "service": _serialized_probe_response(probe.service),
                    "smoke_checks": [
                        {
                            "detail": check["detail"],
                            "key": check["key"],
                            "observed_at": _utc_text(check["observed_at"]),
                            "status": check["status"],
                        }
                        for check in probe.smoke_checks
                    ],
                }
                for probe in self.probes
            ],
        }


def _timestamp(response: Mapping[str, object], field_name: str) -> datetime:
    """Return a validated response source timestamp."""

    value = response.get("timestamp")
    if not isinstance(value, datetime):
        raise Data03ReadinessEvidenceError(f"{field_name}.timestamp is unavailable")
    return value


def _serialized_probe_response(response: Mapping[str, object]) -> dict[str, object]:
    """Serialize a validated response while preserving its source timestamp."""

    return {
        "checks": response["checks"],
        "endpoint": response["endpoint"],
        "http_status": response["http_status"],
        **(
            {"must_not_use_for_decision": response["must_not_use_for_decision"]}
            if "must_not_use_for_decision" in response
            else {}
        ),
        "status": response["status"],
        "timestamp": _utc_text(_timestamp(response, str(response["endpoint"]))),
    }


def _utc_text(value: object) -> str:
    """Serialize a timestamp in canonical UTC-Z form."""

    if not isinstance(value, datetime):
        raise Data03ReadinessEvidenceError("timestamp value is unavailable")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _response(
    value: object,
    *,
    field_name: str,
    decision: bool,
    captured_at: datetime,
) -> dict[str, object]:
    """Validate one raw readiness response and derive no synthetic fields."""

    raw = _mapping(value, field_name)
    expected = _DECISION_KEYS if decision else _SERVICE_KEYS
    _exact_keys(raw, expected, field_name)
    endpoint = raw["endpoint"]
    expected_endpoint = _DECISION_ENDPOINT if decision else _SERVICE_ENDPOINT
    if endpoint != expected_endpoint:
        raise Data03ReadinessEvidenceError(f"{field_name}.endpoint must be {expected_endpoint}")
    status = _status(
        raw["status"],
        frozenset({"ok", "blocked"} if decision else {"ok", "error"}),
        f"{field_name}.status",
    )
    http_status = _http_status(raw["http_status"], f"{field_name}.http_status")
    timestamp = _utc(raw["timestamp"], f"{field_name}.timestamp")
    if timestamp > captured_at:
        raise Data03ReadinessEvidenceError(f"{field_name}.timestamp is from the future")
    if decision:
        must_not = raw["must_not_use_for_decision"]
        if type(must_not) is not bool:
            raise Data03ReadinessEvidenceError(
                f"{field_name}.must_not_use_for_decision must be boolean"
            )
        if (status == "ok") != (must_not is False) or (http_status == 200) != (status == "ok"):
            raise Data03ReadinessEvidenceError(f"{field_name} status and gate disagree")
    elif (http_status == 200) != (status == "ok"):
        raise Data03ReadinessEvidenceError(f"{field_name} status and HTTP code disagree")
    checks = _json_value(raw["checks"], f"{field_name}.checks")
    if not isinstance(checks, Mapping):
        raise Data03ReadinessEvidenceError(f"{field_name}.checks must be an object")
    _check_defects(checks, f"{field_name}.checks")
    response: dict[str, object] = {
        "checks": dict(checks),
        "endpoint": endpoint,
        "http_status": http_status,
        "status": status,
        "timestamp": timestamp,
    }
    if decision:
        response["must_not_use_for_decision"] = raw["must_not_use_for_decision"]
    return response


def _smoke_checks(value: object, *, captured_at: datetime) -> tuple[dict[str, object], ...]:
    """Validate canonical read-only smoke check records."""

    if not isinstance(value, list) or not value:
        raise Data03ReadinessEvidenceError("smoke_checks must be a non-empty array")
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        raw = _mapping(item, f"smoke_checks[{index}]")
        _exact_keys(raw, _SMOKE_KEYS, f"smoke_checks[{index}]")
        key = _token(raw["key"], f"smoke_checks[{index}].key")
        if key in seen:
            raise Data03ReadinessEvidenceError("smoke_checks keys must be unique")
        seen.add(key)
        observed_at = _utc(raw["observed_at"], f"smoke_checks[{index}].observed_at")
        if observed_at > captured_at:
            raise Data03ReadinessEvidenceError(
                f"smoke_checks[{index}].observed_at is from the future"
            )
        records.append(
            {
                "detail": _json_value(raw["detail"], f"smoke_checks[{index}].detail"),
                "key": key,
                "observed_at": observed_at,
                "status": _status(raw["status"], _SMOKE_STATUSES, f"smoke_checks[{index}].status"),
            }
        )
    if [str(item["key"]) for item in records] != sorted(str(item["key"]) for item in records):
        raise Data03ReadinessEvidenceError("smoke_checks must be sorted by key")
    return tuple(records)


def parse_data03_readiness_snapshot(
    payload: bytes,
    *,
    as_of: datetime | None = None,
) -> Data03ReadinessEvidence:
    """Parse externally captured readiness probes without touching a service."""

    if type(payload) is not bytes or not payload:
        raise Data03ReadinessEvidenceError("payload must be non-empty bytes")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Data03ReadinessEvidenceError("payload must be UTF-8 JSON") from exc
    raw = _mapping(decoded, "evidence")
    _exact_keys(raw, _TOP_LEVEL_KEYS, "evidence")
    if raw["read_mode"] != "http_get_read_only":
        raise Data03ReadinessEvidenceError("read_mode must be http_get_read_only")
    candidate = _candidate(raw["candidate"])
    raw_observations = raw["observations"]
    if not isinstance(raw_observations, list) or not raw_observations:
        raise Data03ReadinessEvidenceError("observations must be a non-empty array")
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(0):
        raise Data03ReadinessEvidenceError("as_of must use UTC")
    probes: list[Data03Probe] = []
    previous_captured_at: datetime | None = None
    for index, item in enumerate(raw_observations):
        field_name = f"observations[{index}]"
        observation = _mapping(item, field_name)
        _exact_keys(observation, _OBSERVATION_KEYS, field_name)
        captured_at = _utc(observation["captured_at"], f"{field_name}.captured_at")
        if captured_at > cutoff:
            raise Data03ReadinessEvidenceError(f"{field_name}.captured_at is from the future")
        if previous_captured_at is not None and captured_at <= previous_captured_at:
            raise Data03ReadinessEvidenceError("observations must be strictly chronological")
        previous_captured_at = captured_at
        sample_candidate = _candidate(observation["candidate"], f"{field_name}.candidate")
        if sample_candidate != candidate:
            raise Data03ReadinessEvidenceError("candidate drift detected across observations")
        service = _response(
            observation["service"],
            field_name=f"{field_name}.service",
            decision=False,
            captured_at=captured_at,
        )
        decision = _response(
            observation["decision"],
            field_name=f"{field_name}.decision",
            decision=True,
            captured_at=captured_at,
        )
        probes.append(
            Data03Probe(
                captured_at=captured_at,
                candidate=sample_candidate,
                service=service,
                decision=decision,
                smoke_checks=_smoke_checks(observation["smoke_checks"], captured_at=captured_at),
            )
        )
    return Data03ReadinessEvidence(
        candidate=candidate, read_mode="http_get_read_only", probes=tuple(probes)
    )


def serialize_data03_readiness_evidence(report: Data03ReadinessEvidence) -> bytes:
    """Serialize canonical DATA-03 evidence with stable JSON bytes."""

    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def data03_readiness_artifact_sha256(payload: bytes) -> str:
    """Return the content address for one canonical DATA-03 artifact."""

    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "Data03Probe",
    "Data03ReadinessEvidence",
    "Data03ReadinessEvidenceError",
    "data03_readiness_artifact_sha256",
    "parse_data03_readiness_snapshot",
    "serialize_data03_readiness_evidence",
]
