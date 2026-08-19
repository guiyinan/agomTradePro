"""Strict offline observer for controlled Terminal runtime snapshots.

The observer consumes a previously captured JSON bundle.  It deliberately
does not perform HTTP, process, broker, database, Celery, or Agent work; a
separate controlled harness must create the bundle and preserve its bytes.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineCandidate,
    TerminalRuntimeBaselineContractError,
    TerminalRuntimeBaselineMetric,
    TerminalRuntimeBaselineMetricStatus,
    TerminalRuntimeBaselineSample,
)
from apps.agent_runtime.application.terminal_runtime_baseline_collector import (
    TerminalRuntimeBaselineCollectionRequest,
    TerminalRuntimeBaselineObservationError,
    TerminalRuntimeBaselineObservationPort,
    TerminalRuntimeBaselineObservationRequest,
)
from apps.agent_runtime.application.terminal_runtime_slo import (
    TerminalRuntimeSloMeasurement,
    TerminalRuntimeSloReport,
    TerminalRuntimeSloStatus,
)

MAX_SNAPSHOT_BYTES: Final[int] = 2 * 1024 * 1024
_FORMAT: Final[str] = "terminal-runtime-baseline-snapshot.v1"
_TOP_KEYS: Final[frozenset[str]] = frozenset(
    {"format", "environment", "candidate", "samples", "slo_report", "source"}
)
_CANDIDATE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "candidate_commit",
        "candidate_release",
        "oci_revision",
        "runtime_manifest_digest",
        "test_matrix_digest",
    }
)
_SAMPLE_KEYS: Final[frozenset[str]] = frozenset({"sample_count", "captured_at", "metrics"})
_METRIC_KEYS: Final[frozenset[str]] = frozenset({"key", "status", "value", "reason"})
_SLO_KEYS: Final[frozenset[str]] = frozenset({"captured_at", "measurements"})
_SOURCE_KEYS: Final[frozenset[str]] = frozenset({"kind"})
_FORBIDDEN_KEY_PARTS: Final[tuple[str, ...]] = (
    "prompt",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "session",
    "token",
)


class TerminalRuntimeSnapshotError(TerminalRuntimeBaselineObservationError):
    """Raised when an offline snapshot is not an exact v1 bundle."""


class TerminalRuntimeBaselineSnapshotSource(Protocol):
    """Read immutable snapshot bytes without performing remote I/O."""

    def read(self) -> bytes:
        """Return the exact source bytes."""

        ...


@dataclass(frozen=True, slots=True)
class JsonSnapshotSource:
    """Read a bounded JSON file or bytes supplied by an external harness."""

    payload: bytes | Path

    def read(self) -> bytes:
        """Return bounded bytes, rejecting oversized input."""

        if isinstance(self.payload, Path):
            data = self.payload.read_bytes()
        elif type(self.payload) is bytes:
            data = self.payload
        else:
            raise TerminalRuntimeSnapshotError("snapshot payload type is invalid")
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise TerminalRuntimeSnapshotError("snapshot payload exceeds size limit")
        return data


def _fail(message: str) -> TerminalRuntimeSnapshotError:
    """Build a stable, non-echoing parser error."""

    return TerminalRuntimeSnapshotError(message)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Require a JSON object with string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise _fail(f"{field_name} must be an object with string keys")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    """Reject missing and unknown object keys."""

    if set(value) != expected:
        raise _fail(f"{field_name} has an invalid key set")


def _token(value: object, field_name: str) -> str:
    """Require a bounded token without whitespace."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
        or len(value) > 256
    ):
        raise _fail(f"{field_name} is invalid")
    return value


def _aware_time(value: object, field_name: str) -> datetime:
    """Parse an aware UTC timestamp without accepting local-time ambiguity."""

    if type(value) is not str or not value.endswith("Z"):
        raise _fail(f"{field_name} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _fail(f"{field_name} is invalid") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != UTC.utcoffset(parsed)
    ):
        raise _fail(f"{field_name} must be UTC")
    return parsed


def _number(value: object, field_name: str) -> float | int:
    """Require a finite non-negative JSON number and reject bool."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(f"{field_name} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise _fail(f"{field_name} must be finite and non-negative")
    return value


def _walk_forbidden(value: object, path: str = "root") -> None:
    """Reject secret-bearing keys anywhere in the untrusted JSON tree."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if type(key) is not str:
                raise _fail("snapshot contains a non-string key")
            normalized = key.casefold().replace("-", "_")
            if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                raise _fail("snapshot contains a forbidden field")
            _walk_forbidden(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _walk_forbidden(nested, f"{path}[{index}]")


def _parse_metric(value: object) -> TerminalRuntimeBaselineMetric:
    """Parse one baseline metric through the canonical Domain contract."""

    raw = _mapping(value, "metric")
    _exact_keys(raw, _METRIC_KEYS, "metric")
    try:
        status = TerminalRuntimeBaselineMetricStatus(_token(raw["status"], "metric.status"))
        metric_value = raw["value"]
        if metric_value is not None:
            metric_value = _number(metric_value, "metric.value")
        reason = raw["reason"]
        if reason is not None:
            reason = _token(reason, "metric.reason")
        return TerminalRuntimeBaselineMetric(
            key=_token(raw["key"], "metric.key"),
            status=status,
            value=metric_value,
            reason=reason,
        )
    except (AttributeError, TypeError, ValueError, TerminalRuntimeBaselineContractError) as exc:
        raise _fail("metric failed canonical validation") from exc


def _parse_slo_measurement(value: object) -> TerminalRuntimeSloMeasurement:
    """Parse one hard-SLO measurement through its canonical contract."""

    raw = _mapping(value, "slo measurement")
    _exact_keys(raw, _METRIC_KEYS, "slo measurement")
    try:
        status = TerminalRuntimeSloStatus(_token(raw["status"], "slo.status"))
        measurement_value = raw["value"]
        if measurement_value is not None:
            measurement_value = _number(measurement_value, "slo.value")
        reason = raw["reason"]
        if reason is not None:
            reason = _token(reason, "slo.reason")
        return TerminalRuntimeSloMeasurement(
            key=_token(raw["key"], "slo.key"),
            status=status,
            value=measurement_value,
            reason=reason,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise _fail("hard SLO measurement failed canonical validation") from exc


class TerminalRuntimeBaselineSnapshotObserver(TerminalRuntimeBaselineObservationPort):
    """Implement the baseline observer Protocol from one immutable JSON bundle."""

    def __init__(self, source: TerminalRuntimeBaselineSnapshotSource) -> None:
        """Parse and validate the source once, retaining no raw secret payload."""

        raw_bytes = source.read()
        if len(raw_bytes) > MAX_SNAPSHOT_BYTES:
            raise _fail("snapshot payload exceeds size limit")
        self.source_payload_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        try:
            decoded = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _fail("snapshot payload is not valid UTF-8 JSON") from exc
        _walk_forbidden(decoded)
        top = _mapping(decoded, "snapshot")
        _exact_keys(top, _TOP_KEYS, "snapshot")
        if top["format"] != _FORMAT:
            raise _fail("snapshot format is unsupported")
        self._environment = _token(top["environment"], "environment")

        candidate_raw = _mapping(top["candidate"], "candidate")
        _exact_keys(candidate_raw, _CANDIDATE_KEYS, "candidate")
        try:
            self._candidate = TerminalRuntimeBaselineCandidate(
                candidate_commit=_token(candidate_raw["candidate_commit"], "candidate_commit"),
                candidate_release=_token(candidate_raw["candidate_release"], "candidate_release"),
                oci_revision=_token(candidate_raw["oci_revision"], "oci_revision"),
                runtime_manifest_digest=_token(
                    candidate_raw["runtime_manifest_digest"], "runtime_manifest_digest"
                ),
                test_matrix_digest=_token(
                    candidate_raw["test_matrix_digest"], "test_matrix_digest"
                ),
            )
        except (TypeError, ValueError, TerminalRuntimeBaselineContractError) as exc:
            raise _fail("candidate failed canonical validation") from exc

        samples_raw = _mapping(top["samples"], "samples")
        if set(samples_raw) != {"1", "5", "10", "20"}:
            raise _fail("samples must contain exactly 1, 5, 10, and 20")
        self._samples: dict[int, TerminalRuntimeBaselineSample] = {}
        for level_text, sample_value in samples_raw.items():
            sample_raw = _mapping(sample_value, f"sample {level_text}")
            _exact_keys(sample_raw, _SAMPLE_KEYS, f"sample {level_text}")
            try:
                sample_count = sample_raw["sample_count"]
                if type(sample_count) is not int or sample_count <= 0:
                    raise _fail("sample_count is invalid")
                metrics_raw = sample_raw["metrics"]
                if not isinstance(metrics_raw, list):
                    raise _fail("sample metrics must be a list")
                sample = TerminalRuntimeBaselineSample(
                    environment=self._environment,
                    candidate_commit=self._candidate.candidate_commit,
                    candidate_release=self._candidate.candidate_release,
                    concurrency=int(level_text),
                    sample_count=sample_count,
                    captured_at=_aware_time(sample_raw["captured_at"], "captured_at"),
                    metrics=tuple(_parse_metric(item) for item in metrics_raw),
                    candidate_identity=self._candidate,
                )
            except (TypeError, ValueError, TerminalRuntimeBaselineContractError) as exc:
                raise _fail(f"sample {level_text} failed canonical validation") from exc
            self._samples[int(level_text)] = sample

        slo_raw = _mapping(top["slo_report"], "slo_report")
        _exact_keys(slo_raw, _SLO_KEYS, "slo_report")
        measurements_raw = slo_raw["measurements"]
        if not isinstance(measurements_raw, list):
            raise _fail("slo measurements must be a list")
        try:
            self._slo_report = TerminalRuntimeSloReport(
                environment=self._environment,
                candidate_commit=self._candidate.candidate_commit,
                candidate_release=self._candidate.candidate_release,
                oci_revision=self._candidate.oci_revision,
                runtime_manifest_digest=self._candidate.runtime_manifest_digest,
                test_matrix_digest=self._candidate.test_matrix_digest,
                captured_at=_aware_time(slo_raw["captured_at"], "slo captured_at"),
                measurements=tuple(_parse_slo_measurement(item) for item in measurements_raw),
            )
        except (TypeError, ValueError) as exc:
            raise _fail("slo report failed canonical validation") from exc

        source_raw = _mapping(top["source"], "source")
        _exact_keys(source_raw, _SOURCE_KEYS, "source")
        _token(source_raw["kind"], "source.kind")

    @property
    def candidate(self) -> TerminalRuntimeBaselineCandidate:
        """Return the validated immutable candidate identity."""

        return self._candidate

    @property
    def environment(self) -> str:
        """Return the validated environment identity."""

        return self._environment

    def observe(
        self, request: TerminalRuntimeBaselineObservationRequest
    ) -> TerminalRuntimeBaselineSample:
        """Return the exact sample selected by an existing collection request."""

        if (
            request.environment != self._environment
            or request.candidate_identity != self._candidate
        ):
            raise TerminalRuntimeSnapshotError("snapshot identity does not match request")
        try:
            return self._samples[request.concurrency]
        except KeyError as exc:
            raise TerminalRuntimeSnapshotError("snapshot concurrency is unavailable") from exc

    def observe_slo(
        self, request: TerminalRuntimeBaselineCollectionRequest
    ) -> TerminalRuntimeSloReport:
        """Return the exact hard-SLO report selected by an existing collection request."""

        if (
            request.environment != self._environment
            or request.candidate_identity != self._candidate
        ):
            raise TerminalRuntimeSnapshotError("snapshot identity does not match request")
        return self._slo_report


def canonical_snapshot_payload_sha256(payload: bytes) -> str:
    """Return the digest used to bind an external snapshot payload."""

    if type(payload) is not bytes or len(payload) > MAX_SNAPSHOT_BYTES:
        raise TerminalRuntimeSnapshotError("snapshot payload is invalid")
    return hashlib.sha256(payload).hexdigest()
