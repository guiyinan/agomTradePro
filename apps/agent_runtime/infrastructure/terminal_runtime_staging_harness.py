"""Concrete fail-closed staging harness for TAR-06 capacity observations.

The harness is intentionally opt-in and refuses known production targets.  It
drives the queued Terminal API with twenty distinct staging actors, collects
Prometheus values through explicit query mappings, and implements the typed
command/load/metric ports consumed by ``TerminalRuntimeBaselineControlledObserver``.
It never changes runtime flags, starts workers, injects faults, or records
credentials in its source receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Barrier, BrokenBarrierError, Lock
from typing import Final, Protocol, cast

import requests

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineMetric,
    TerminalRuntimeBaselineMetricStatus,
    required_baseline_metric_keys,
    required_concurrency_levels,
)
from apps.agent_runtime.application.terminal_runtime_baseline_collector import (
    TerminalRuntimeBaselineCollectionRequest,
    TerminalRuntimeBaselineObservationRequest,
)
from apps.agent_runtime.application.terminal_runtime_slo import (
    TerminalRuntimeSloMeasurement,
    TerminalRuntimeSloStatus,
    terminal_runtime_slo_criteria,
)
from apps.agent_runtime.infrastructure.terminal_runtime_controlled_observer import (
    TerminalRuntimeBaselineCommandReceipt,
    TerminalRuntimeBaselineLoadReceipt,
    TerminalRuntimeBaselineMetricSnapshot,
    TerminalRuntimeBaselineSloSnapshot,
)
from apps.agent_runtime.infrastructure.terminal_runtime_staging_contract import (
    TerminalRuntimeStagingApproval,
    TerminalRuntimeStagingConfigurationError,
    TerminalRuntimeStagingQuery,
    TerminalRuntimeStagingRuntimeEnvelope,
    TerminalRuntimeStagingSpecification,
    parse_terminal_runtime_staging_manifest,
)
from core.exceptions import ExternalServiceError
from shared.numeric import safe_float

_SOURCE_FORMAT: Final[str] = "terminal-runtime-staging-source.v1"
_RUN_PATH: Final[str] = "/api/terminal/runs/"
_QUEUE_PATH: Final[str] = "/api/terminal/runs/queue/"
_HEALTH_PATH: Final[str] = "/api/health/"
_PROMETHEUS_QUERY_PATH: Final[str] = "/api/v1/query"
_REQUEST_TEMPLATE: Final[str] = "Return STAGING_OK without tools."
_MAX_RESPONSE_BYTES: Final[int] = 1024 * 1024
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_ALLOWED_REJECTION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "per_user_active_limit",
        "per_user_queued_limit",
        "global_active_limit",
        "global_queued_limit",
    }
)


class TerminalRuntimeStagingObservationError(ExternalServiceError):
    """Raised when staging HTTP or metric evidence violates its contract."""

    default_code = "TERMINAL_STAGING_OBSERVATION_FAILED"


def _configuration_error(message: str) -> TerminalRuntimeStagingConfigurationError:
    """Build a stable configuration error without echoing untrusted values."""

    return TerminalRuntimeStagingConfigurationError(message)


def _observation_error(message: str) -> TerminalRuntimeStagingObservationError:
    """Build a stable observation error without response bodies or credentials."""

    return TerminalRuntimeStagingObservationError(message)


def _observation_mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow one external response object without classifying it as config."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise _observation_error(f"{field_name} is not a JSON object")
    return cast(Mapping[str, object], value)


def _token(value: object, field_name: str) -> str:
    """Require a bounded machine token."""

    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise _configuration_error(f"{field_name} must be a stable token")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware observation clock."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise _observation_error(f"{field_name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    """Serialize one aware clock as canonical UTC text."""

    _aware(value, "timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class TerminalRuntimeStagingActor:
    """One distinct staging identity; its API token is never serialized."""

    alias: str
    api_token: str = field(repr=False)

    def __post_init__(self) -> None:
        """Reject aliases or credentials that cannot be safely transported."""

        _token(self.alias, "actor.alias")
        if (
            type(self.api_token) is not str
            or not self.api_token
            or len(self.api_token) > 4096
            or any(character.isspace() for character in self.api_token)
        ):
            raise _configuration_error("actor API token is invalid")


@dataclass(frozen=True, slots=True)
class TerminalRuntimePrometheusCredentials:
    """Interactive Prometheus credentials that are excluded from receipts."""

    username: str = field(repr=False)
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        """Reject blank or control-character-bearing credentials."""

        for value, field_name in (
            (self.username, "Prometheus username"),
            (self.password, "Prometheus password"),
        ):
            if (
                type(value) is not str
                or not value
                or len(value) > 4096
                or "\r" in value
                or "\n" in value
            ):
                raise _configuration_error(f"{field_name} is invalid")


@dataclass(frozen=True, slots=True)
class TerminalRuntimeStagingPreflightObservation:
    """Read-only target health and queued-route readiness observation."""

    captured_at: datetime
    health_status_code: int
    queue_status_code: int
    worker_ready: bool

    def __post_init__(self) -> None:
        """Validate status and clock types without declaring them successful."""

        _aware(self.captured_at, "preflight.captured_at")
        for value in (self.health_status_code, self.queue_status_code):
            if type(value) is not int or not 100 <= value <= 599:
                raise _observation_error("preflight status code is invalid")
        if type(self.worker_ready) is not bool:
            raise _observation_error("preflight worker readiness is invalid")


@dataclass(frozen=True, slots=True)
class TerminalRuntimeStagingRequestObservation:
    """Secret-free result for one queued API submission."""

    actor_alias: str
    run_id: str | None
    status_code: int
    reason_code: str | None
    elapsed_ms: float
    captured_at: datetime

    def __post_init__(self) -> None:
        """Require either a bound acceptance or a canonical bounded rejection."""

        _token(self.actor_alias, "observation.actor_alias")
        _aware(self.captured_at, "observation.captured_at")
        if not math.isfinite(self.elapsed_ms) or self.elapsed_ms < 0:
            raise _observation_error("request elapsed time is invalid")
        if self.status_code == 202:
            if self.run_id is None:
                raise _observation_error("accepted response omitted the requested run ID")
            _token(self.run_id, "observation.run_id")
            if self.reason_code is not None:
                raise _observation_error("accepted response carried a rejection reason")
        elif self.status_code == 429:
            if self.run_id is not None or self.reason_code not in _ALLOWED_REJECTION_REASONS:
                raise _observation_error("bounded rejection response is inconsistent")
        else:
            raise _observation_error("queued submission returned an uncontracted status")


class TerminalRuntimeStagingHttpPort(Protocol):
    """External staging API port used by the bounded load harness."""

    def preflight(
        self, actor: TerminalRuntimeStagingActor
    ) -> TerminalRuntimeStagingPreflightObservation:
        """Read health and queue readiness without mutating runtime state."""

        ...

    def submit(
        self,
        *,
        actor: TerminalRuntimeStagingActor,
        task_id: int,
        message: str,
        run_id: str,
        client_request_id: str,
    ) -> TerminalRuntimeStagingRequestObservation:
        """Submit one bounded queued run using a staging-only actor."""

        ...


class TerminalRuntimePrometheusPort(Protocol):
    """Read one numeric Prometheus instant-vector observation."""

    def query(self, expression: str) -> float | None:
        """Return one value or None when the query has no sample."""

        ...


class TerminalRuntimeStagingClock(Protocol):
    """Inject an aware clock so approval-window checks remain deterministic."""

    def __call__(self) -> datetime:
        """Return the current aware time."""

        ...


def _system_utc_now() -> datetime:
    """Return the production approval-check clock."""

    return datetime.now(UTC)


def _percentile(values: Sequence[float], quantile: float) -> float:
    """Return a linear-interpolated percentile for a non-empty sample."""

    if not values:
        raise _observation_error("request latency sample is empty")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


class TerminalRuntimeStagingHarness:
    """Implement concrete controlled-observer ports for an approved staging target."""

    def __init__(
        self,
        *,
        specification: TerminalRuntimeStagingSpecification,
        actors: tuple[TerminalRuntimeStagingActor, ...],
        http_port: TerminalRuntimeStagingHttpPort,
        prometheus_port: TerminalRuntimePrometheusPort,
        clock: TerminalRuntimeStagingClock | None = None,
    ) -> None:
        """Bind exact actors and external adapters without performing I/O."""

        if type(specification) is not TerminalRuntimeStagingSpecification:
            raise _configuration_error("staging specification type is invalid")
        if type(actors) is not tuple or len(actors) != 20:
            raise _configuration_error("exactly twenty staging actors are required")
        if any(type(actor) is not TerminalRuntimeStagingActor for actor in actors):
            raise _configuration_error("staging actor type is invalid")
        aliases = tuple(actor.alias for actor in actors)
        token_digests = tuple(
            hashlib.sha256(actor.api_token.encode("utf-8")).digest() for actor in actors
        )
        if len(set(aliases)) != 20 or len(set(token_digests)) != 20:
            raise _configuration_error(
                "twenty distinct staging actors and credentials are required"
            )
        self.specification = specification
        self._actors = actors
        self._http_port = http_port
        self._prometheus_port = prometheus_port
        self._clock = clock or _system_utc_now
        self._lock = Lock()
        self._preflight: TerminalRuntimeStagingPreflightObservation | None = None
        self._authorized_levels: set[int] = set()
        self._attempted_levels: set[int] = set()
        self._level_observations: dict[
            int, tuple[TerminalRuntimeStagingRequestObservation, ...]
        ] = {}
        self._metric_snapshots: dict[int, TerminalRuntimeBaselineMetricSnapshot] = {}
        self._slo_snapshot: TerminalRuntimeBaselineSloSnapshot | None = None
        self._worker_heartbeat_age_by_level: dict[int, float] = {}

    def _require_current_approval(self) -> None:
        """Reject network work outside the parsed approval's exact UTC window."""

        current = _aware(self._clock(), "approval observed_at").astimezone(UTC)
        approval = self.specification.approval
        if current < approval.issued_at or current >= approval.expires_at:
            raise _observation_error("staging approval is not currently valid")

    def _validate_level_request(self, request: TerminalRuntimeBaselineObservationRequest) -> None:
        """Require the exact configured environment and candidate."""

        if (
            type(request) is not TerminalRuntimeBaselineObservationRequest
            or request.environment != self.specification.environment
            or request.candidate_identity != self.specification.candidate_identity
            or request.concurrency not in required_concurrency_levels()
        ):
            raise _observation_error("staging request identity changed")

    def execute(
        self, request: TerminalRuntimeBaselineObservationRequest
    ) -> TerminalRuntimeBaselineCommandReceipt:
        """Authorize one level after current approval and live-worker checks."""

        self._validate_level_request(request)
        self._require_current_approval()
        with self._lock:
            if (
                request.concurrency in self._authorized_levels
                or request.concurrency in self._attempted_levels
                or request.concurrency in self._level_observations
            ):
                raise _observation_error(
                    "staging concurrency level was already authorized or attempted"
                )
            if self._preflight is None:
                preflight = self._http_port.preflight(self._actors[0])
                if type(preflight) is not TerminalRuntimeStagingPreflightObservation:
                    raise _observation_error("staging preflight receipt type is invalid")
                if (
                    preflight.health_status_code != 200
                    or preflight.queue_status_code != 200
                    or not preflight.worker_ready
                ):
                    raise _observation_error("staging preflight did not pass")
                prometheus_probe = self._prometheus_port.query("vector(1)")
                if prometheus_probe != 1.0:
                    raise _observation_error("staging Prometheus preflight did not pass")
                self._preflight = preflight
            heartbeat_query = self.specification.baseline_query("worker_heartbeat_age_seconds")
            if heartbeat_query.expression is None:
                raise _observation_error("staging worker heartbeat query is unavailable")
            worker_heartbeat_age = self._prometheus_port.query(heartbeat_query.expression)
            if (
                worker_heartbeat_age is None
                or not math.isfinite(worker_heartbeat_age)
                or worker_heartbeat_age < 0
                or worker_heartbeat_age
                > self.specification.runtime.worker_heartbeat_max_age_seconds
            ):
                raise _observation_error("staging worker heartbeat is stale or unavailable")
            self._worker_heartbeat_age_by_level[request.concurrency] = worker_heartbeat_age
            self._authorized_levels.add(request.concurrency)
        return TerminalRuntimeBaselineCommandReceipt(
            environment=request.environment,
            candidate_identity=request.candidate_identity,
            concurrency=request.concurrency,
        )

    def _submit_one(
        self,
        actor: TerminalRuntimeStagingActor,
        start_barrier: Barrier,
    ) -> TerminalRuntimeStagingRequestObservation:
        """Submit one identity-bound queued request with generated idempotency IDs."""

        try:
            start_barrier.wait(timeout=self.specification.request_timeout_seconds)
        except BrokenBarrierError as exc:
            raise _observation_error("staging concurrency barrier failed") from exc
        run_id = f"run-tar06-{uuid.uuid4().hex}"
        client_request_id = f"tar06-{uuid.uuid4().hex}"
        observation = self._http_port.submit(
            actor=actor,
            task_id=self.specification.task_id,
            message=_REQUEST_TEMPLATE,
            run_id=run_id,
            client_request_id=client_request_id,
        )
        if type(observation) is not TerminalRuntimeStagingRequestObservation:
            raise _observation_error("queued submission receipt type is invalid")
        if observation.actor_alias != actor.alias:
            raise _observation_error("queued submission actor identity changed")
        if observation.status_code == 202 and observation.run_id != run_id:
            raise _observation_error("queued submission run identity changed")
        return observation

    def run(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
        command: TerminalRuntimeBaselineCommandReceipt,
    ) -> TerminalRuntimeBaselineLoadReceipt:
        """Execute one exact concurrency level across distinct staging actors."""

        self._validate_level_request(request)
        if (
            type(command) is not TerminalRuntimeBaselineCommandReceipt
            or command.environment != request.environment
            or command.candidate_identity != request.candidate_identity
            or command.concurrency != request.concurrency
        ):
            raise _observation_error("staging command binding changed")
        with self._lock:
            if request.concurrency not in self._authorized_levels:
                raise _observation_error(
                    "staging concurrency level was not authorized by current preflight"
                )
            self._authorized_levels.remove(request.concurrency)
            if (
                request.concurrency in self._attempted_levels
                or request.concurrency in self._level_observations
            ):
                raise _observation_error("staging concurrency level was already attempted")
            self._attempted_levels.add(request.concurrency)
        self._require_current_approval()

        observations: list[TerminalRuntimeStagingRequestObservation] = []
        level_actors = self._actors[: request.concurrency]
        for _ in range(self.specification.repetitions):
            start_barrier = Barrier(request.concurrency)
            with ThreadPoolExecutor(
                max_workers=request.concurrency,
                thread_name_prefix=f"tar06-level-{request.concurrency}",
            ) as executor:
                futures: tuple[Future[TerminalRuntimeStagingRequestObservation], ...] = tuple(
                    executor.submit(self._submit_one, actor, start_barrier)
                    for actor in level_actors
                )
                observations.extend(future.result() for future in futures)
        frozen = tuple(observations)
        with self._lock:
            self._level_observations[request.concurrency] = frozen
        return TerminalRuntimeBaselineLoadReceipt(
            environment=request.environment,
            candidate_identity=request.candidate_identity,
            concurrency=request.concurrency,
            sample_count=len(frozen),
        )

    def _metric_from_query(self, key: str) -> TerminalRuntimeBaselineMetric:
        """Read one baseline query without turning failure or absence into zero."""

        query = self.specification.baseline_query(key)
        if query.expression is None:
            return TerminalRuntimeBaselineMetric(
                key=key,
                status=TerminalRuntimeBaselineMetricStatus.UNAVAILABLE,
                value=None,
                reason="query_not_configured",
            )
        try:
            value = self._prometheus_port.query(query.expression)
        except TerminalRuntimeStagingObservationError:
            return TerminalRuntimeBaselineMetric(
                key=key,
                status=TerminalRuntimeBaselineMetricStatus.UNAVAILABLE,
                value=None,
                reason="prometheus_query_failed",
            )
        if value is None:
            return TerminalRuntimeBaselineMetric(
                key=key,
                status=TerminalRuntimeBaselineMetricStatus.UNAVAILABLE,
                value=None,
                reason="prometheus_no_sample",
            )
        if not math.isfinite(value) or value < 0:
            return TerminalRuntimeBaselineMetric(
                key=key,
                status=TerminalRuntimeBaselineMetricStatus.UNAVAILABLE,
                value=None,
                reason="prometheus_value_invalid",
            )
        return TerminalRuntimeBaselineMetric(
            key=key,
            status=TerminalRuntimeBaselineMetricStatus.OBSERVED,
            value=value,
        )

    def collect(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
        load: TerminalRuntimeBaselineLoadReceipt,
    ) -> TerminalRuntimeBaselineMetricSnapshot:
        """Compute HTTP percentiles and read every remaining baseline metric."""

        self._validate_level_request(request)
        self._require_current_approval()
        if (
            type(load) is not TerminalRuntimeBaselineLoadReceipt
            or load.environment != request.environment
            or load.candidate_identity != request.candidate_identity
            or load.concurrency != request.concurrency
        ):
            raise _observation_error("staging load binding changed")
        observations = self._level_observations.get(request.concurrency)
        if observations is None or len(observations) != load.sample_count:
            raise _observation_error("staging load observations are incomplete")
        latencies = tuple(item.elapsed_ms for item in observations)
        web_metrics = {
            "web_p50_ms": _percentile(latencies, 0.50),
            "web_p95_ms": _percentile(latencies, 0.95),
            "web_p99_ms": _percentile(latencies, 0.99),
        }
        metrics = tuple(
            (
                TerminalRuntimeBaselineMetric(
                    key=key,
                    status=TerminalRuntimeBaselineMetricStatus.OBSERVED,
                    value=web_metrics[key],
                )
                if key in web_metrics
                else self._metric_from_query(key)
            )
            for key in sorted(required_baseline_metric_keys())
        )
        snapshot = TerminalRuntimeBaselineMetricSnapshot(
            environment=request.environment,
            candidate_identity=request.candidate_identity,
            concurrency=request.concurrency,
            captured_at=datetime.now(UTC),
            metrics=metrics,
        )
        with self._lock:
            self._metric_snapshots[request.concurrency] = snapshot
        return snapshot

    def _slo_from_query(self, key: str, *, count_value: bool) -> TerminalRuntimeSloMeasurement:
        """Read one SLO value, preserving absent, failed, or non-integral counts."""

        query = self.specification.slo_query(key)
        if query.expression is None:
            return TerminalRuntimeSloMeasurement(
                key=key,
                status=TerminalRuntimeSloStatus.UNAVAILABLE,
                value=None,
                reason="query_not_configured",
            )
        try:
            value = self._prometheus_port.query(query.expression)
        except TerminalRuntimeStagingObservationError:
            return TerminalRuntimeSloMeasurement(
                key=key,
                status=TerminalRuntimeSloStatus.UNAVAILABLE,
                value=None,
                reason="prometheus_query_failed",
            )
        if value is None:
            return TerminalRuntimeSloMeasurement(
                key=key,
                status=TerminalRuntimeSloStatus.UNAVAILABLE,
                value=None,
                reason="prometheus_no_sample",
            )
        if not math.isfinite(value) or value < 0 or (count_value and not value.is_integer()):
            return TerminalRuntimeSloMeasurement(
                key=key,
                status=TerminalRuntimeSloStatus.UNAVAILABLE,
                value=None,
                reason="prometheus_value_invalid",
            )
        normalized: float | int = int(value) if count_value else value
        return TerminalRuntimeSloMeasurement(
            key=key,
            status=TerminalRuntimeSloStatus.OBSERVED,
            value=normalized,
        )

    def collect_slo(
        self, request: TerminalRuntimeBaselineCollectionRequest
    ) -> TerminalRuntimeBaselineSloSnapshot:
        """Build all hard SLO measurements from load timings and exact queries."""

        self._require_current_approval()
        if (
            type(request) is not TerminalRuntimeBaselineCollectionRequest
            or request.environment != self.specification.environment
            or request.candidate_identity != self.specification.candidate_identity
            or set(self._level_observations) != required_concurrency_levels()
            or set(self._metric_snapshots) != required_concurrency_levels()
        ):
            raise _observation_error("staging SLO collection identity or levels are incomplete")
        all_latencies = tuple(
            observation.elapsed_ms
            for level in sorted(self._level_observations)
            for observation in self._level_observations[level]
        )
        measurements: list[TerminalRuntimeSloMeasurement] = []
        for criterion in terminal_runtime_slo_criteria():
            if criterion.key == "run_api_p95_ms":
                measurements.append(
                    TerminalRuntimeSloMeasurement(
                        key=criterion.key,
                        status=TerminalRuntimeSloStatus.OBSERVED,
                        value=_percentile(all_latencies, 0.95),
                    )
                )
            else:
                measurements.append(
                    self._slo_from_query(
                        criterion.key,
                        count_value=criterion.unit == "count",
                    )
                )
        snapshot = TerminalRuntimeBaselineSloSnapshot(
            environment=request.environment,
            candidate_identity=request.candidate_identity,
            captured_at=datetime.now(UTC),
            measurements=tuple(measurements),
        )
        self._slo_snapshot = snapshot
        return snapshot

    def serialize_source_receipt(self) -> bytes:
        """Serialize complete raw observations without prompt or credentials."""

        if (
            self._preflight is None
            or set(self._worker_heartbeat_age_by_level) != required_concurrency_levels()
            or set(self._level_observations) != required_concurrency_levels()
            or set(self._metric_snapshots) != required_concurrency_levels()
            or self._slo_snapshot is None
        ):
            raise _observation_error("staging source receipt is incomplete")
        candidate = self.specification.candidate_identity
        payload: dict[str, object] = {
            "format": _SOURCE_FORMAT,
            "environment": self.specification.environment,
            "candidate": {
                "candidate_commit": candidate.candidate_commit,
                "candidate_release": candidate.candidate_release,
                "oci_revision": candidate.oci_revision,
                "runtime_manifest_digest": candidate.runtime_manifest_digest,
                "test_matrix_digest": candidate.test_matrix_digest,
            },
            "source_binding": {
                "manifest_sha256": self.specification.manifest_sha256,
                "approved_preflight_sha256": self.specification.approved_preflight_sha256,
                "staging_envelope_sha256": self.specification.approval.envelope_sha256,
                "authorization_id": self.specification.approval.authorization_id,
                "approved_by": self.specification.approval.approved_by,
                "approval_issued_at": _utc_text(self.specification.approval.issued_at),
                "approval_expires_at": _utc_text(self.specification.approval.expires_at),
            },
            "target": {
                "base_url": self.specification.base_url,
                "prometheus_url": self.specification.prometheus_url,
            },
            "workload": {
                "levels": sorted(required_concurrency_levels()),
                "repetitions": self.specification.repetitions,
                "task_id": self.specification.task_id,
                "total_request_budget": self.specification.total_request_budget,
                "request_template_sha256": hashlib.sha256(
                    _REQUEST_TEMPLATE.encode("utf-8")
                ).hexdigest(),
                "actor_aliases": [actor.alias for actor in self._actors],
            },
            "preflight": {
                "captured_at": _utc_text(self._preflight.captured_at),
                "health_status_code": self._preflight.health_status_code,
                "queue_status_code": self._preflight.queue_status_code,
                "worker_ready": self._preflight.worker_ready,
                "worker_heartbeat_age_seconds": self._worker_heartbeat_age_by_level[
                    max(required_concurrency_levels())
                ],
                "worker_heartbeat_age_seconds_by_level": {
                    str(level): self._worker_heartbeat_age_by_level[level]
                    for level in sorted(self._worker_heartbeat_age_by_level)
                },
                "worker_heartbeat_max_age_seconds": (
                    self.specification.runtime.worker_heartbeat_max_age_seconds
                ),
                "prometheus_query": "vector(1)",
            },
            "levels": [
                {
                    "concurrency": level,
                    "requests": [
                        {
                            "actor_alias": item.actor_alias,
                            "captured_at": _utc_text(item.captured_at),
                            "elapsed_ms": item.elapsed_ms,
                            "reason_code": item.reason_code,
                            "run_id": item.run_id,
                            "status_code": item.status_code,
                        }
                        for item in self._level_observations[level]
                    ],
                    "metrics": [
                        {
                            "key": metric.key,
                            "reason": metric.reason,
                            "status": metric.status.value,
                            "value": metric.value,
                        }
                        for metric in self._metric_snapshots[level].metrics
                    ],
                }
                for level in sorted(self._level_observations)
            ],
            "slo_measurements": [
                {
                    "key": item.key,
                    "reason": item.reason,
                    "status": item.status.value,
                    "value": item.value,
                }
                for item in self._slo_snapshot.measurements
            ],
            "runtime_enablement": "not_authorized",
            "production_claim": False,
            "secrets_recorded": False,
        }
        return json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")


def _bounded_json_response(response: requests.Response, field_name: str) -> Mapping[str, object]:
    """Parse a bounded JSON object without returning response text in errors."""

    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise _observation_error(f"{field_name} response exceeds the size limit")
    try:
        decoded = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise _observation_error(f"{field_name} response is not JSON") from exc
    if not isinstance(decoded, Mapping) or any(type(key) is not str for key in decoded):
        raise _observation_error(f"{field_name} response is not a JSON object")
    return cast(Mapping[str, object], decoded)


class RequestsTerminalRuntimeStagingHttpClient:
    """HTTPS adapter for the queued Terminal staging API."""

    def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
        """Create a strict no-redirect HTTP client for one validated origin."""

        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _headers(actor: TerminalRuntimeStagingActor) -> dict[str, str]:
        """Build a request-scoped API token header without retaining it."""

        return {
            "Accept": "application/json",
            "Authorization": f"Token {actor.api_token}",
            "Content-Type": "application/json",
        }

    def preflight(
        self, actor: TerminalRuntimeStagingActor
    ) -> TerminalRuntimeStagingPreflightObservation:
        """Read public health and authenticated queue readiness."""

        try:
            health = requests.get(
                f"{self._base_url}{_HEALTH_PATH}",
                timeout=self._timeout_seconds,
                allow_redirects=False,
            )
            queue = requests.get(
                f"{self._base_url}{_QUEUE_PATH}",
                headers=self._headers(actor),
                timeout=self._timeout_seconds,
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise _observation_error("staging preflight timed out") from exc
        except requests.RequestException as exc:
            raise _observation_error("staging preflight request failed") from exc
        worker_ready = False
        if queue.status_code == 200:
            queue_payload = _bounded_json_response(queue, "queue preflight")
            raw_worker_ready = queue_payload.get("worker_ready")
            if type(raw_worker_ready) is not bool:
                raise _observation_error("queue preflight worker readiness is absent")
            worker_ready = raw_worker_ready
        return TerminalRuntimeStagingPreflightObservation(
            captured_at=datetime.now(UTC),
            health_status_code=health.status_code,
            queue_status_code=queue.status_code,
            worker_ready=worker_ready,
        )

    def submit(
        self,
        *,
        actor: TerminalRuntimeStagingActor,
        task_id: int,
        message: str,
        run_id: str,
        client_request_id: str,
    ) -> TerminalRuntimeStagingRequestObservation:
        """Submit one exact queued request and retain only safe response fields."""

        started = time.perf_counter()
        try:
            response = requests.post(
                f"{self._base_url}{_RUN_PATH}",
                headers=self._headers(actor),
                json={
                    "task_id": task_id,
                    "message": message,
                    "run_id": run_id,
                    "client_request_id": client_request_id,
                },
                timeout=self._timeout_seconds,
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise _observation_error("queued submission timed out") from exc
        except requests.RequestException as exc:
            raise _observation_error("queued submission request failed") from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if response.status_code not in {202, 429}:
            raise _observation_error("queued submission returned an uncontracted status")
        payload = _bounded_json_response(response, "queued submission")
        observed_run_id: str | None = None
        reason_code: str | None = None
        if response.status_code == 202:
            raw_run_id = payload.get("run_id")
            if type(raw_run_id) is not str:
                raise _observation_error("accepted response omitted run identity")
            observed_run_id = raw_run_id
        elif response.status_code == 429:
            raw_reason_code = payload.get("reason_code")
            if type(raw_reason_code) is not str:
                raise _observation_error("bounded rejection omitted reason code")
            reason_code = raw_reason_code
        return TerminalRuntimeStagingRequestObservation(
            actor_alias=actor.alias,
            run_id=observed_run_id,
            status_code=response.status_code,
            reason_code=reason_code,
            elapsed_ms=elapsed_ms,
            captured_at=datetime.now(UTC),
        )


class RequestsTerminalRuntimePrometheusClient:
    """Authenticated no-redirect Prometheus instant-query adapter."""

    def __init__(
        self,
        *,
        prometheus_url: str,
        credentials: TerminalRuntimePrometheusCredentials,
        timeout_seconds: float,
    ) -> None:
        """Bind one validated query origin and interactive credential pair."""

        self._query_url = f"{prometheus_url.rstrip('/')}{_PROMETHEUS_QUERY_PATH}"
        self._credentials = credentials
        self._timeout_seconds = timeout_seconds

    def query(self, expression: str) -> float | None:
        """Return one finite non-negative vector value or explicit no-sample."""

        try:
            response = requests.get(
                self._query_url,
                params={"query": expression},
                auth=(self._credentials.username, self._credentials.password),
                timeout=self._timeout_seconds,
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise _observation_error("Prometheus query timed out") from exc
        except requests.RequestException as exc:
            raise _observation_error("Prometheus query request failed") from exc
        if response.status_code != 200:
            raise _observation_error("Prometheus query returned a non-success status")
        payload = _bounded_json_response(response, "Prometheus query")
        if payload.get("status") != "success":
            raise _observation_error("Prometheus query did not report success")
        data = _observation_mapping(payload.get("data"), "Prometheus data")
        result_type = data.get("resultType")
        result = data.get("result")
        raw_value: object
        if result_type == "vector":
            if not isinstance(result, list):
                raise _observation_error("Prometheus vector result is invalid")
            if not result:
                return None
            if len(result) != 1:
                raise _observation_error("Prometheus query returned ambiguous series")
            series = _observation_mapping(result[0], "Prometheus series")
            raw_value = series.get("value")
        elif result_type == "scalar":
            raw_value = result
        else:
            raise _observation_error("Prometheus result type is unsupported")
        if not isinstance(raw_value, list) or len(raw_value) != 2:
            raise _observation_error("Prometheus sample is invalid")
        parsed = safe_float(raw_value[1], default=None)
        if parsed is None or parsed < 0:
            raise _observation_error("Prometheus sample value is invalid")
        return parsed


__all__ = [
    "RequestsTerminalRuntimePrometheusClient",
    "RequestsTerminalRuntimeStagingHttpClient",
    "TerminalRuntimePrometheusCredentials",
    "TerminalRuntimePrometheusPort",
    "TerminalRuntimeStagingActor",
    "TerminalRuntimeStagingApproval",
    "TerminalRuntimeStagingConfigurationError",
    "TerminalRuntimeStagingClock",
    "TerminalRuntimeStagingHarness",
    "TerminalRuntimeStagingHttpPort",
    "TerminalRuntimeStagingObservationError",
    "TerminalRuntimeStagingPreflightObservation",
    "TerminalRuntimeStagingQuery",
    "TerminalRuntimeStagingRequestObservation",
    "TerminalRuntimeStagingRuntimeEnvelope",
    "TerminalRuntimeStagingSpecification",
    "parse_terminal_runtime_staging_manifest",
]
