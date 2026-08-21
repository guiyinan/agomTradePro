"""Fail-closed contract for candidate-bound TAR-01 chaos observations.

This module deliberately stops at the Application boundary.  It validates and
serializes observations supplied by an injected port; it does not start a
worker, contact Redis/Celery/Docker, send HTTP traffic, or inject a fault.  A
future controlled adapter must provide the same immutable candidate identity
at every boundary and must preserve unavailable/failed observations instead of
turning them into zeroes or a passing result.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol, TypeVar

from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix_digest,
)


class TerminalRuntimeChaosEvidenceError(ValueError):
    """Raised when chaos evidence is malformed, substituted, or incomplete."""


class TerminalRuntimeChaosObservationError(TerminalRuntimeChaosEvidenceError):
    """Raised when an injected observer crosses the chaos contract boundary."""


class TerminalRuntimeChaosStatus(StrEnum):
    """Whether a requested fault observation produced usable evidence."""

    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class TerminalRuntimeChaosWorkerStatus(StrEnum):
    """Worker state recorded after a controlled fault."""

    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTED = "restarted"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class TerminalRuntimeChaosRunStatus(StrEnum):
    """Terminal run state recorded by a chaos observer."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"


class TerminalRuntimeChaosStreamStatus(StrEnum):
    """SSE/event-stream state recorded by a chaos observer."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTED = "reconnected"
    TERMINAL_REPLAYED = "terminal_replayed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class TerminalRuntimeChaosRecoveryStatus(StrEnum):
    """Whether the run/worker/stream recovered after the fault."""

    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_OCI_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")
_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_MARKERS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "password",
    "prompt",
    "secret",
    "token",
)


def _safe_token(value: object, field_name: str) -> str:
    """Require a bounded token and reject common secret-bearing values."""

    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} must be a stable token")
    lowered = value.casefold()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} must not contain secret material")
    return value


def _require_utc(value: object, field_name: str) -> datetime:
    """Require an aware UTC timestamp; naive or non-UTC clocks are rejected."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} must use UTC")
    return value.astimezone(UTC)


def _require_non_negative_int(value: object, field_name: str) -> int:
    """Require a JSON-like non-negative integer without bool coercion."""

    if type(value) is not int or value < 0:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} must be a non-negative integer")
    return value


def _require_exact_keys(value: Mapping[str, object], expected: set[str], field_name: str) -> None:
    """Reject omitted and smuggled fields at every serialized boundary."""

    if set(value) != expected:
        raise TerminalRuntimeChaosEvidenceError(
            f"{field_name} keys must be exactly {sorted(expected)}"
        )


def _validated_enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    """Reject plain strings and enum values from an unrelated status family."""

    if type(value) is not enum_type:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} status type is invalid")
    return value


@dataclass(frozen=True, slots=True)
class TerminalRuntimeChaosCandidate:
    """Immutable source/release/OCI/matrix identity for one chaos run."""

    candidate_commit: str
    candidate_release: str
    oci_revision: str
    test_matrix_digest: str

    def __post_init__(self) -> None:
        """Validate every candidate component, including the live matrix digest."""

        if (
            type(self.candidate_commit) is not str
            or _COMMIT_RE.fullmatch(self.candidate_commit) is None
        ):
            raise TerminalRuntimeChaosEvidenceError("candidate_commit is invalid")
        if type(self.candidate_release) is not str or not re.fullmatch(
            r"\d{14}", self.candidate_release
        ):
            raise TerminalRuntimeChaosEvidenceError("candidate_release is invalid")
        if type(self.oci_revision) is not str or _OCI_RE.fullmatch(self.oci_revision) is None:
            raise TerminalRuntimeChaosEvidenceError("oci_revision is invalid")
        if (
            type(self.test_matrix_digest) is not str
            or _DIGEST_RE.fullmatch(self.test_matrix_digest) is None
        ):
            raise TerminalRuntimeChaosEvidenceError("test_matrix_digest is invalid")
        if self.test_matrix_digest != canonical_terminal_runtime_test_matrix_digest():
            raise TerminalRuntimeChaosEvidenceError(
                "test_matrix_digest does not match the canonical matrix"
            )

    def validate(self) -> None:
        """Revalidate an identity after it crossed an injected boundary."""

        self.__post_init__()


# The longer name is useful at call sites that deal with multiple evidence
# families.  It intentionally remains the same immutable type.
TerminalRuntimeChaosEvidenceBinding = TerminalRuntimeChaosCandidate


def _validated_candidate(value: object) -> TerminalRuntimeChaosCandidate:
    """Reconstruct a candidate so forged ``object.__new__`` values fail closed."""

    if type(value) is not TerminalRuntimeChaosCandidate:
        raise TerminalRuntimeChaosEvidenceError("candidate identity is invalid or forged")
    try:
        candidate = TerminalRuntimeChaosCandidate(
            candidate_commit=value.candidate_commit,
            candidate_release=value.candidate_release,
            oci_revision=value.oci_revision,
            test_matrix_digest=value.test_matrix_digest,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise TerminalRuntimeChaosEvidenceError("candidate identity is invalid or forged") from exc
    if candidate != value:
        raise TerminalRuntimeChaosEvidenceError("candidate identity is invalid or forged")
    return candidate


@dataclass(frozen=True, slots=True)
class TerminalRuntimeChaosTimelineEvent:
    """One secret-free event in a strictly non-decreasing UTC timeline."""

    sequence: int
    occurred_at: datetime
    event: str

    def __post_init__(self) -> None:
        """Validate sequence, UTC clock, and event vocabulary boundary."""

        _require_non_negative_int(self.sequence, "timeline.sequence")
        if self.sequence == 0:
            raise TerminalRuntimeChaosEvidenceError("timeline.sequence must be positive")
        _require_utc(self.occurred_at, "timeline.occurred_at")
        _safe_token(self.event, "timeline.event")


@dataclass(frozen=True, slots=True)
class TerminalRuntimeChaosState:
    """Worker, durable run, stream, and recovery statuses for one fault."""

    worker_status: TerminalRuntimeChaosWorkerStatus
    run_status: TerminalRuntimeChaosRunStatus
    stream_status: TerminalRuntimeChaosStreamStatus
    recovery_status: TerminalRuntimeChaosRecoveryStatus

    def __post_init__(self) -> None:
        """Reject status strings or values from an unrelated status family."""

        _validated_enum(self.worker_status, TerminalRuntimeChaosWorkerStatus, "worker_status")
        _validated_enum(self.run_status, TerminalRuntimeChaosRunStatus, "run_status")
        _validated_enum(self.stream_status, TerminalRuntimeChaosStreamStatus, "stream_status")
        _validated_enum(self.recovery_status, TerminalRuntimeChaosRecoveryStatus, "recovery_status")


@dataclass(frozen=True, slots=True)
class TerminalRuntimeChaosCounters:
    """Counters whose absence must never be interpreted as zero."""

    reconnect_attempts: int
    reconnect_successes: int
    terminal_overwrites: int
    duplicate_non_idempotent_side_effects: int
    cross_user_leaks: int

    def __post_init__(self) -> None:
        """Validate non-negative counters and reconnect conservation."""

        for field_name in (
            "reconnect_attempts",
            "reconnect_successes",
            "terminal_overwrites",
            "duplicate_non_idempotent_side_effects",
            "cross_user_leaks",
        ):
            _require_non_negative_int(getattr(self, field_name), f"counters.{field_name}")
        if self.reconnect_successes > self.reconnect_attempts:
            raise TerminalRuntimeChaosEvidenceError(
                "counters.reconnect_successes cannot exceed reconnect_attempts"
            )

    @property
    def all_safety_counters_zero(self) -> bool:
        """Return true only when duplicate, overwrite, and isolation counters are zero."""

        return (
            self.terminal_overwrites == 0
            and self.duplicate_non_idempotent_side_effects == 0
            and self.cross_user_leaks == 0
        )


@dataclass(frozen=True, slots=True)
class TerminalRuntimeChaosObservation:
    """One candidate-bound fault result with explicit unavailable semantics."""

    scenario_id: str
    fault: str
    status: TerminalRuntimeChaosStatus
    environment: str
    candidate_identity: TerminalRuntimeChaosCandidate
    started_at: datetime
    completed_at: datetime | None
    state: TerminalRuntimeChaosState | None
    counters: TerminalRuntimeChaosCounters | None
    timeline: tuple[TerminalRuntimeChaosTimelineEvent, ...]
    reason: str | None = None

    def __post_init__(self) -> None:
        """Validate an observed result or an explicit unavailable/failed result."""

        _safe_token(self.scenario_id, "scenario_id")
        _safe_token(self.fault, "fault")
        _validated_enum(self.status, TerminalRuntimeChaosStatus, "status")
        _safe_token(self.environment, "environment")
        _validated_candidate(self.candidate_identity)
        started_at = _require_utc(self.started_at, "started_at")
        if type(self.timeline) is not tuple:
            raise TerminalRuntimeChaosEvidenceError("timeline must be an immutable tuple")
        previous_sequence: int | None = None
        previous_at = started_at
        for event in self.timeline:
            if type(event) is not TerminalRuntimeChaosTimelineEvent:
                raise TerminalRuntimeChaosEvidenceError("timeline contains an invalid event")
            event.__post_init__()
            if previous_sequence is not None and event.sequence <= previous_sequence:
                raise TerminalRuntimeChaosEvidenceError("timeline sequence must be increasing")
            occurred_at = _require_utc(event.occurred_at, "timeline.occurred_at")
            if occurred_at < previous_at:
                raise TerminalRuntimeChaosEvidenceError("timeline timestamps must be monotonic")
            previous_sequence = event.sequence
            previous_at = occurred_at

        if self.status is TerminalRuntimeChaosStatus.OBSERVED:
            if self.reason is not None:
                raise TerminalRuntimeChaosEvidenceError("observed evidence cannot carry a reason")
            if self.completed_at is None:
                raise TerminalRuntimeChaosEvidenceError("observed evidence requires completed_at")
            completed_at = _require_utc(self.completed_at, "completed_at")
            if completed_at < started_at:
                raise TerminalRuntimeChaosEvidenceError("completed_at precedes started_at")
            if self.state is None or type(self.state) is not TerminalRuntimeChaosState:
                raise TerminalRuntimeChaosEvidenceError("observed evidence requires state")
            if self.counters is None or type(self.counters) is not TerminalRuntimeChaosCounters:
                raise TerminalRuntimeChaosEvidenceError("observed evidence requires counters")
            self.state.__post_init__()
            self.counters.__post_init__()
            if not self.timeline:
                raise TerminalRuntimeChaosEvidenceError("observed evidence requires a timeline")
            if _require_utc(self.timeline[-1].occurred_at, "timeline.occurred_at") > completed_at:
                raise TerminalRuntimeChaosEvidenceError("timeline ends after completed_at")
        else:
            _safe_token(self.reason, "reason")
            if self.completed_at is not None:
                raise TerminalRuntimeChaosEvidenceError(
                    "unavailable/failed evidence cannot carry completed_at"
                )
            if self.state is not None or self.counters is not None or self.timeline:
                raise TerminalRuntimeChaosEvidenceError(
                    "unavailable/failed evidence cannot carry partial measurements"
                )


@dataclass(frozen=True, slots=True)
class TerminalRuntimeChaosEvidenceReport:
    """A collection of chaos observations that cannot enable runtime by itself."""

    environment: str
    candidate_identity: TerminalRuntimeChaosCandidate
    collected_at: datetime
    observations: tuple[TerminalRuntimeChaosObservation, ...]

    def __post_init__(self) -> None:
        """Require one immutable candidate/environment across every observation."""

        _safe_token(self.environment, "environment")
        candidate = _validated_candidate(self.candidate_identity)
        collected_at = _require_utc(self.collected_at, "collected_at")
        if type(self.observations) is not tuple or not self.observations:
            raise TerminalRuntimeChaosEvidenceError("observations must be a non-empty tuple")
        identities: set[tuple[str, str]] = set()
        for observation in self.observations:
            if type(observation) is not TerminalRuntimeChaosObservation:
                raise TerminalRuntimeChaosEvidenceError("observations contain an invalid item")
            observation.__post_init__()
            if observation.environment != self.environment:
                raise TerminalRuntimeChaosEvidenceError("observation environment changed")
            if observation.candidate_identity != candidate:
                raise TerminalRuntimeChaosEvidenceError("observation candidate changed")
            key = (observation.scenario_id, observation.fault)
            if key in identities:
                raise TerminalRuntimeChaosEvidenceError("duplicate scenario/fault observation")
            identities.add(key)
            if (
                observation.completed_at is not None
                and _require_utc(observation.completed_at, "completed_at") > collected_at
            ):
                raise TerminalRuntimeChaosEvidenceError("observation completes after collection")

    @property
    def ready_for_chaos_gate(self) -> bool:
        """Return true only for complete observed, recovered, zero-violation evidence."""

        return all(
            observation.status is TerminalRuntimeChaosStatus.OBSERVED
            and observation.state is not None
            and observation.state.recovery_status is TerminalRuntimeChaosRecoveryStatus.RECOVERED
            and observation.counters is not None
            and observation.counters.all_safety_counters_zero
            for observation in self.observations
        )

    def validate(self) -> None:
        """Revalidate a report after an untrusted observer boundary."""

        self.__post_init__()


def _candidate_payload(candidate: TerminalRuntimeChaosCandidate) -> dict[str, object]:
    """Serialize one already-validated candidate identity."""

    return {
        "candidate_commit": candidate.candidate_commit,
        "candidate_release": candidate.candidate_release,
        "oci_revision": candidate.oci_revision,
        "test_matrix_digest": candidate.test_matrix_digest,
    }


def _state_payload(state: TerminalRuntimeChaosState) -> dict[str, object]:
    """Serialize status state without arbitrary dynamic fields."""

    return {
        "worker_status": state.worker_status.value,
        "run_status": state.run_status.value,
        "stream_status": state.stream_status.value,
        "recovery_status": state.recovery_status.value,
    }


def _counter_payload(counters: TerminalRuntimeChaosCounters) -> dict[str, object]:
    """Serialize the fixed counter vocabulary."""

    return {
        "reconnect_attempts": counters.reconnect_attempts,
        "reconnect_successes": counters.reconnect_successes,
        "terminal_overwrites": counters.terminal_overwrites,
        "duplicate_non_idempotent_side_effects": counters.duplicate_non_idempotent_side_effects,
        "cross_user_leaks": counters.cross_user_leaks,
    }


def _utc_text(value: datetime) -> str:
    """Serialize an aware timestamp in canonical UTC form."""

    return (
        _require_utc(value, "timestamp").isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _observation_payload(observation: TerminalRuntimeChaosObservation) -> dict[str, object]:
    """Serialize one validated observation with explicit nulls for non-observed states."""

    return {
        "candidate": _candidate_payload(observation.candidate_identity),
        "completed_at": (
            _utc_text(observation.completed_at) if observation.completed_at is not None else None
        ),
        "counters": (
            _counter_payload(observation.counters) if observation.counters is not None else None
        ),
        "environment": observation.environment,
        "fault": observation.fault,
        "reason": observation.reason,
        "scenario_id": observation.scenario_id,
        "started_at": _utc_text(observation.started_at),
        "state": _state_payload(observation.state) if observation.state is not None else None,
        "status": observation.status.value,
        "timeline": [
            {
                "event": event.event,
                "occurred_at": _utc_text(event.occurred_at),
                "sequence": event.sequence,
            }
            for event in observation.timeline
        ],
    }


def serialize_terminal_runtime_chaos_evidence(
    report: TerminalRuntimeChaosEvidenceReport,
) -> bytes:
    """Serialize a validated report into deterministic, non-enabling JSON bytes."""

    if type(report) is not TerminalRuntimeChaosEvidenceReport:
        raise TerminalRuntimeChaosEvidenceError("report type is invalid")
    try:
        report.validate()
    except (AttributeError, TypeError, ValueError) as exc:
        raise TerminalRuntimeChaosEvidenceError("report failed canonical validation") from exc
    payload: dict[str, object] = {
        "artifact_type": "terminal_runtime_chaos_observation",
        "candidate": _candidate_payload(report.candidate_identity),
        "collected_at": _utc_text(report.collected_at),
        "environment": report.environment,
        "evidence_scope": "offline_chaos_observation",
        "observations": [_observation_payload(item) for item in report.observations],
        "runtime_enablement": "not_authorized",
        "schema": "terminal-runtime-chaos-observation.v1",
    }
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def terminal_runtime_chaos_artifact_sha256(payload: bytes) -> str:
    """Return the content-address for a serialized chaos artifact."""

    if type(payload) is not bytes or not payload:
        raise TerminalRuntimeChaosEvidenceError("artifact payload must be non-empty bytes")
    return hashlib.sha256(payload).hexdigest()


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow an untrusted JSON object without accepting non-string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} must be an object")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    """Narrow an untrusted JSON array."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} must be an array")
    return value


def _parse_timestamp(value: object, field_name: str) -> datetime:
    """Parse the serializer's strict UTC timestamp representation."""

    if type(value) is not str or not value.endswith("Z"):
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} must be a UTC timestamp") from exc
    return _require_utc(parsed, field_name)


def _parse_candidate(value: object, field_name: str) -> TerminalRuntimeChaosCandidate:
    """Parse and reconstruct a candidate identity from JSON."""

    candidate = _mapping(value, field_name)
    _require_exact_keys(
        candidate,
        {"candidate_commit", "candidate_release", "oci_revision", "test_matrix_digest"},
        field_name,
    )
    try:
        return TerminalRuntimeChaosCandidate(
            candidate_commit=_safe_token(
                candidate["candidate_commit"], f"{field_name}.candidate_commit"
            ),
            candidate_release=_safe_token(
                candidate["candidate_release"], f"{field_name}.candidate_release"
            ),
            oci_revision=_safe_token(candidate["oci_revision"], f"{field_name}.oci_revision"),
            test_matrix_digest=_safe_token(
                candidate["test_matrix_digest"], f"{field_name}.test_matrix_digest"
            ),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} is invalid") from exc


_E = TypeVar("_E", bound=StrEnum)


def _parse_enum(value: object, enum_type: type[_E], field_name: str) -> _E:
    """Parse one exact enum string from JSON."""

    if type(value) is not str:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} is invalid")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name} is invalid") from exc


def _parse_state(value: object, field_name: str) -> TerminalRuntimeChaosState:
    """Parse the fixed worker/run/stream/recovery state object."""

    state = _mapping(value, field_name)
    _require_exact_keys(
        state,
        {"worker_status", "run_status", "stream_status", "recovery_status"},
        field_name,
    )
    return TerminalRuntimeChaosState(
        worker_status=_parse_enum(
            state["worker_status"], TerminalRuntimeChaosWorkerStatus, f"{field_name}.worker_status"
        ),
        run_status=_parse_enum(
            state["run_status"], TerminalRuntimeChaosRunStatus, f"{field_name}.run_status"
        ),
        stream_status=_parse_enum(
            state["stream_status"], TerminalRuntimeChaosStreamStatus, f"{field_name}.stream_status"
        ),
        recovery_status=_parse_enum(
            state["recovery_status"],
            TerminalRuntimeChaosRecoveryStatus,
            f"{field_name}.recovery_status",
        ),
    )


def _parse_counters(value: object, field_name: str) -> TerminalRuntimeChaosCounters:
    """Parse the fixed reconnect/overwrite/duplicate/isolation counters."""

    counters = _mapping(value, field_name)
    _require_exact_keys(
        counters,
        {
            "reconnect_attempts",
            "reconnect_successes",
            "terminal_overwrites",
            "duplicate_non_idempotent_side_effects",
            "cross_user_leaks",
        },
        field_name,
    )
    return TerminalRuntimeChaosCounters(
        reconnect_attempts=_require_non_negative_int(
            counters["reconnect_attempts"], f"{field_name}.reconnect_attempts"
        ),
        reconnect_successes=_require_non_negative_int(
            counters["reconnect_successes"], f"{field_name}.reconnect_successes"
        ),
        terminal_overwrites=_require_non_negative_int(
            counters["terminal_overwrites"], f"{field_name}.terminal_overwrites"
        ),
        duplicate_non_idempotent_side_effects=_require_non_negative_int(
            counters["duplicate_non_idempotent_side_effects"],
            f"{field_name}.duplicate_non_idempotent_side_effects",
        ),
        cross_user_leaks=_require_non_negative_int(
            counters["cross_user_leaks"], f"{field_name}.cross_user_leaks"
        ),
    )


def _parse_timeline(
    value: object, field_name: str
) -> tuple[TerminalRuntimeChaosTimelineEvent, ...]:
    """Parse a timeline without accepting arbitrary event payloads."""

    raw_events = _sequence(value, field_name)
    events: list[TerminalRuntimeChaosTimelineEvent] = []
    for index, raw_event in enumerate(raw_events):
        event = _mapping(raw_event, f"{field_name}[{index}]")
        _require_exact_keys(event, {"event", "occurred_at", "sequence"}, f"{field_name}[{index}]")
        events.append(
            TerminalRuntimeChaosTimelineEvent(
                sequence=_require_non_negative_int(
                    event["sequence"], f"{field_name}[{index}].sequence"
                ),
                occurred_at=_parse_timestamp(
                    event["occurred_at"], f"{field_name}[{index}].occurred_at"
                ),
                event=_safe_token(event["event"], f"{field_name}[{index}].event"),
            )
        )
    return tuple(events)


def _parse_observation(
    value: object,
    *,
    report_environment: str,
    report_candidate: TerminalRuntimeChaosCandidate,
    field_name: str,
) -> TerminalRuntimeChaosObservation:
    """Parse one observation and bind its duplicated identity to the report."""

    observation = _mapping(value, field_name)
    _require_exact_keys(
        observation,
        {
            "candidate",
            "completed_at",
            "counters",
            "environment",
            "fault",
            "reason",
            "scenario_id",
            "started_at",
            "state",
            "status",
            "timeline",
        },
        field_name,
    )
    candidate = _parse_candidate(observation["candidate"], f"{field_name}.candidate")
    if candidate != report_candidate:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name}.candidate changed")
    environment = _safe_token(observation["environment"], f"{field_name}.environment")
    if environment != report_environment:
        raise TerminalRuntimeChaosEvidenceError(f"{field_name}.environment changed")
    status = _parse_enum(observation["status"], TerminalRuntimeChaosStatus, f"{field_name}.status")
    raw_reason = observation["reason"]
    if raw_reason is not None:
        raw_reason = _safe_token(raw_reason, f"{field_name}.reason")
    raw_completed = observation["completed_at"]
    completed_at = (
        None
        if raw_completed is None
        else _parse_timestamp(raw_completed, f"{field_name}.completed_at")
    )
    raw_state = observation["state"]
    state = None if raw_state is None else _parse_state(raw_state, f"{field_name}.state")
    raw_counters = observation["counters"]
    counters = (
        None if raw_counters is None else _parse_counters(raw_counters, f"{field_name}.counters")
    )
    return TerminalRuntimeChaosObservation(
        scenario_id=_safe_token(observation["scenario_id"], f"{field_name}.scenario_id"),
        fault=_safe_token(observation["fault"], f"{field_name}.fault"),
        status=status,
        environment=environment,
        candidate_identity=candidate,
        started_at=_parse_timestamp(observation["started_at"], f"{field_name}.started_at"),
        completed_at=completed_at,
        state=state,
        counters=counters,
        timeline=_parse_timeline(observation["timeline"], f"{field_name}.timeline"),
        reason=raw_reason,
    )


def validate_terminal_runtime_chaos_evidence(
    payload: Mapping[str, object],
    *,
    expected_candidate: TerminalRuntimeChaosCandidate | None = None,
) -> TerminalRuntimeChaosEvidenceReport:
    """Validate a serialized report and optionally bind it to an expected candidate.

    Passing ``expected_candidate`` is required for a gate decision; omitting it
    is useful only for structural round-trip tests and does not establish an
    external release authority.
    """

    _require_exact_keys(
        payload,
        {
            "artifact_type",
            "candidate",
            "collected_at",
            "environment",
            "evidence_scope",
            "observations",
            "runtime_enablement",
            "schema",
        },
        "evidence",
    )
    if payload["schema"] != "terminal-runtime-chaos-observation.v1":
        raise TerminalRuntimeChaosEvidenceError("unsupported evidence schema")
    if payload["artifact_type"] != "terminal_runtime_chaos_observation":
        raise TerminalRuntimeChaosEvidenceError("artifact_type is inconsistent")
    if payload["evidence_scope"] != "offline_chaos_observation":
        raise TerminalRuntimeChaosEvidenceError("evidence_scope is inconsistent")
    if payload["runtime_enablement"] != "not_authorized":
        raise TerminalRuntimeChaosEvidenceError(
            "chaos evidence cannot authorize runtime enablement"
        )
    environment = _safe_token(payload["environment"], "environment")
    candidate = _parse_candidate(payload["candidate"], "candidate")
    if expected_candidate is not None:
        expected = _validated_candidate(expected_candidate)
        if candidate != expected:
            raise TerminalRuntimeChaosEvidenceError("evidence candidate does not match expected")
    raw_observations = _sequence(payload["observations"], "observations")
    observations = tuple(
        _parse_observation(
            item,
            report_environment=environment,
            report_candidate=candidate,
            field_name=f"observations[{index}]",
        )
        for index, item in enumerate(raw_observations)
    )
    try:
        return TerminalRuntimeChaosEvidenceReport(
            environment=environment,
            candidate_identity=candidate,
            collected_at=_parse_timestamp(payload["collected_at"], "collected_at"),
            observations=observations,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise TerminalRuntimeChaosEvidenceError(
            "evidence report failed canonical validation"
        ) from exc


@dataclass(frozen=True, slots=True)
class TerminalRuntimeChaosObservationRequest:
    """Immutable request sent to a future controlled observer port."""

    environment: str
    candidate_identity: TerminalRuntimeChaosCandidate
    scenario_id: str
    fault: str

    def __post_init__(self) -> None:
        """Validate request identity before any port call is made."""

        _safe_token(self.environment, "environment")
        _validated_candidate(self.candidate_identity)
        _safe_token(self.scenario_id, "scenario_id")
        _safe_token(self.fault, "fault")


class TerminalRuntimeChaosObservationPort(Protocol):
    """Port implemented by an explicitly authorized external/fake observer."""

    def observe(
        self,
        request: TerminalRuntimeChaosObservationRequest,
    ) -> TerminalRuntimeChaosObservation:
        """Return one candidate-bound observation without changing its identity."""

        ...


class TerminalRuntimeChaosControlledObserver:
    """Validate observations from an injected port without performing I/O."""

    def __init__(self, port: TerminalRuntimeChaosObservationPort) -> None:
        """Create an observer around one explicitly injected port."""

        self._port = port

    def observe(
        self,
        request: TerminalRuntimeChaosObservationRequest,
    ) -> TerminalRuntimeChaosObservation:
        """Call the port once and reject candidate/environment substitution."""

        if type(request) is not TerminalRuntimeChaosObservationRequest:
            raise TerminalRuntimeChaosObservationError("observation request type is invalid")
        request.__post_init__()
        raw = self._port.observe(request)
        if type(raw) is not TerminalRuntimeChaosObservation:
            raise TerminalRuntimeChaosObservationError("observation port returned invalid evidence")
        try:
            validated = TerminalRuntimeChaosObservation(
                scenario_id=raw.scenario_id,
                fault=raw.fault,
                status=raw.status,
                environment=raw.environment,
                candidate_identity=raw.candidate_identity,
                started_at=raw.started_at,
                completed_at=raw.completed_at,
                state=raw.state,
                counters=raw.counters,
                timeline=raw.timeline,
                reason=raw.reason,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise TerminalRuntimeChaosObservationError(
                "observation port returned invalid evidence"
            ) from exc
        if validated != raw:
            raise TerminalRuntimeChaosObservationError("observation port returned forged evidence")
        if validated.environment != request.environment:
            raise TerminalRuntimeChaosObservationError("observation environment changed")
        if validated.candidate_identity != request.candidate_identity:
            raise TerminalRuntimeChaosObservationError("observation candidate changed")
        if validated.scenario_id != request.scenario_id or validated.fault != request.fault:
            raise TerminalRuntimeChaosObservationError("observation scenario or fault changed")
        return validated

    def collect(
        self,
        requests: tuple[TerminalRuntimeChaosObservationRequest, ...],
        *,
        collected_at: datetime,
    ) -> TerminalRuntimeChaosEvidenceReport:
        """Collect explicit requests and preserve unavailable/failed results."""

        if type(requests) is not tuple or not requests:
            raise TerminalRuntimeChaosObservationError("requests must be a non-empty tuple")
        for request in requests:
            if type(request) is not TerminalRuntimeChaosObservationRequest:
                raise TerminalRuntimeChaosObservationError("requests contain an invalid item")
            request.__post_init__()
        first = requests[0]
        observations = tuple(self.observe(request) for request in requests)
        try:
            return TerminalRuntimeChaosEvidenceReport(
                environment=first.environment,
                candidate_identity=first.candidate_identity,
                collected_at=collected_at,
                observations=observations,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise TerminalRuntimeChaosObservationError(
                "controlled chaos collection failed canonical validation"
            ) from exc
