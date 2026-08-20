"""Fail-closed validation for authenticated TAR-01 reserved-route evidence.

The reserved ``/api/terminal/runs/`` route is intentionally unavailable while
the queued runtime is dormant.  This module validates the resulting production
observation without turning it into a capacity baseline.  It performs no
network, ORM, Celery, broker, or Agent I/O.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final


class TerminalRuntimeReservedRouteEvidenceError(ValueError):
    """Raised when reserved-route evidence is incomplete or inconsistent."""


_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_RE: Final[re.Pattern[str]] = re.compile(r"^agomtradepro-web:(\S+)$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_LEVELS: Final[tuple[int, ...]] = (1, 5, 10, 20)
_EXPECTED_REASON: Final[str] = "queued_runtime_not_wired"
_EXPECTED_CODE: Final[str] = "DISPATCH_UNAVAILABLE"
_EXPECTED_RETRY_AFTER: Final[str] = "60"


def _mapping(value: object, field: str) -> Mapping[str, object]:
    """Require a JSON object with string keys."""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TerminalRuntimeReservedRouteEvidenceError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    """Require a JSON array."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TerminalRuntimeReservedRouteEvidenceError(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    """Require a non-empty whitespace-free JSON string."""

    if type(value) is not str or not value or value.strip() != value:
        raise TerminalRuntimeReservedRouteEvidenceError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    """Require a JSON integer and reject bool-as-int coercion."""

    if type(value) is not int:
        raise TerminalRuntimeReservedRouteEvidenceError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    """Require an actual JSON boolean."""

    if type(value) is not bool:
        raise TerminalRuntimeReservedRouteEvidenceError(f"{field} must be a boolean")
    return value


def _finite_non_negative(value: object, field: str) -> float:
    """Require a finite, non-negative numeric latency."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TerminalRuntimeReservedRouteEvidenceError(f"{field} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise TerminalRuntimeReservedRouteEvidenceError(f"{field} must be finite and non-negative")
    return numeric


def _require_exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    """Reject omitted or smuggled fields in a structural evidence object."""

    if set(value) != expected:
        raise TerminalRuntimeReservedRouteEvidenceError(
            f"{field} keys must be exactly {sorted(expected)}"
        )


def _validate_candidate(candidate: Mapping[str, object]) -> tuple[str, str, str]:
    """Validate release, source, and image identity as one immutable tuple."""

    _require_exact_keys(
        candidate,
        {
            "status",
            "app_version",
            "release_tag",
            "source_commit",
            "short_commit",
            "image_tag",
            "image_id",
            "source_mode",
            "runtime_match",
            "must_not_trust_for_release",
            "deployment_report",
        },
        "candidate",
    )
    if candidate["status"] != "verified":
        raise TerminalRuntimeReservedRouteEvidenceError("candidate status must be verified")
    _string(candidate["app_version"], "candidate.app_version")
    release = _string(candidate["release_tag"], "candidate.release_tag")
    source_commit = _string(candidate["source_commit"], "candidate.source_commit")
    if _COMMIT_RE.fullmatch(source_commit) is None:
        raise TerminalRuntimeReservedRouteEvidenceError("candidate.source_commit is invalid")
    if candidate["short_commit"] != source_commit[:12]:
        raise TerminalRuntimeReservedRouteEvidenceError("candidate.short_commit is inconsistent")
    image_tag = _string(candidate["image_tag"], "candidate.image_tag")
    image_match = _IMAGE_RE.fullmatch(image_tag)
    if image_match is None or image_match.group(1) != release:
        raise TerminalRuntimeReservedRouteEvidenceError("candidate.image_tag is inconsistent")
    image_id = _string(candidate["image_id"], "candidate.image_id")
    if _SHA256_RE.fullmatch(image_id) is None:
        raise TerminalRuntimeReservedRouteEvidenceError("candidate.image_id is invalid")
    if candidate["source_mode"] != "git-clone":
        raise TerminalRuntimeReservedRouteEvidenceError("candidate source_mode must be git-clone")
    if _boolean(candidate["runtime_match"], "candidate.runtime_match") is not True:
        raise TerminalRuntimeReservedRouteEvidenceError("candidate runtime_match must be true")
    if _boolean(candidate["must_not_trust_for_release"], "candidate.must_not_trust_for_release"):
        raise TerminalRuntimeReservedRouteEvidenceError(
            "candidate must_not_trust_for_release must be false"
        )
    _string(candidate["deployment_report"], "candidate.deployment_report")
    return source_commit, release, image_id


def _validate_health_pair(payload: Mapping[str, object]) -> bool:
    """Validate stable health/readiness observations and return stability."""

    before = _mapping(payload["health_before"], "health_before")
    after = _mapping(payload["health_after"], "health_after")
    for name, health in (("health_before", before), ("health_after", after)):
        _require_exact_keys(health, {"statuses", "readiness"}, name)
        statuses = _sequence(health["statuses"], f"{name}.statuses")
        if not statuses or any(_integer(status, f"{name}.statuses") != 200 for status in statuses):
            raise TerminalRuntimeReservedRouteEvidenceError(f"{name}.statuses must all be 200")
        readiness = _mapping(health["readiness"], f"{name}.readiness")
        _require_exact_keys(
            readiness, {"status", "payload_status", "celery_workers"}, f"{name}.readiness"
        )
        if _integer(readiness["status"], f"{name}.readiness.status") != 200:
            raise TerminalRuntimeReservedRouteEvidenceError(f"{name}.readiness.status must be 200")
        if readiness["payload_status"] != "ok":
            raise TerminalRuntimeReservedRouteEvidenceError(
                f"{name}.readiness.payload_status must be ok"
            )
        if _integer(readiness["celery_workers"], f"{name}.readiness.celery_workers") <= 0:
            raise TerminalRuntimeReservedRouteEvidenceError(
                f"{name}.readiness.celery_workers must be positive"
            )
    return before == after


def _validate_audit_pair(payload: Mapping[str, object]) -> bool:
    """Validate audit health and prove before/after counters are unchanged."""

    before = _mapping(payload["audit_before"], "audit_before")
    after = _mapping(payload["audit_after"], "audit_after")
    expected_keys = {
        "status",
        "overall_status",
        "total_operation_logs",
        "total_failures",
        "failure_rate",
        "backlog_counts",
    }
    for name, audit in (("audit_before", before), ("audit_after", after)):
        _require_exact_keys(audit, expected_keys, name)
        if _integer(audit["status"], f"{name}.status") != 200 or audit["overall_status"] != "OK":
            raise TerminalRuntimeReservedRouteEvidenceError(f"{name} is not healthy")
        if _integer(audit["total_operation_logs"], f"{name}.total_operation_logs") < 0:
            raise TerminalRuntimeReservedRouteEvidenceError(
                f"{name}.total_operation_logs is invalid"
            )
        if _integer(audit["total_failures"], f"{name}.total_failures") < 0:
            raise TerminalRuntimeReservedRouteEvidenceError(f"{name}.total_failures is invalid")
        if _finite_non_negative(audit["failure_rate"], f"{name}.failure_rate") != 0:
            raise TerminalRuntimeReservedRouteEvidenceError(f"{name}.failure_rate must be zero")
        backlog = _mapping(audit["backlog_counts"], f"{name}.backlog_counts")
        expected_backlog = {"pending", "due_pending", "claimed", "expired_claimed", "failed"}
        _require_exact_keys(backlog, expected_backlog, f"{name}.backlog_counts")
        if any(
            _integer(backlog[key], f"{name}.backlog_counts.{key}") != 0 for key in expected_backlog
        ):
            raise TerminalRuntimeReservedRouteEvidenceError(f"{name}.backlog_counts must be zero")
    return before == after


def _validate_level(level: Mapping[str, object], expected_concurrency: int) -> None:
    """Validate one reserved-route staircase level."""

    _require_exact_keys(
        level,
        {
            "concurrency",
            "requests",
            "status_counts",
            "reason_counts",
            "retry_after_counts",
            "latency_ms",
            "all_expected",
        },
        f"level[{expected_concurrency}]",
    )
    if _integer(level["concurrency"], "level.concurrency") != expected_concurrency:
        raise TerminalRuntimeReservedRouteEvidenceError("level concurrency order is inconsistent")
    if _integer(level["requests"], "level.requests") != expected_concurrency:
        raise TerminalRuntimeReservedRouteEvidenceError(
            "level request count must equal concurrency"
        )
    if _boolean(level["all_expected"], "level.all_expected") is not True:
        raise TerminalRuntimeReservedRouteEvidenceError("each level must be all_expected")
    for key, expected in (
        ("status_counts", {"503": expected_concurrency}),
        ("reason_counts", {_EXPECTED_REASON: expected_concurrency}),
        ("retry_after_counts", {_EXPECTED_RETRY_AFTER: expected_concurrency}),
    ):
        counts = _mapping(level[key], f"level.{key}")
        if set(counts) != set(expected) or any(
            _integer(counts[item], f"level.{key}.{item}") != count
            for item, count in expected.items()
        ):
            raise TerminalRuntimeReservedRouteEvidenceError(
                f"level.{key} does not describe the expected fail-closed responses"
            )
    latency = _mapping(level["latency_ms"], "level.latency_ms")
    _require_exact_keys(latency, {"p50", "p95", "p99", "max"}, "level.latency_ms")
    values = tuple(
        _finite_non_negative(latency[key], f"level.latency_ms.{key}")
        for key in ("p50", "p95", "p99", "max")
    )
    if values != tuple(sorted(values)):
        raise TerminalRuntimeReservedRouteEvidenceError(
            "latency percentiles must be non-decreasing"
        )


@dataclass(frozen=True, slots=True)
class TerminalRuntimeReservedRouteEvidenceReport:
    """Validated summary that cannot be used as a capacity baseline."""

    candidate_commit: str
    candidate_release: str
    image_id: str
    level_count: int
    health_stable: bool
    side_effects_observed: bool
    capacity_ready: bool


def validate_terminal_runtime_reserved_route_evidence(
    payload: Mapping[str, object],
) -> TerminalRuntimeReservedRouteEvidenceReport:
    """Validate one authenticated reserved-route observation without enabling runtime."""

    _require_exact_keys(
        payload,
        {
            "schema",
            "artifact_type",
            "environment",
            "base_url",
            "collected_at",
            "method",
            "route",
            "authentication",
            "candidate",
            "deployment_verifier",
            "health_before",
            "health_after",
            "audit_before",
            "audit_after",
            "tui_catalog_observation",
            "levels",
            "acceptance",
            "limitations",
        },
        "evidence",
    )
    if payload["schema"] != "terminal-runtime-reserved-route-observation.v2":
        raise TerminalRuntimeReservedRouteEvidenceError("unsupported evidence schema")
    if payload["artifact_type"] != "terminal_runtime_reserved_route_observation":
        raise TerminalRuntimeReservedRouteEvidenceError("artifact_type is inconsistent")
    if payload["environment"] != "production-vps" or payload["method"] != "POST":
        raise TerminalRuntimeReservedRouteEvidenceError("evidence environment or method is invalid")
    if payload["route"] != "/api/terminal/runs/":
        raise TerminalRuntimeReservedRouteEvidenceError("evidence route is invalid")
    _string(payload["base_url"], "base_url")
    _string(payload["collected_at"], "collected_at")
    authentication = _mapping(payload["authentication"], "authentication")
    _require_exact_keys(
        authentication,
        {"method", "csrf_referer_and_token_supplied", "credentials_recorded"},
        "authentication",
    )
    if (
        authentication["method"] != "account_session"
        or _boolean(
            authentication["csrf_referer_and_token_supplied"],
            "authentication.csrf_referer_and_token_supplied",
        )
        is not True
    ):
        raise TerminalRuntimeReservedRouteEvidenceError("authentication evidence is incomplete")
    if _boolean(authentication["credentials_recorded"], "authentication.credentials_recorded"):
        raise TerminalRuntimeReservedRouteEvidenceError("credentials must not be recorded")
    source_commit, release, image_id = _validate_candidate(
        _mapping(payload["candidate"], "candidate")
    )
    verifier = _mapping(payload["deployment_verifier"], "deployment_verifier")
    if verifier.get("status") != "passed":
        raise TerminalRuntimeReservedRouteEvidenceError("deployment verifier did not pass")
    if _integer(verifier.get("https_health"), "deployment_verifier.https_health") != 200:
        raise TerminalRuntimeReservedRouteEvidenceError("deployment HTTPS health is not 200")
    if (
        _boolean(verifier.get("containers_healthy"), "deployment_verifier.containers_healthy")
        is not True
    ):
        raise TerminalRuntimeReservedRouteEvidenceError("containers are not healthy")
    if (
        verifier.get("database_and_redis") != "ok"
        or verifier.get("celery_worker_and_beat") != "running"
    ):
        raise TerminalRuntimeReservedRouteEvidenceError("deployment dependencies are not healthy")
    _string(verifier.get("celery_ping"), "deployment_verifier.celery_ping")
    if (
        verifier.get("migrations") != "no migrations to apply"
        or verifier.get("tui_registry") != "matched"
    ):
        raise TerminalRuntimeReservedRouteEvidenceError(
            "deployment verifier identity is incomplete"
        )
    _validate_health_pair(payload)
    _validate_audit_pair(payload)
    levels = _sequence(payload["levels"], "levels")
    if len(levels) != len(_LEVELS):
        raise TerminalRuntimeReservedRouteEvidenceError("levels must contain exactly 1/5/10/20")
    for raw_level, expected in zip(levels, _LEVELS, strict=True):
        _validate_level(_mapping(raw_level, f"level[{expected}]"), expected)
    acceptance = _mapping(payload["acceptance"], "acceptance")
    _require_exact_keys(
        acceptance,
        {
            "health_stable",
            "reserved_route_fail_closed",
            "side_effects_observed",
            "side_effect_basis",
            "queued_runtime_enabled",
            "capacity_ready",
            "outcome",
            "reason",
        },
        "acceptance",
    )
    health_stable = _validate_health_pair(payload)
    side_effects_observed = _validate_audit_pair(payload)
    if acceptance["health_stable"] != health_stable:
        raise TerminalRuntimeReservedRouteEvidenceError(
            "acceptance health_stable is not derived from observations"
        )
    if acceptance["reserved_route_fail_closed"] is not True:
        raise TerminalRuntimeReservedRouteEvidenceError("reserved route must be fail-closed")
    if acceptance["side_effects_observed"] != (not side_effects_observed):
        raise TerminalRuntimeReservedRouteEvidenceError(
            "acceptance side_effects_observed is inconsistent"
        )
    if not _string(acceptance["side_effect_basis"], "acceptance.side_effect_basis"):
        raise TerminalRuntimeReservedRouteEvidenceError("side effect basis is required")
    if (
        acceptance["queued_runtime_enabled"] is not False
        or acceptance["capacity_ready"] is not False
    ):
        raise TerminalRuntimeReservedRouteEvidenceError(
            "reserved route evidence cannot enable runtime"
        )
    if acceptance["outcome"] != "capacity_denied" or acceptance["reason"] != _EXPECTED_REASON:
        raise TerminalRuntimeReservedRouteEvidenceError("reserved route outcome is inconsistent")
    limitations = _sequence(payload["limitations"], "limitations")
    if not limitations or any(type(item) is not str or not item for item in limitations):
        raise TerminalRuntimeReservedRouteEvidenceError(
            "limitations must be explicit non-empty strings"
        )
    return TerminalRuntimeReservedRouteEvidenceReport(
        candidate_commit=source_commit,
        candidate_release=release,
        image_id=image_id,
        level_count=len(levels),
        health_stable=health_stable,
        side_effects_observed=not side_effects_observed,
        capacity_ready=False,
    )
