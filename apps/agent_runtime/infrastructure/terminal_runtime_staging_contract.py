"""Fail-closed manifest and approval contract for TAR-06 staging load.

The parser performs no network I/O.  It binds the immutable candidate, target,
isolated runtime, workload, and query maps to a short-lived explicit approval
before the staging harness can receive credentials or submit queued requests.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, cast
from urllib.parse import urlsplit

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineCandidate,
    required_baseline_metric_keys,
    required_concurrency_levels,
)
from apps.agent_runtime.application.terminal_runtime_slo import (
    terminal_runtime_slo_criteria,
)
from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix_digest,
)
from core.exceptions import ConfigurationError

_FORMAT: Final[str] = "terminal-runtime-staging-harness.v1"
_PREFLIGHT_FORMAT: Final[str] = "terminal-runtime-staging-preflight.v1"
_MAX_BYTES: Final[int] = 1024 * 1024
_MAX_APPROVAL_VALIDITY: Final[timedelta] = timedelta(days=1)
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_COMPUTED_BASELINE_KEYS: Final[frozenset[str]] = frozenset(
    {"web_p50_ms", "web_p95_ms", "web_p99_ms"}
)
_COMPUTED_SLO_KEYS: Final[frozenset[str]] = frozenset({"run_api_p95_ms"})
_KNOWN_PRODUCTION_HOSTS: Final[frozenset[str]] = frozenset({"demo.agomtrade.pro"})
_APPROVED_ACTIONS: Final[dict[str, bool]] = {
    "staging_network_load": True,
    "production_load": False,
    "fault_injection": False,
    "paid_provider_or_mcp_calls": False,
    "runtime_flag_changes": False,
}


class TerminalRuntimeStagingConfigurationError(ConfigurationError):
    """Raised before network I/O when a staging envelope is unsafe or malformed."""

    default_code = "TERMINAL_STAGING_CONFIGURATION_INVALID"


def _fail(message: str) -> TerminalRuntimeStagingConfigurationError:
    """Build one stable error without echoing untrusted configuration values."""

    return TerminalRuntimeStagingConfigurationError(message)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow one JSON object and require string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise _fail(f"{field_name} must be an object")
    return cast(Mapping[str, object], value)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    """Reject missing and unknown operational fields."""

    if set(value) != expected:
        raise _fail(f"{field_name} has an invalid key set")


def _token(value: object, field_name: str) -> str:
    """Require a bounded machine token."""

    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise _fail(f"{field_name} must be a stable token")
    return value


def _sha256(value: object, field_name: str) -> str:
    """Require a lowercase SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _fail(f"{field_name} must be a SHA-256 digest")
    return value


def _boolean(value: object, field_name: str) -> bool:
    """Require an exact JSON boolean."""

    if type(value) is not bool:
        raise _fail(f"{field_name} must be a boolean")
    return value


def _positive_integer(value: object, field_name: str, maximum: int) -> int:
    """Require a bounded positive integer while rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise _fail(f"{field_name} is outside its bounded range")
    return value


def _positive_number(value: object, field_name: str, maximum: float) -> float:
    """Require one finite positive operational number."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 < parsed <= maximum:
        raise _fail(f"{field_name} is outside its bounded range")
    return parsed


def _configuration_utc(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware UTC configuration clock."""

    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timedelta(0):
        raise _fail(f"{field_name} must be timezone-aware UTC")
    return value


def _utc_timestamp(value: object, field_name: str) -> datetime:
    """Parse one canonical UTC timestamp from an approval document."""

    if type(value) is not str or not value.endswith("Z"):
        raise _fail(f"{field_name} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _fail(f"{field_name} must be a UTC timestamp") from exc
    return _configuration_utc(parsed, field_name)


def _canonical_json(value: object) -> bytes:
    """Serialize one decoded configuration object deterministically."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _fail("staging envelope is not canonical JSON") from exc


def _host(value: object, field_name: str) -> str:
    """Require a bare normalized hostname without credentials or a port."""

    if type(value) is not str or not value or value.strip() != value:
        raise _fail(f"{field_name} is invalid")
    parsed = urlsplit(f"//{value}")
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise _fail(f"{field_name} must be a bare hostname")
    return parsed.hostname.casefold().rstrip(".")


def _url(value: object, field_name: str, *, allow_path: bool) -> tuple[str, str]:
    """Validate a credential-free HTTPS URL, allowing HTTP only on loopback."""

    if type(value) is not str or not value or value.strip() != value:
        raise _fail(f"{field_name} is invalid")
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    loopback = hostname in {"127.0.0.1", "::1", "localhost"}
    unsafe_path = any(segment in {".", ".."} for segment in parsed.path.split("/"))
    if (
        not hostname
        or parsed.scheme not in ({"http", "https"} if loopback else {"https"})
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or unsafe_path
        or (not allow_path and parsed.path not in ("", "/"))
    ):
        raise _fail(f"{field_name} must be a credential-free safe URL")
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    return normalized, hostname


def _host_is_forbidden(hostname: str, production_hosts: tuple[str, ...]) -> bool:
    """Reject an exact production hostname or one of its subdomains."""

    return any(
        hostname == production_host or hostname.endswith(f".{production_host}")
        for production_host in production_hosts
    )


@dataclass(frozen=True, slots=True)
class TerminalRuntimeStagingQuery:
    """One exact Prometheus expression or an explicit unavailable declaration."""

    key: str
    expression: str | None

    def __post_init__(self) -> None:
        """Validate query text without accepting empty or oversized expressions."""

        _token(self.key, "query.key")
        if self.expression is not None and (
            type(self.expression) is not str
            or not self.expression.strip()
            or self.expression.strip() != self.expression
            or len(self.expression) > 4096
        ):
            raise _fail("query.expression is invalid")


@dataclass(frozen=True, slots=True)
class TerminalRuntimeStagingRuntimeEnvelope:
    """Exact isolated-worker profile authorized for one staging load run."""

    dedicated_worker_service: str
    dedicated_worker_queue: str
    worker_concurrency: int
    worker_prefetch_multiplier: int
    worker_memory_limit_bytes: int
    worker_cpu_limit: float
    worker_heartbeat_max_age_seconds: int
    legacy_inline_concurrency: int
    staging_runtime_authorized: bool
    queued_intake_enabled: bool
    queued_worker_enabled: bool
    provider_execution_mode: str
    mcp_execution_mode: str


@dataclass(frozen=True, slots=True)
class TerminalRuntimeStagingApproval:
    """Parsed current approval bound to every executable manifest field."""

    authorization_id: str
    approved_by: str
    issued_at: datetime
    expires_at: datetime
    envelope_sha256: str


@dataclass(frozen=True, slots=True)
class TerminalRuntimeStagingSpecification:
    """Validated non-production target, candidate, budget, and query envelope."""

    environment: str
    candidate_identity: TerminalRuntimeBaselineCandidate
    base_url: str
    prometheus_url: str
    production_hosts: tuple[str, ...]
    task_id: int
    repetitions: int
    request_timeout_seconds: float
    approved_preflight_sha256: str
    runtime: TerminalRuntimeStagingRuntimeEnvelope
    approval: TerminalRuntimeStagingApproval
    manifest_sha256: str
    baseline_metric_queries: tuple[TerminalRuntimeStagingQuery, ...]
    slo_queries: tuple[TerminalRuntimeStagingQuery, ...]

    @property
    def total_request_budget(self) -> int:
        """Return the exact 1+5+10+20 request total across repetitions."""

        return sum(required_concurrency_levels()) * self.repetitions

    def baseline_query(self, key: str) -> TerminalRuntimeStagingQuery:
        """Return the exact baseline query registered for a required key."""

        return next(item for item in self.baseline_metric_queries if item.key == key)

    def slo_query(self, key: str) -> TerminalRuntimeStagingQuery:
        """Return the exact hard-SLO query registered for a required key."""

        return next(item for item in self.slo_queries if item.key == key)


def _parse_query_map(
    value: object,
    *,
    field_name: str,
    expected_keys: frozenset[str],
) -> tuple[TerminalRuntimeStagingQuery, ...]:
    """Parse an exact query map while preserving explicit null entries."""

    raw = _mapping(value, field_name)
    if set(raw) != expected_keys:
        raise _fail(f"{field_name} must contain every exact required key")
    queries: list[TerminalRuntimeStagingQuery] = []
    for key in sorted(expected_keys):
        expression = raw[key]
        if expression is not None and type(expression) is not str:
            raise _fail(f"{field_name} contains an invalid expression")
        queries.append(TerminalRuntimeStagingQuery(key=key, expression=expression))
    return tuple(queries)


def _staging_envelope_sha256(manifest: Mapping[str, object]) -> str:
    """Hash every executable manifest field except the approval file digest."""

    envelope = dict(manifest)
    if "approved_preflight_sha256" not in envelope:
        raise _fail("manifest omitted the approval digest")
    del envelope["approved_preflight_sha256"]
    return hashlib.sha256(_canonical_json(envelope)).hexdigest()


def _parse_runtime_envelope(value: object) -> TerminalRuntimeStagingRuntimeEnvelope:
    """Parse the exact isolated, non-billable staging worker profile."""

    runtime = _mapping(value, "runtime")
    _exact_keys(
        runtime,
        frozenset(
            {
                "dedicated_worker_service",
                "dedicated_worker_queue",
                "worker_concurrency",
                "worker_prefetch_multiplier",
                "worker_memory_limit_bytes",
                "worker_cpu_limit",
                "worker_heartbeat_max_age_seconds",
                "legacy_inline_concurrency",
                "staging_runtime_authorized",
                "queued_intake_enabled",
                "queued_worker_enabled",
                "provider_execution_mode",
                "mcp_execution_mode",
            }
        ),
        "runtime",
    )
    worker_service = _token(runtime["dedicated_worker_service"], "runtime worker service")
    worker_queue = _token(runtime["dedicated_worker_queue"], "runtime worker queue")
    if worker_service != "terminal_agent_worker" or worker_queue != "terminal_agent":
        raise _fail("runtime dedicated worker identity is invalid")
    worker_concurrency = _positive_integer(
        runtime["worker_concurrency"], "runtime.worker_concurrency", 20
    )
    worker_prefetch = _positive_integer(
        runtime["worker_prefetch_multiplier"], "runtime.worker_prefetch_multiplier", 16
    )
    if worker_prefetch != 1:
        raise _fail("runtime worker prefetch must remain one")
    worker_memory = _positive_integer(
        runtime["worker_memory_limit_bytes"],
        "runtime.worker_memory_limit_bytes",
        64 * 1024 * 1024 * 1024,
    )
    if worker_memory < 128 * 1024 * 1024:
        raise _fail("runtime worker memory limit is too small")
    worker_cpu = _positive_number(runtime["worker_cpu_limit"], "runtime.worker_cpu_limit", 64.0)
    heartbeat_max_age = _positive_integer(
        runtime["worker_heartbeat_max_age_seconds"],
        "runtime.worker_heartbeat_max_age_seconds",
        120,
    )
    legacy_inline = _positive_integer(
        runtime["legacy_inline_concurrency"], "runtime.legacy_inline_concurrency", 20
    )
    if legacy_inline != 1:
        raise _fail("legacy inline concurrency must remain one")
    runtime_authorized = _boolean(
        runtime["staging_runtime_authorized"], "runtime.staging_runtime_authorized"
    )
    queued_intake_enabled = _boolean(
        runtime["queued_intake_enabled"], "runtime.queued_intake_enabled"
    )
    queued_worker_enabled = _boolean(
        runtime["queued_worker_enabled"], "runtime.queued_worker_enabled"
    )
    if not (runtime_authorized and queued_intake_enabled and queued_worker_enabled):
        raise _fail("staging runtime, intake, and worker must already be enabled")
    provider_mode = _token(runtime["provider_execution_mode"], "runtime provider mode")
    if provider_mode != "non_billable_stub":
        raise _fail("runtime provider must be a non-billable staging stub")
    mcp_mode = _token(runtime["mcp_execution_mode"], "runtime MCP mode")
    if mcp_mode != "disabled":
        raise _fail("runtime MCP execution must remain disabled")
    return TerminalRuntimeStagingRuntimeEnvelope(
        dedicated_worker_service=worker_service,
        dedicated_worker_queue=worker_queue,
        worker_concurrency=worker_concurrency,
        worker_prefetch_multiplier=worker_prefetch,
        worker_memory_limit_bytes=worker_memory,
        worker_cpu_limit=worker_cpu,
        worker_heartbeat_max_age_seconds=heartbeat_max_age,
        legacy_inline_concurrency=legacy_inline,
        staging_runtime_authorized=runtime_authorized,
        queued_intake_enabled=queued_intake_enabled,
        queued_worker_enabled=queued_worker_enabled,
        provider_execution_mode=provider_mode,
        mcp_execution_mode=mcp_mode,
    )


def _parse_staging_approval(
    payload: bytes,
    *,
    expected_digest: str,
    expected_envelope_sha256: str,
    observed_at: datetime,
) -> TerminalRuntimeStagingApproval:
    """Validate one current explicit approval for the exact staging envelope."""

    if type(payload) is not bytes or not payload or len(payload) > _MAX_BYTES:
        raise _fail("approved preflight bytes are invalid")
    if hashlib.sha256(payload).hexdigest() != expected_digest:
        raise _fail("approved preflight digest does not match")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("approved preflight is not valid UTF-8 JSON") from exc
    preflight = _mapping(decoded, "approved preflight")
    _exact_keys(
        preflight,
        frozenset(
            {
                "format",
                "decision",
                "authorization_id",
                "approved_by",
                "issued_at",
                "expires_at",
                "envelope_sha256",
                "allowed_actions",
            }
        ),
        "approved preflight",
    )
    if preflight["format"] != _PREFLIGHT_FORMAT:
        raise _fail("approved preflight format is unsupported")
    if preflight["decision"] != "approved":
        raise _fail("approved preflight decision must be approved")
    authorization_id = _token(preflight["authorization_id"], "approval.authorization_id")
    approved_by = _token(preflight["approved_by"], "approval.approved_by")
    issued_at = _utc_timestamp(preflight["issued_at"], "approval.issued_at")
    expires_at = _utc_timestamp(preflight["expires_at"], "approval.expires_at")
    current = _configuration_utc(observed_at, "approval observed_at")
    if expires_at <= issued_at or expires_at - issued_at > _MAX_APPROVAL_VALIDITY:
        raise _fail("approved preflight validity window is invalid")
    if current < issued_at:
        raise _fail("approved preflight is not yet valid")
    if current >= expires_at:
        raise _fail("approved preflight has expired")
    envelope_sha256 = _sha256(preflight["envelope_sha256"], "approval.envelope_sha256")
    if envelope_sha256 != expected_envelope_sha256:
        raise _fail("approved preflight envelope binding does not match")
    actions = _mapping(preflight["allowed_actions"], "approval.allowed_actions")
    if set(actions) != set(_APPROVED_ACTIONS):
        raise _fail("approved preflight action scope is incomplete")
    for key, expected in _APPROVED_ACTIONS.items():
        if _boolean(actions[key], f"approval.allowed_actions.{key}") is not expected:
            raise _fail("approved preflight action scope is unsafe")
    return TerminalRuntimeStagingApproval(
        authorization_id=authorization_id,
        approved_by=approved_by,
        issued_at=issued_at,
        expires_at=expires_at,
        envelope_sha256=envelope_sha256,
    )


def parse_terminal_runtime_staging_manifest(
    payload: bytes,
    *,
    approved_preflight: bytes,
    observed_at: datetime | None = None,
) -> TerminalRuntimeStagingSpecification:
    """Parse and approve one exact staging manifest without performing I/O."""

    if type(payload) is not bytes or not payload or len(payload) > _MAX_BYTES:
        raise _fail("staging manifest bytes are invalid")
    if type(approved_preflight) is not bytes or not approved_preflight:
        raise _fail("approved preflight bytes are required")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("staging manifest is not valid UTF-8 JSON") from exc
    top = _mapping(decoded, "manifest")
    _exact_keys(
        top,
        frozenset(
            {
                "format",
                "environment",
                "candidate",
                "target",
                "runtime",
                "workload",
                "approved_preflight_sha256",
                "baseline_metric_queries",
                "slo_queries",
            }
        ),
        "manifest",
    )
    if top["format"] != _FORMAT:
        raise _fail("staging manifest format is unsupported")
    environment = _token(top["environment"], "environment")
    if not environment.startswith(("staging-", "local-")):
        raise _fail("environment must identify non-production staging")
    candidate_raw = _mapping(top["candidate"], "candidate")
    _exact_keys(
        candidate_raw,
        frozenset(
            {
                "candidate_commit",
                "candidate_release",
                "oci_revision",
                "runtime_manifest_digest",
                "test_matrix_digest",
            }
        ),
        "candidate",
    )
    try:
        candidate = TerminalRuntimeBaselineCandidate(
            candidate_commit=cast(str, candidate_raw["candidate_commit"]),
            candidate_release=cast(str, candidate_raw["candidate_release"]),
            oci_revision=cast(str, candidate_raw["oci_revision"]),
            runtime_manifest_digest=cast(str, candidate_raw["runtime_manifest_digest"]),
            test_matrix_digest=cast(str, candidate_raw["test_matrix_digest"]),
        )
    except (TypeError, ValueError) as exc:
        raise _fail("candidate identity is invalid") from exc
    if candidate.test_matrix_digest != canonical_terminal_runtime_test_matrix_digest():
        raise _fail("candidate test matrix digest is not canonical")
    target = _mapping(top["target"], "target")
    _exact_keys(target, frozenset({"base_url", "prometheus_url", "production_hosts"}), "target")
    raw_production_hosts = target["production_hosts"]
    if not isinstance(raw_production_hosts, list) or not raw_production_hosts:
        raise _fail("production host denylist must be non-empty")
    declared_hosts = tuple(
        _host(item, "target.production_hosts[]") for item in raw_production_hosts
    )
    if len(set(declared_hosts)) != len(declared_hosts):
        raise _fail("production host denylist contains duplicates")
    production_hosts = tuple(sorted(_KNOWN_PRODUCTION_HOSTS | set(declared_hosts)))
    base_url, base_host = _url(target["base_url"], "target.base_url", allow_path=False)
    prometheus_url, prometheus_host = _url(
        target["prometheus_url"], "target.prometheus_url", allow_path=True
    )
    if _host_is_forbidden(base_host, production_hosts) or _host_is_forbidden(
        prometheus_host, production_hosts
    ):
        raise _fail("production target is forbidden for the staging harness")
    runtime = _parse_runtime_envelope(top["runtime"])
    workload = _mapping(top["workload"], "workload")
    _exact_keys(
        workload,
        frozenset({"task_id", "repetitions", "request_timeout_seconds"}),
        "workload",
    )
    task_id = _positive_integer(workload["task_id"], "workload.task_id", 2_147_483_647)
    repetitions = _positive_integer(workload["repetitions"], "workload.repetitions", 10)
    timeout = _positive_number(
        workload["request_timeout_seconds"], "workload.request_timeout_seconds", 30.0
    )
    expected_preflight_sha256 = _sha256(
        top["approved_preflight_sha256"], "approved_preflight_sha256"
    )
    baseline_queries = _parse_query_map(
        top["baseline_metric_queries"],
        field_name="baseline_metric_queries",
        expected_keys=required_baseline_metric_keys() - _COMPUTED_BASELINE_KEYS,
    )
    heartbeat_query = next(
        item for item in baseline_queries if item.key == "worker_heartbeat_age_seconds"
    )
    if heartbeat_query.expression is None:
        raise _fail("worker heartbeat query is required before staging load")
    slo_queries = _parse_query_map(
        top["slo_queries"],
        field_name="slo_queries",
        expected_keys=frozenset(item.key for item in terminal_runtime_slo_criteria())
        - _COMPUTED_SLO_KEYS,
    )
    approval = _parse_staging_approval(
        approved_preflight,
        expected_digest=expected_preflight_sha256,
        expected_envelope_sha256=_staging_envelope_sha256(top),
        observed_at=observed_at or datetime.now(UTC),
    )
    return TerminalRuntimeStagingSpecification(
        environment=environment,
        candidate_identity=candidate,
        base_url=base_url,
        prometheus_url=prometheus_url,
        production_hosts=production_hosts,
        task_id=task_id,
        repetitions=repetitions,
        request_timeout_seconds=timeout,
        approved_preflight_sha256=expected_preflight_sha256,
        runtime=runtime,
        approval=approval,
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
        baseline_metric_queries=baseline_queries,
        slo_queries=slo_queries,
    )


__all__ = [
    "TerminalRuntimeStagingApproval",
    "TerminalRuntimeStagingConfigurationError",
    "TerminalRuntimeStagingQuery",
    "TerminalRuntimeStagingRuntimeEnvelope",
    "TerminalRuntimeStagingSpecification",
    "parse_terminal_runtime_staging_manifest",
]
