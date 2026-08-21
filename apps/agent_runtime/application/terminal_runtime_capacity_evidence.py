"""Fail-closed validation for candidate-bound TAR-01 capacity evidence.

The capacity artifact records a deliberately bounded production observation.  It
is evidence of queue admission, idempotency, worker recovery, and SSE error
replay; it is not a capacity acceptance or production-readiness attestation.
This module performs only structural and semantic validation of JSON-shaped
data.  It does not perform network, ORM, Celery, broker, or Agent I/O.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final


class TerminalRuntimeCapacityEvidenceError(ValueError):
    """Raised when candidate-bound capacity evidence is incomplete or altered."""


@dataclass(frozen=True, slots=True)
class TerminalRuntimeCapacityEvidenceBinding:
    """Immutable candidate identity expected by the governance manifest."""

    candidate_commit: str
    release: str
    image: str


@dataclass(frozen=True, slots=True)
class TerminalRuntimeCapacityEvidenceReport:
    """Validated summary that cannot be used to close TAR-01."""

    candidate_commit: str
    candidate_release: str
    image_id: str
    accepted_runs: int
    rejected_runs: int
    level_count: int
    idempotency_verified: bool
    worker_recovery_verified: bool
    sse_verified: bool
    cleanup_verified: bool
    decision: str
    safety_ready: bool
    capacity_ready: bool


_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_TAG_RE: Final[re.Pattern[str]] = re.compile(r"^agomtradepro-web:\S+$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_OBSERVED_AT_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LEVELS: Final[tuple[str, ...]] = ("1", "5", "10", "20")
_STATUS_CODES: Final[frozenset[str]] = frozenset({"202", "429"})
_REJECTION_REASON: Final[str] = "per_user_queued_limit"
_ERROR_CODE: Final[str] = "terminal_agent_execution_failed"


def _mapping(value: object, field: str) -> Mapping[str, object]:
    """Require a JSON object with string keys."""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TerminalRuntimeCapacityEvidenceError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    """Require a JSON array."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TerminalRuntimeCapacityEvidenceError(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    """Require a non-empty JSON string without surrounding whitespace."""

    if type(value) is not str or not value or value.strip() != value:
        raise TerminalRuntimeCapacityEvidenceError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
    """Require a JSON integer and reject bool-as-int coercion."""

    if type(value) is not int:
        raise TerminalRuntimeCapacityEvidenceError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise TerminalRuntimeCapacityEvidenceError(f"{field} must be >= {minimum}")
    return value


def _boolean(value: object, field: str) -> bool:
    """Require an actual JSON boolean."""

    if type(value) is not bool:
        raise TerminalRuntimeCapacityEvidenceError(f"{field} must be a boolean")
    return value


def _require_exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    """Reject omitted or smuggled fields in an evidence object."""

    if set(value) != expected:
        raise TerminalRuntimeCapacityEvidenceError(
            f"{field} keys must be exactly {sorted(expected)}"
        )


def _validate_binding(binding: TerminalRuntimeCapacityEvidenceBinding) -> None:
    """Validate the expected identity supplied by the governance manifest."""

    candidate_commit = _string(binding.candidate_commit, "expected.candidate_commit")
    if _COMMIT_RE.fullmatch(candidate_commit) is None:
        raise TerminalRuntimeCapacityEvidenceError("expected.candidate_commit is invalid")
    release = _string(binding.release, "expected.release")
    if not re.fullmatch(r"\d{14}", release):
        raise TerminalRuntimeCapacityEvidenceError("expected.release is invalid")
    image = _string(binding.image, "expected.image")
    if _SHA256_RE.fullmatch(image) is None and _IMAGE_TAG_RE.fullmatch(image) is None:
        raise TerminalRuntimeCapacityEvidenceError("expected.image is invalid")


def _validate_candidate(
    candidate: Mapping[str, object],
) -> tuple[str, str, str]:
    """Validate the artifact's immutable source, release, and image identity."""

    _require_exact_keys(
        candidate,
        {"branch", "source_commit", "release_tag", "image_id", "runtime_match"},
        "candidate",
    )
    _string(candidate["branch"], "candidate.branch")
    source_commit = _string(candidate["source_commit"], "candidate.source_commit")
    if _COMMIT_RE.fullmatch(source_commit) is None:
        raise TerminalRuntimeCapacityEvidenceError("candidate.source_commit is invalid")
    release = _string(candidate["release_tag"], "candidate.release_tag")
    if not re.fullmatch(r"\d{14}", release):
        raise TerminalRuntimeCapacityEvidenceError("candidate.release_tag is invalid")
    image_id = _string(candidate["image_id"], "candidate.image_id")
    if _SHA256_RE.fullmatch(image_id) is None:
        raise TerminalRuntimeCapacityEvidenceError("candidate.image_id is invalid")
    if _boolean(candidate["runtime_match"], "candidate.runtime_match") is not True:
        raise TerminalRuntimeCapacityEvidenceError("candidate runtime_match must be true")
    return source_commit, release, image_id


def _validate_authorization(
    authorization: Mapping[str, object],
    release: str,
) -> None:
    """Require temporary, bounded runtime authorization and exact worker image."""

    _require_exact_keys(
        authorization,
        {
            "terminal_runtime_authorized",
            "queued_intake_enabled",
            "queued_worker_enabled",
            "emergency_stop",
            "worker_image",
            "window",
            "restored_after_observation",
        },
        "authorization",
    )
    for key in (
        "terminal_runtime_authorized",
        "queued_intake_enabled",
        "queued_worker_enabled",
    ):
        if _boolean(authorization[key], f"authorization.{key}") is not True:
            raise TerminalRuntimeCapacityEvidenceError(
                f"authorization.{key} must be true for an observed canary"
            )
    if _boolean(authorization["emergency_stop"], "authorization.emergency_stop") is not False:
        raise TerminalRuntimeCapacityEvidenceError("authorization.emergency_stop must be false")
    worker_image = _string(authorization["worker_image"], "authorization.worker_image")
    if worker_image != f"agomtradepro-web:{release}":
        raise TerminalRuntimeCapacityEvidenceError("authorization.worker_image is inconsistent")
    if authorization["window"] != "controlled_observation_only":
        raise TerminalRuntimeCapacityEvidenceError("authorization.window is not bounded")
    if (
        _boolean(
            authorization["restored_after_observation"], "authorization.restored_after_observation"
        )
        is not True
    ):
        raise TerminalRuntimeCapacityEvidenceError(
            "authorization.restored_after_observation must be true"
        )


def _validate_actor(actor: Mapping[str, object]) -> None:
    """Prove that credentials were not retained in the artifact."""

    _require_exact_keys(
        actor,
        {"authentication", "actor", "secrets_recorded", "temporary_token_deleted"},
        "actor",
    )
    _string(actor["authentication"], "actor.authentication")
    _string(actor["actor"], "actor.actor")
    if _boolean(actor["secrets_recorded"], "actor.secrets_recorded") is not False:
        raise TerminalRuntimeCapacityEvidenceError("actor.secrets_recorded must be false")
    if _boolean(actor["temporary_token_deleted"], "actor.temporary_token_deleted") is not True:
        raise TerminalRuntimeCapacityEvidenceError("actor.temporary_token_deleted must be true")


def _validate_status_counts(
    counts: Mapping[str, object],
    expected_requests: int,
    field: str,
) -> tuple[int, int]:
    """Validate one level and return accepted/rejected response counts."""

    if not set(counts).issubset(_STATUS_CODES) or not counts:
        raise TerminalRuntimeCapacityEvidenceError(
            f"{field} keys must be a non-empty subset of 202/429"
        )
    accepted = 0
    rejected = 0
    for status, raw_count in counts.items():
        count = _integer(raw_count, f"{field}.{status}", minimum=0)
        if status == "202":
            accepted = count
        else:
            rejected = count
    if accepted + rejected != expected_requests:
        raise TerminalRuntimeCapacityEvidenceError(
            f"{field} counts must sum to {expected_requests}"
        )
    return accepted, rejected


def _validate_queue_snapshot(
    snapshot: Mapping[str, object],
    field: str,
    *,
    expected_queued: int | None = None,
) -> None:
    """Validate non-negative user/global queue counters."""

    _require_exact_keys(
        snapshot,
        {"user_active", "user_queued", "global_active", "global_queued"},
        field,
    )
    for key in ("user_active", "user_queued", "global_active", "global_queued"):
        _integer(snapshot[key], f"{field}.{key}", minimum=0)
    if expected_queued is not None and any(
        snapshot[key] != expected_queued for key in ("user_queued", "global_queued")
    ):
        raise TerminalRuntimeCapacityEvidenceError(
            f"{field} queued counters must equal accepted_runs"
        )


def _validate_capacity(capacity: Mapping[str, object]) -> tuple[int, int]:
    """Validate bounded admission counts and queue conservation."""

    _require_exact_keys(
        capacity,
        {
            "worker_stopped_during_submission",
            "levels",
            "accepted_runs",
            "rejected_runs",
            "rejection_reason",
            "queue_after_submit",
            "queue_final",
        },
        "capacity",
    )
    if (
        _boolean(
            capacity["worker_stopped_during_submission"],
            "capacity.worker_stopped_during_submission",
        )
        is not True
    ):
        raise TerminalRuntimeCapacityEvidenceError(
            "capacity.worker_stopped_during_submission must be true"
        )
    levels = _mapping(capacity["levels"], "capacity.levels")
    if set(levels) != set(_LEVELS):
        raise TerminalRuntimeCapacityEvidenceError("capacity.levels must contain exactly 1/5/10/20")
    accepted_total = 0
    rejected_total = 0
    for level in _LEVELS:
        counts = _mapping(levels[level], f"capacity.levels.{level}")
        accepted, rejected = _validate_status_counts(counts, int(level), f"capacity.levels.{level}")
        accepted_total += accepted
        rejected_total += rejected
    accepted_runs = _integer(capacity["accepted_runs"], "capacity.accepted_runs", minimum=1)
    rejected_runs = _integer(capacity["rejected_runs"], "capacity.rejected_runs", minimum=1)
    if (accepted_runs, rejected_runs) != (accepted_total, rejected_total):
        raise TerminalRuntimeCapacityEvidenceError(
            "capacity accepted/rejected totals do not match level counts"
        )
    if capacity["rejection_reason"] != _REJECTION_REASON:
        raise TerminalRuntimeCapacityEvidenceError("capacity.rejection_reason is inconsistent")
    _validate_queue_snapshot(
        _mapping(capacity["queue_after_submit"], "capacity.queue_after_submit"),
        "capacity.queue_after_submit",
        expected_queued=accepted_runs,
    )
    _validate_queue_snapshot(
        _mapping(capacity["queue_final"], "capacity.queue_final"),
        "capacity.queue_final",
    )
    final = _mapping(capacity["queue_final"], "capacity.queue_final")
    if any(
        final[key] != 0 for key in ("user_active", "user_queued", "global_active", "global_queued")
    ):
        raise TerminalRuntimeCapacityEvidenceError("capacity.queue_final must be fully drained")
    return accepted_runs, rejected_runs


def _validate_idempotency(idempotency: Mapping[str, object]) -> None:
    """Require first-winner replay without a second durable row."""

    _require_exact_keys(
        idempotency,
        {"replay_status_code", "same_run_id", "second_durable_row"},
        "idempotency",
    )
    if _integer(idempotency["replay_status_code"], "idempotency.replay_status_code") != 202:
        raise TerminalRuntimeCapacityEvidenceError("idempotency replay status must be 202")
    _string(idempotency["same_run_id"], "idempotency.same_run_id")
    if _boolean(idempotency["second_durable_row"], "idempotency.second_durable_row") is not False:
        raise TerminalRuntimeCapacityEvidenceError("idempotency created a second durable row")


def _validate_worker_recovery(worker_recovery: Mapping[str, object]) -> None:
    """Require explicit restart readiness, terminal failure, and queue drain."""

    _require_exact_keys(
        worker_recovery,
        {
            "started_after_queue",
            "restart_requested",
            "post_restart_worker_ready",
            "chaos_runs",
            "chaos_runs_terminal_status",
            "chaos_runs_error_code",
            "queue_drained_after_restart",
        },
        "worker_recovery",
    )
    for key in (
        "started_after_queue",
        "restart_requested",
        "post_restart_worker_ready",
        "queue_drained_after_restart",
    ):
        if _boolean(worker_recovery[key], f"worker_recovery.{key}") is not True:
            raise TerminalRuntimeCapacityEvidenceError(f"worker_recovery.{key} must be true")
    chaos_runs = _sequence(worker_recovery["chaos_runs"], "worker_recovery.chaos_runs")
    if not chaos_runs or any(
        not _string(item, "worker_recovery.chaos_runs[]") for item in chaos_runs
    ):
        raise TerminalRuntimeCapacityEvidenceError("worker_recovery.chaos_runs must be non-empty")
    if worker_recovery["chaos_runs_terminal_status"] != "failed":
        raise TerminalRuntimeCapacityEvidenceError(
            "worker_recovery terminal status is inconsistent"
        )
    if worker_recovery["chaos_runs_error_code"] != _ERROR_CODE:
        raise TerminalRuntimeCapacityEvidenceError("worker_recovery error code is inconsistent")


def _validate_sse(sse: Mapping[str, object]) -> None:
    """Require authenticated SSE negotiation and durable error replay."""

    _require_exact_keys(
        sse,
        {"status_code", "content_type", "stream_lines_captured", "first_chaos_event_type", "note"},
        "sse",
    )
    if _integer(sse["status_code"], "sse.status_code") != 200:
        raise TerminalRuntimeCapacityEvidenceError("sse.status_code must be 200")
    if sse["content_type"] != "text/event-stream":
        raise TerminalRuntimeCapacityEvidenceError("sse.content_type is inconsistent")
    if _integer(sse["stream_lines_captured"], "sse.stream_lines_captured", minimum=1) < 1:
        raise TerminalRuntimeCapacityEvidenceError("sse must capture at least one line")
    if sse["first_chaos_event_type"] != "error":
        raise TerminalRuntimeCapacityEvidenceError("sse first chaos event must be an error")
    _string(sse["note"], "sse.note")


def _validate_cleanup(cleanup: Mapping[str, object]) -> None:
    """Require all temporary runtime access to be disabled after observation."""

    _require_exact_keys(
        cleanup,
        {
            "runtime_flags_after_observation",
            "dedicated_terminal_worker_after_observation",
            "web_container",
            "temporary_token_revoked",
            "business_run_rows_retained",
        },
        "cleanup",
    )
    flags = _mapping(
        cleanup["runtime_flags_after_observation"], "cleanup.runtime_flags_after_observation"
    )
    _require_exact_keys(
        flags,
        {
            "TERMINAL_RUNTIME_AUTHORIZED",
            "TERMINAL_QUEUED_INTAKE_ENABLED",
            "TERMINAL_QUEUED_WORKER_ENABLED",
            "TERMINAL_EMERGENCY_STOP",
        },
        "cleanup.runtime_flags_after_observation",
    )
    if any(
        _boolean(flags[key], f"cleanup.runtime_flags_after_observation.{key}") is not False
        for key in flags
    ):
        raise TerminalRuntimeCapacityEvidenceError("cleanup runtime flags must all be false")
    if cleanup["dedicated_terminal_worker_after_observation"] != "absent":
        raise TerminalRuntimeCapacityEvidenceError("dedicated terminal worker was not removed")
    if cleanup["web_container"] != "running":
        raise TerminalRuntimeCapacityEvidenceError("web container is not running")
    if _boolean(cleanup["temporary_token_revoked"], "cleanup.temporary_token_revoked") is not True:
        raise TerminalRuntimeCapacityEvidenceError("temporary token was not revoked")
    if (
        _boolean(cleanup["business_run_rows_retained"], "cleanup.business_run_rows_retained")
        is not True
    ):
        raise TerminalRuntimeCapacityEvidenceError("business run rows were not retained")


def _validate_public_probes(public_probes: Mapping[str, object]) -> None:
    """Validate health and decision fail-closed probes without trusting decisions."""

    _require_exact_keys(
        public_probes,
        {"health", "ready", "decision_ready", "agent_runtime_health"},
        "public_probes",
    )
    health = _mapping(public_probes["health"], "public_probes.health")
    _require_exact_keys(health, {"status_code", "observed_status"}, "public_probes.health")
    if (
        _integer(health["status_code"], "public_probes.health.status_code") != 200
        or health["observed_status"] != "ok"
    ):
        raise TerminalRuntimeCapacityEvidenceError("health probe is not healthy")
    ready = _mapping(public_probes["ready"], "public_probes.ready")
    _require_exact_keys(
        ready,
        {"status_code", "observed_status", "critical_data", "decision_data"},
        "public_probes.ready",
    )
    if (
        _integer(ready["status_code"], "public_probes.ready.status_code") != 200
        or ready["observed_status"] != "ok"
        or ready["critical_data"] != "ok"
        or ready["decision_data"] != "warning"
    ):
        raise TerminalRuntimeCapacityEvidenceError("ready probe is inconsistent")
    decision_ready = _mapping(public_probes["decision_ready"], "public_probes.decision_ready")
    _require_exact_keys(
        decision_ready,
        {"status_code", "observed_status", "must_not_use_for_decision", "block_reason_code"},
        "public_probes.decision_ready",
    )
    if (
        _integer(decision_ready["status_code"], "public_probes.decision_ready.status_code") != 503
        or decision_ready["observed_status"] != "blocked"
        or _boolean(
            decision_ready["must_not_use_for_decision"],
            "public_probes.decision_ready.must_not_use_for_decision",
        )
        is not True
        or decision_ready["block_reason_code"] != "decision_runtime_blocked"
    ):
        raise TerminalRuntimeCapacityEvidenceError("decision-ready probe is not fail-closed")
    agent_health = _mapping(
        public_probes["agent_runtime_health"], "public_probes.agent_runtime_health"
    )
    _require_exact_keys(
        agent_health,
        {"status_code", "observed_status"},
        "public_probes.agent_runtime_health",
    )
    if (
        _integer(agent_health["status_code"], "public_probes.agent_runtime_health.status_code")
        != 200
        or agent_health["observed_status"] != "healthy"
    ):
        raise TerminalRuntimeCapacityEvidenceError("agent runtime health probe is unhealthy")


def _validate_gate(tar01_gate: Mapping[str, object]) -> None:
    """Require the artifact to preserve the blocked TAR-01 decision."""

    _require_exact_keys(
        tar01_gate, {"decision", "safety_ready", "capacity_ready", "command"}, "tar01_gate"
    )
    if tar01_gate["decision"] != "BLOCKED":
        raise TerminalRuntimeCapacityEvidenceError("tar01_gate.decision must remain BLOCKED")
    if _boolean(tar01_gate["safety_ready"], "tar01_gate.safety_ready") is not True:
        raise TerminalRuntimeCapacityEvidenceError("tar01_gate.safety_ready must be true")
    if _boolean(tar01_gate["capacity_ready"], "tar01_gate.capacity_ready") is not False:
        raise TerminalRuntimeCapacityEvidenceError("tar01_gate.capacity_ready must be false")
    if tar01_gate["command"] != "python scripts/check_tar01_exit_gate.py --format json":
        raise TerminalRuntimeCapacityEvidenceError("tar01_gate.command is inconsistent")


def _validate_scope(scope: Mapping[str, object]) -> None:
    """Require authorization and explicit non-claims about production evidence."""

    _require_exact_keys(
        scope,
        {
            "production_data_written",
            "write_scope",
            "decision_state_overridden",
            "provider_success_claimed",
            "authorized_by_user",
            "not_proven",
        },
        "scope",
    )
    if _boolean(scope["production_data_written"], "scope.production_data_written") is not True:
        raise TerminalRuntimeCapacityEvidenceError("scope.production_data_written must be true")
    _string(scope["write_scope"], "scope.write_scope")
    if _boolean(scope["decision_state_overridden"], "scope.decision_state_overridden") is not False:
        raise TerminalRuntimeCapacityEvidenceError("scope.decision_state_overridden must be false")
    if _boolean(scope["provider_success_claimed"], "scope.provider_success_claimed") is not False:
        raise TerminalRuntimeCapacityEvidenceError("scope.provider_success_claimed must be false")
    if _boolean(scope["authorized_by_user"], "scope.authorized_by_user") is not True:
        raise TerminalRuntimeCapacityEvidenceError("scope.authorized_by_user must be true")
    not_proven = _sequence(scope["not_proven"], "scope.not_proven")
    required = {
        "multi-user/global capacity and hard SLO",
        "sustained chaos and reconnect recovery",
        "14-day telemetry",
        "restore/rollback",
        "successful provider/MCP execution",
        "owner/reviewer cryptographic exit sign-off",
    }
    observed = {_string(item, "scope.not_proven[]") for item in not_proven}
    if not required.issubset(observed):
        raise TerminalRuntimeCapacityEvidenceError("scope.not_proven omits a required non-claim")


def _validate_expected_binding(
    source_commit: str,
    release: str,
    image_id: str,
    authorization: Mapping[str, object],
    expected: TerminalRuntimeCapacityEvidenceBinding,
) -> None:
    """Bind the artifact to the exact candidate named by the contract."""

    _validate_binding(expected)
    if (source_commit, release) != (expected.candidate_commit, expected.release):
        raise TerminalRuntimeCapacityEvidenceError("artifact candidate does not match contract")
    if expected.image.startswith("sha256:") and image_id != expected.image:
        raise TerminalRuntimeCapacityEvidenceError("artifact image digest does not match contract")
    if (
        expected.image.startswith("agomtradepro-web:")
        and authorization["worker_image"] != expected.image
    ):
        raise TerminalRuntimeCapacityEvidenceError("artifact worker image does not match contract")


def validate_terminal_runtime_capacity_evidence(
    payload: Mapping[str, object],
    *,
    expected_candidate: TerminalRuntimeCapacityEvidenceBinding | None = None,
) -> TerminalRuntimeCapacityEvidenceReport:
    """Validate one bounded capacity observation without enabling runtime."""

    _require_exact_keys(
        payload,
        {
            "schema",
            "observed_at",
            "candidate",
            "authorization",
            "actor",
            "capacity",
            "idempotency",
            "worker_recovery",
            "sse",
            "cleanup",
            "public_probes",
            "tar01_gate",
            "scope",
        },
        "evidence",
    )
    if payload["schema"] != "tar01-current-production-capacity.v1":
        raise TerminalRuntimeCapacityEvidenceError("unsupported evidence schema")
    observed_at = _string(payload["observed_at"], "observed_at")
    if _OBSERVED_AT_RE.fullmatch(observed_at) is None:
        raise TerminalRuntimeCapacityEvidenceError("observed_at must be an UTC timestamp")
    candidate = _mapping(payload["candidate"], "candidate")
    source_commit, release, image_id = _validate_candidate(candidate)
    authorization = _mapping(payload["authorization"], "authorization")
    _validate_authorization(authorization, release)
    if expected_candidate is not None:
        _validate_expected_binding(
            source_commit, release, image_id, authorization, expected_candidate
        )
    _validate_actor(_mapping(payload["actor"], "actor"))
    accepted_runs, rejected_runs = _validate_capacity(_mapping(payload["capacity"], "capacity"))
    _validate_idempotency(_mapping(payload["idempotency"], "idempotency"))
    _validate_worker_recovery(_mapping(payload["worker_recovery"], "worker_recovery"))
    _validate_sse(_mapping(payload["sse"], "sse"))
    _validate_cleanup(_mapping(payload["cleanup"], "cleanup"))
    _validate_public_probes(_mapping(payload["public_probes"], "public_probes"))
    _validate_gate(_mapping(payload["tar01_gate"], "tar01_gate"))
    _validate_scope(_mapping(payload["scope"], "scope"))
    return TerminalRuntimeCapacityEvidenceReport(
        candidate_commit=source_commit,
        candidate_release=release,
        image_id=image_id,
        accepted_runs=accepted_runs,
        rejected_runs=rejected_runs,
        level_count=len(_LEVELS),
        idempotency_verified=True,
        worker_recovery_verified=True,
        sse_verified=True,
        cleanup_verified=True,
        decision="BLOCKED",
        safety_ready=True,
        capacity_ready=False,
    )
