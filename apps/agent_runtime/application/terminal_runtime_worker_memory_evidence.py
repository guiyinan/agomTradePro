"""Fail-closed validation for the TAR-01 QLib worker memory observation.

The validator accepts only the already collected, candidate-bound observation
shape.  It does not inspect Docker, Celery, QLib, PostgreSQL, Redis, or the
VPS, and it never turns this bounded single-worker observation into a capacity
or decision-readiness result.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final


class TerminalRuntimeWorkerMemoryEvidenceError(ValueError):
    """Raised when worker-memory evidence is malformed or candidate-substituted."""


@dataclass(frozen=True, slots=True)
class TerminalRuntimeWorkerMemoryEvidenceBinding:
    """Immutable source, release, and image identity expected by the report."""

    candidate_commit: str
    candidate_release: str
    image_id: str

    def __post_init__(self) -> None:
        """Validate the immutable deployment identity."""

        if (
            type(self.candidate_commit) is not str
            or _COMMIT_RE.fullmatch(self.candidate_commit) is None
        ):
            raise TerminalRuntimeWorkerMemoryEvidenceError("candidate_commit is invalid")
        if (
            type(self.candidate_release) is not str
            or _RELEASE_RE.fullmatch(self.candidate_release) is None
        ):
            raise TerminalRuntimeWorkerMemoryEvidenceError("candidate_release is invalid")
        if type(self.image_id) is not str or _IMAGE_ID_RE.fullmatch(self.image_id) is None:
            raise TerminalRuntimeWorkerMemoryEvidenceError("image_id is invalid")

    @property
    def release(self) -> str:
        """Return the release tag using the short evidence vocabulary."""

        return self.candidate_release

    @property
    def image(self) -> str:
        """Return the immutable OCI image digest using the short vocabulary."""

        return self.image_id


@dataclass(frozen=True, slots=True)
class TerminalRuntimeWorkerMemoryEvidenceReport:
    """Validated summary that remains a bounded observation, not a gate pass."""

    candidate_commit: str
    candidate_release: str
    image_id: str
    observed_at: datetime
    window_start: datetime
    window_end: datetime
    window_seconds: int
    memory_limit_bytes: int
    observed_max_memory_bytes: int
    batch_count: int
    task_outcome: str
    stored: int
    health_status: int
    ready_status: int
    decision_ready_status: int
    decision_ready_must_not_use_for_decision: bool
    runtime_flags_changed: bool
    business_canary_submitted: bool
    tar01_exit_decision: str
    safety_ready: bool
    capacity_ready: bool

    @property
    def candidate_bound(self) -> bool:
        """Return true because the validator requires an external expected identity."""

        return True


_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{14}$")
_IMAGE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_TAG_RE: Final[re.Pattern[str]] = re.compile(r"^agomtradepro-web:\d{14}$")
_CI_URL_RE: Final[re.Pattern[str]] = re.compile(
    r"^https://github\.com/guiyinan/agomTradePro/actions/runs/\d+$"
)
_MEMORY_RANGE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<minimum>[0-9]+(?:\.[0-9]+)?)MiB\.\.(?P<maximum>[0-9]+(?:\.[0-9]+)?)GiB / 4GiB$"
)
_WINDOW_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<minutes>\d+)m(?P<seconds>\d{2})s$")
_SAFE_TEXT_FORBIDDEN: Final[tuple[str, ...]] = (
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
_EXPECTED_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "artifact",
        "observed_at",
        "candidate",
        "trigger_and_correction",
        "deployment",
        "worker_contract",
        "post_deploy_observation",
        "api_observation",
        "ci",
        "gate",
    }
)
_EXPECTED_REMAINING_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        "multi-user/global hard-SLO capacity",
        "sustained chaos and reconnect recovery",
        "provider/MCP success",
        "14-day telemetry",
        "production restore/rollback and RTO/RPO",
        "owner/reviewer sign-off",
    }
)
_EXPECTED_QUEUES: Final[tuple[str, ...]] = ("celery", "qlib_infer", "qlib_train")
_MEMORY_LIMIT_BYTES: Final[int] = 4 * 1024**3


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Require a JSON object with string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be an object")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    """Require a JSON array."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be an array")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], field_name: str) -> None:
    """Reject omitted and smuggled fields in the evidence envelope."""

    if set(value) != expected:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            f"{field_name} keys must be exactly {sorted(expected)}"
        )


def _text(value: object, field_name: str) -> str:
    """Require non-empty printable text without credentials or prompts."""

    if type(value) is not str or not value or value.strip() != value:
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be non-empty text")
    if any(ord(character) < 32 for character in value):
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} contains control characters")
    lowered = value.casefold()
    if any(marker in lowered for marker in _SAFE_TEXT_FORBIDDEN):
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} contains secret material")
    return value


def _token(value: object, field_name: str) -> str:
    """Require a short whitespace-free machine token."""

    text = _text(value, field_name)
    if re.fullmatch(r"[A-Za-z0-9_.:/+-]{1,256}", text) is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be a stable token")
    return text


def _integer(value: object, field_name: str, *, minimum: int = 0) -> int:
    """Require a JSON integer without bool coercion."""

    if type(value) is not int or value < minimum:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            f"{field_name} must be an integer >= {minimum}"
        )
    return value


def _boolean(value: object, field_name: str) -> bool:
    """Require an actual JSON boolean."""

    if type(value) is not bool:
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be a boolean")
    return value


def _finite_positive(value: object, field_name: str) -> float:
    """Require a finite positive numeric value."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be finite and positive")
    return result


def _utc_timestamp(value: object, field_name: str) -> datetime:
    """Parse an ISO timestamp and return its UTC instant."""

    if type(value) is not str or not value:
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be an aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            f"{field_name} must be an aware timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _validate_binding(binding: TerminalRuntimeWorkerMemoryEvidenceBinding) -> None:
    """Revalidate an expected identity before comparing untrusted evidence."""

    if type(binding) is not TerminalRuntimeWorkerMemoryEvidenceBinding:
        raise TerminalRuntimeWorkerMemoryEvidenceError("expected candidate binding is invalid")
    try:
        TerminalRuntimeWorkerMemoryEvidenceBinding(
            candidate_commit=binding.candidate_commit,
            candidate_release=binding.candidate_release,
            image_id=binding.image_id,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            "expected candidate binding is invalid"
        ) from exc


def _validate_candidate(
    payload: Mapping[str, object],
    expected: TerminalRuntimeWorkerMemoryEvidenceBinding,
) -> None:
    """Validate source/release/image identity and exact expected binding."""

    _exact_keys(
        payload,
        {"branch", "commit", "release_tag", "image_tag", "image_id", "source_mode"},
        "candidate",
    )
    commit = _token(payload["commit"], "candidate.commit")
    release = _token(payload["release_tag"], "candidate.release_tag")
    image_tag = _token(payload["image_tag"], "candidate.image_tag")
    image_id = _token(payload["image_id"], "candidate.image_id")
    if payload["branch"] != "dev/next-development":
        raise TerminalRuntimeWorkerMemoryEvidenceError("candidate.branch is invalid")
    if _COMMIT_RE.fullmatch(commit) is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError("candidate.commit is invalid")
    if _RELEASE_RE.fullmatch(release) is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError("candidate.release_tag is invalid")
    if image_tag != f"agomtradepro-web:{release}" or _IMAGE_TAG_RE.fullmatch(image_tag) is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError("candidate.image_tag is inconsistent")
    if _IMAGE_ID_RE.fullmatch(image_id) is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError("candidate.image_id is invalid")
    if payload["source_mode"] != "git-clone":
        raise TerminalRuntimeWorkerMemoryEvidenceError("candidate.source_mode is invalid")
    if (commit, release, image_id) != (
        expected.candidate_commit,
        expected.candidate_release,
        expected.image_id,
    ):
        raise TerminalRuntimeWorkerMemoryEvidenceError("evidence candidate does not match expected")


def _validate_trigger(payload: Mapping[str, object]) -> None:
    """Validate the recorded predecessor invalidation and correction."""

    _exact_keys(
        payload,
        {
            "trigger",
            "predecessor_commit",
            "predecessor_release_tag",
            "predecessor_oom_observed_at",
            "predecessor_oom_total_vm_kib",
            "predecessor_oom_anon_rss_kib",
            "correction",
        },
        "trigger_and_correction",
    )
    predecessor_commit = _token(payload["predecessor_commit"], "predecessor_commit")
    predecessor_release = _token(payload["predecessor_release_tag"], "predecessor_release_tag")
    if _COMMIT_RE.fullmatch(predecessor_commit) is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError("predecessor_commit is invalid")
    if _RELEASE_RE.fullmatch(predecessor_release) is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError("predecessor_release_tag is invalid")
    _utc_timestamp(payload["predecessor_oom_observed_at"], "predecessor_oom_observed_at")
    _integer(payload["predecessor_oom_total_vm_kib"], "predecessor_oom_total_vm_kib", minimum=1)
    _integer(payload["predecessor_oom_anon_rss_kib"], "predecessor_oom_anon_rss_kib", minimum=1)
    _text(payload["trigger"], "trigger")
    _text(payload["correction"], "correction")


def _validate_deployment(
    payload: Mapping[str, object], expected: TerminalRuntimeWorkerMemoryEvidenceBinding
) -> None:
    """Validate immutable deployment and QLib package identity."""

    _exact_keys(
        payload,
        {
            "mode",
            "action",
            "data_volumes_preserved",
            "predeploy_backup",
            "deployment_report",
            "migration_status",
            "schema_check",
            "django_system_check",
            "public_url",
            "health_status",
            "ready_status",
            "caddy_tls",
            "qlib",
        },
        "deployment",
    )
    if payload["mode"] != "code-only" or payload["action"] != "upgrade":
        raise TerminalRuntimeWorkerMemoryEvidenceError("deployment mode/action is invalid")
    if _boolean(payload["data_volumes_preserved"], "deployment.data_volumes_preserved") is not True:
        raise TerminalRuntimeWorkerMemoryEvidenceError("deployment data volumes were not preserved")
    for field_name, expected_value in (
        ("migration_status", "no migrations to apply"),
        ("schema_check", "ok"),
        ("django_system_check", "ok"),
        ("caddy_tls", "verified"),
    ):
        if payload[field_name] != expected_value:
            raise TerminalRuntimeWorkerMemoryEvidenceError(f"deployment.{field_name} is invalid")
    _text(payload["predeploy_backup"], "deployment.predeploy_backup")
    _text(payload["deployment_report"], "deployment.deployment_report")
    if payload["public_url"] != "https://demo.agomtrade.pro":
        raise TerminalRuntimeWorkerMemoryEvidenceError("deployment.public_url is invalid")
    if _integer(payload["health_status"], "deployment.health_status") != 200:
        raise TerminalRuntimeWorkerMemoryEvidenceError("deployment.health_status must be 200")
    if _integer(payload["ready_status"], "deployment.ready_status") != 200:
        raise TerminalRuntimeWorkerMemoryEvidenceError("deployment.ready_status must be 200")
    qlib = _mapping(payload["qlib"], "deployment.qlib")
    _exact_keys(qlib, {"pyqlib_version", "wrong_qlib_distribution", "module"}, "deployment.qlib")
    if qlib["pyqlib_version"] != "0.9.7" or qlib["wrong_qlib_distribution"] != "absent":
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            "deployment.qlib package identity is invalid"
        )
    module = _text(qlib["module"], "deployment.qlib.module")
    if not module.startswith("/usr/local/lib/python3.11/site-packages/qlib/"):
        raise TerminalRuntimeWorkerMemoryEvidenceError("deployment.qlib.module is invalid")
    if (
        payload["deployment_report"]
        != f"dist/remote-build-reports/remote-build-report-{expected.candidate_release}.json"
    ):
        raise TerminalRuntimeWorkerMemoryEvidenceError("deployment report is not candidate-bound")


def _validate_worker_contract(payload: Mapping[str, object]) -> None:
    """Validate the bounded QLib worker resource contract."""

    _exact_keys(
        payload,
        {
            "memory_limit",
            "memory_limit_bytes",
            "concurrency",
            "max_tasks_per_child",
            "qlib_prediction_batch_size",
            "queues",
        },
        "worker_contract",
    )
    if payload["memory_limit"] != "4GiB":
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker_contract.memory_limit is invalid")
    if (
        _integer(payload["memory_limit_bytes"], "worker_contract.memory_limit_bytes")
        != _MEMORY_LIMIT_BYTES
    ):
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            "worker_contract.memory_limit_bytes is invalid"
        )
    for field_name in ("concurrency", "max_tasks_per_child"):
        if _integer(payload[field_name], f"worker_contract.{field_name}") != 1:
            raise TerminalRuntimeWorkerMemoryEvidenceError(
                f"worker_contract.{field_name} must be 1"
            )
    if (
        _integer(
            payload["qlib_prediction_batch_size"], "worker_contract.qlib_prediction_batch_size"
        )
        != 500
    ):
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker_contract batch size must be 500")
    queues = tuple(
        _token(item, "worker_contract.queues")
        for item in _sequence(payload["queues"], "worker_contract.queues")
    )
    if queues != _EXPECTED_QUEUES:
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker_contract.queues are invalid")


def _memory_range(value: object) -> tuple[int, int]:
    """Parse the bounded memory range and return minimum/maximum bytes."""

    text = _text(value, "post_deploy_observation.worker_memory_range")
    match = _MEMORY_RANGE_RE.fullmatch(text)
    if match is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker memory range is invalid")
    minimum_mib = float(match.group("minimum"))
    maximum_gib = float(match.group("maximum"))
    if not math.isfinite(minimum_mib) or not math.isfinite(maximum_gib):
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker memory range is not finite")
    minimum_bytes = int(minimum_mib * 1024**2)
    maximum_bytes = int(maximum_gib * 1024**3)
    if minimum_bytes < 0 or maximum_bytes < minimum_bytes or maximum_bytes > _MEMORY_LIMIT_BYTES:
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker memory range exceeds the limit")
    return minimum_bytes, maximum_bytes


def _validate_post_deploy_observation(
    payload: Mapping[str, object],
) -> tuple[datetime, datetime, int, int, int, str, int]:
    """Validate UTC window, resource counters, and successful 12-batch task."""

    _exact_keys(
        payload,
        {
            "window_start",
            "window_end",
            "window",
            "worker_memory_range",
            "worker_restart_count",
            "worker_oom_killed",
            "worker_status",
            "post_release_kernel_oom_events",
            "worker_lost_error_count",
            "sigkill_count",
            "traceback_count",
            "qlib_batches_observed",
            "successful_task",
        },
        "post_deploy_observation",
    )
    window_start = _utc_timestamp(payload["window_start"], "post_deploy_observation.window_start")
    window_end = _utc_timestamp(payload["window_end"], "post_deploy_observation.window_end")
    if window_end <= window_start:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            "worker observation window is not increasing"
        )
    window_text = _token(payload["window"], "post_deploy_observation.window")
    window_match = _WINDOW_RE.fullmatch(window_text)
    if window_match is None:
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker observation window text is invalid")
    window_seconds = int(window_match.group("minutes")) * 60 + int(window_match.group("seconds"))
    actual_seconds = int((window_end - window_start).total_seconds())
    if actual_seconds != window_seconds:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            "worker window text does not match timestamps"
        )
    _, maximum_memory_bytes = _memory_range(payload["worker_memory_range"])
    if (
        _integer(payload["worker_restart_count"], "post_deploy_observation.worker_restart_count")
        != 0
    ):
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker_restart_count must be zero")
    if (
        _boolean(payload["worker_oom_killed"], "post_deploy_observation.worker_oom_killed")
        is not False
    ):
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker_oom_killed must be false")
    if payload["worker_status"] != "running":
        raise TerminalRuntimeWorkerMemoryEvidenceError("worker_status must be running")
    for field_name in (
        "post_release_kernel_oom_events",
        "worker_lost_error_count",
        "sigkill_count",
        "traceback_count",
    ):
        if _integer(payload[field_name], f"post_deploy_observation.{field_name}") != 0:
            raise TerminalRuntimeWorkerMemoryEvidenceError(f"{field_name} must be zero")
    if payload["qlib_batches_observed"] != "1/12 through 12/12":
        raise TerminalRuntimeWorkerMemoryEvidenceError("qlib batch observation is incomplete")
    task = _mapping(payload["successful_task"], "post_deploy_observation.successful_task")
    _exact_keys(
        task,
        {
            "task_id",
            "universe_id",
            "batch_count",
            "last_batch_instruments",
            "runtime_seconds",
            "outcome",
            "stored",
            "stock_count",
        },
        "post_deploy_observation.successful_task",
    )
    _token(task["task_id"], "successful_task.task_id")
    _token(task["universe_id"], "successful_task.universe_id")
    if _integer(task["batch_count"], "successful_task.batch_count") != 12:
        raise TerminalRuntimeWorkerMemoryEvidenceError("successful task batch_count must be 12")
    if _integer(task["last_batch_instruments"], "successful_task.last_batch_instruments") <= 0:
        raise TerminalRuntimeWorkerMemoryEvidenceError("successful task last batch is invalid")
    _finite_positive(task["runtime_seconds"], "successful_task.runtime_seconds")
    if task["outcome"] != "success":
        raise TerminalRuntimeWorkerMemoryEvidenceError("successful task outcome must be success")
    stored = _integer(task["stored"], "successful_task.stored")
    if stored != 1:
        raise TerminalRuntimeWorkerMemoryEvidenceError("successful task stored must be 1")
    _integer(task["stock_count"], "successful_task.stock_count")
    return window_start, window_end, window_seconds, maximum_memory_bytes, 12, "success", stored


def _validate_api_observation(
    payload: Mapping[str, object],
) -> tuple[int, int, int, bool, bool, bool]:
    """Validate health and explicit fail-closed decision/API flags."""

    _exact_keys(
        payload,
        {
            "health_status",
            "ready_status",
            "decision_ready_status",
            "decision_ready_must_not_use_for_decision",
            "runtime_flags_changed",
            "business_canary_submitted",
        },
        "api_observation",
    )
    health = _integer(payload["health_status"], "api_observation.health_status")
    ready = _integer(payload["ready_status"], "api_observation.ready_status")
    decision = _integer(payload["decision_ready_status"], "api_observation.decision_ready_status")
    if (health, ready) != (200, 200):
        raise TerminalRuntimeWorkerMemoryEvidenceError("api health/readiness must be 200")
    if decision != 503:
        raise TerminalRuntimeWorkerMemoryEvidenceError("decision-ready must remain 503")
    must_not_use = _boolean(
        payload["decision_ready_must_not_use_for_decision"],
        "api_observation.decision_ready_must_not_use_for_decision",
    )
    flags_changed = _boolean(
        payload["runtime_flags_changed"], "api_observation.runtime_flags_changed"
    )
    canary = _boolean(
        payload["business_canary_submitted"], "api_observation.business_canary_submitted"
    )
    if not must_not_use or flags_changed or canary:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            "api observation must remain fail-closed and flag/canary free"
        )
    return health, ready, decision, must_not_use, flags_changed, canary


def _validate_ci(
    payload: Mapping[str, object], expected: TerminalRuntimeWorkerMemoryEvidenceBinding
) -> None:
    """Ensure CI references the same immutable source commit."""

    _exact_keys(
        payload,
        {
            "head",
            "security_scan",
            "architecture_layer_guard",
            "consistency_check",
            "ci_fast_feedback",
        },
        "ci",
    )
    if payload["head"] != expected.candidate_commit:
        raise TerminalRuntimeWorkerMemoryEvidenceError("ci.head is not candidate-bound")
    for field_name in (
        "security_scan",
        "architecture_layer_guard",
        "consistency_check",
        "ci_fast_feedback",
    ):
        url = _text(payload[field_name], f"ci.{field_name}")
        if _CI_URL_RE.fullmatch(url) is None:
            raise TerminalRuntimeWorkerMemoryEvidenceError(f"ci.{field_name} is invalid")


def _validate_gate(payload: Mapping[str, object]) -> tuple[str, bool, bool]:
    """Require the artifact to retain its blocked, non-capacity decision."""

    _exact_keys(
        payload,
        {"tar01_exit_decision", "safety_ready", "capacity_ready", "remaining_production_evidence"},
        "gate",
    )
    if payload["tar01_exit_decision"] != "BLOCKED":
        raise TerminalRuntimeWorkerMemoryEvidenceError("tar01_exit_decision must remain BLOCKED")
    safety_ready = _boolean(payload["safety_ready"], "gate.safety_ready")
    capacity_ready = _boolean(payload["capacity_ready"], "gate.capacity_ready")
    if not safety_ready or capacity_ready:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            "gate must remain safety-ready but capacity-blocked"
        )
    remaining = tuple(
        _text(item, "gate.remaining_production_evidence")
        for item in _sequence(
            payload["remaining_production_evidence"], "gate.remaining_production_evidence"
        )
    )
    if frozenset(remaining) != _EXPECTED_REMAINING_EVIDENCE:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            "gate remaining evidence is incomplete or altered"
        )
    return "BLOCKED", safety_ready, capacity_ready


def validate_terminal_runtime_worker_memory_evidence(
    payload: Mapping[str, object],
    *,
    expected_candidate: TerminalRuntimeWorkerMemoryEvidenceBinding,
) -> TerminalRuntimeWorkerMemoryEvidenceReport:
    """Validate the existing QLib memory artifact against an external candidate identity."""

    if not isinstance(payload, Mapping):
        raise TerminalRuntimeWorkerMemoryEvidenceError("evidence must be an object")
    _exact_keys(payload, set(_EXPECTED_TOP_LEVEL_KEYS), "evidence")
    if (
        payload["schema_version"] != "1.0"
        or payload["artifact"] != "tar01-qlib-batch-memory-remediation"
    ):
        raise TerminalRuntimeWorkerMemoryEvidenceError("evidence schema/artifact is invalid")
    _validate_binding(expected_candidate)
    candidate = _mapping(payload["candidate"], "candidate")
    _validate_candidate(candidate, expected_candidate)
    observed_at = _utc_timestamp(payload["observed_at"], "observed_at")
    _validate_trigger(_mapping(payload["trigger_and_correction"], "trigger_and_correction"))
    _validate_deployment(_mapping(payload["deployment"], "deployment"), expected_candidate)
    worker = _mapping(payload["worker_contract"], "worker_contract")
    _validate_worker_contract(worker)
    observation = _mapping(payload["post_deploy_observation"], "post_deploy_observation")
    window_start, window_end, window_seconds, max_memory_bytes, batch_count, outcome, stored = (
        _validate_post_deploy_observation(observation)
    )
    if observed_at < window_end:
        raise TerminalRuntimeWorkerMemoryEvidenceError(
            "observed_at precedes observation window end"
        )
    api = _mapping(payload["api_observation"], "api_observation")
    health, ready, decision, must_not_use, flags_changed, canary = _validate_api_observation(api)
    _validate_ci(_mapping(payload["ci"], "ci"), expected_candidate)
    gate_decision, safety_ready, capacity_ready = _validate_gate(_mapping(payload["gate"], "gate"))
    return TerminalRuntimeWorkerMemoryEvidenceReport(
        candidate_commit=expected_candidate.candidate_commit,
        candidate_release=expected_candidate.candidate_release,
        image_id=expected_candidate.image_id,
        observed_at=observed_at,
        window_start=window_start,
        window_end=window_end,
        window_seconds=window_seconds,
        memory_limit_bytes=_MEMORY_LIMIT_BYTES,
        observed_max_memory_bytes=max_memory_bytes,
        batch_count=batch_count,
        task_outcome=outcome,
        stored=stored,
        health_status=health,
        ready_status=ready,
        decision_ready_status=decision,
        decision_ready_must_not_use_for_decision=must_not_use,
        runtime_flags_changed=flags_changed,
        business_canary_submitted=canary,
        tar01_exit_decision=gate_decision,
        safety_ready=safety_ready,
        capacity_ready=capacity_ready,
    )
