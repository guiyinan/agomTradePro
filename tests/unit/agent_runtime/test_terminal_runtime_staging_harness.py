"""Focused tests for the concrete, non-production TAR-06 staging harness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineMetricStatus,
    TerminalRuntimeBaselineReport,
    required_baseline_metric_keys,
)
from apps.agent_runtime.application.terminal_runtime_baseline_collector import (
    TerminalRuntimeBaselineCollectionRequest,
    TerminalRuntimeBaselineCollector,
    TerminalRuntimeBaselineObservationRequest,
)
from apps.agent_runtime.application.terminal_runtime_slo import (
    TerminalRuntimeSloStatus,
    terminal_runtime_slo_criteria,
)
from apps.agent_runtime.infrastructure.terminal_runtime_baseline_snapshot_observer import (
    JsonSnapshotSource,
    TerminalRuntimeBaselineSnapshotObserver,
)
from apps.agent_runtime.infrastructure.terminal_runtime_controlled_observer import (
    TerminalRuntimeBaselineCommandReceipt,
    TerminalRuntimeBaselineControlledObserver,
)
from apps.agent_runtime.infrastructure.terminal_runtime_staging_harness import (
    TerminalRuntimeStagingActor,
    TerminalRuntimeStagingConfigurationError,
    TerminalRuntimeStagingHarness,
    TerminalRuntimeStagingObservationError,
    TerminalRuntimeStagingPreflightObservation,
    TerminalRuntimeStagingRequestObservation,
    parse_terminal_runtime_staging_manifest,
)
from scripts import run_terminal_runtime_staging_baseline as staging_runner

CAPTURED_AT = datetime(2026, 8, 31, 1, 2, 3, tzinfo=UTC)
APPROVAL_ISSUED_AT = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
APPROVAL_EXPIRES_AT = APPROVAL_ISSUED_AT + timedelta(days=1)


def _captured_clock() -> datetime:
    """Return the deterministic approval-check clock used by the harness."""

    return CAPTURED_AT


def _canonical_json(payload: object) -> bytes:
    """Serialize one deterministic test artifact."""

    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _manifest_payload(
    *,
    base_url: str = "https://staging.example.test",
    production_hosts: list[str] | None = None,
    approved_preflight_sha256: str = "0" * 64,
    runtime_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return one unapproved staging manifest payload."""

    baseline_query_keys = sorted(
        required_baseline_metric_keys() - {"web_p50_ms", "web_p95_ms", "web_p99_ms"}
    )
    slo_query_keys = [
        criterion.key
        for criterion in terminal_runtime_slo_criteria()
        if criterion.key != "run_api_p95_ms"
    ]
    runtime: dict[str, object] = {
        "dedicated_worker_service": "terminal_agent_worker",
        "dedicated_worker_queue": "terminal_agent",
        "worker_concurrency": 4,
        "worker_prefetch_multiplier": 1,
        "worker_memory_limit_bytes": 2 * 1024 * 1024 * 1024,
        "worker_cpu_limit": 2.0,
        "worker_heartbeat_max_age_seconds": 30,
        "legacy_inline_concurrency": 1,
        "staging_runtime_authorized": True,
        "queued_intake_enabled": True,
        "queued_worker_enabled": True,
        "provider_execution_mode": "non_billable_stub",
        "mcp_execution_mode": "disabled",
    }
    runtime.update(runtime_overrides or {})
    return {
        "format": "terminal-runtime-staging-harness.v1",
        "environment": "staging-tar05",
        "candidate": {
            "candidate_commit": "a" * 40,
            "candidate_release": "20260831010000",
            "oci_revision": "sha256:" + "b" * 64,
            "runtime_manifest_digest": "c" * 64,
            "test_matrix_digest": "6272ea6606ebbf3c0791e48d807b733cbc6d9a4ce7d945d95c5e3a16c22aea64",
        },
        "target": {
            "base_url": base_url,
            "prometheus_url": "https://metrics.staging.example.test/internal/prometheus",
            "production_hosts": production_hosts or ["demo.agomtrade.pro"],
        },
        "runtime": runtime,
        "workload": {
            "task_id": 41,
            "repetitions": 1,
            "request_timeout_seconds": 10,
        },
        "approved_preflight_sha256": approved_preflight_sha256,
        "baseline_metric_queries": {key: f"baseline:{key}" for key in baseline_query_keys},
        "slo_queries": {key: f"slo:{key}" for key in slo_query_keys},
    }


def _envelope_sha256(payload: dict[str, object]) -> str:
    """Hash every executable field while excluding only the approval digest."""

    envelope = dict(payload)
    envelope.pop("approved_preflight_sha256")
    return hashlib.sha256(_canonical_json(envelope)).hexdigest()


def _preflight_payload(
    manifest_payload: dict[str, object],
    *,
    decision: str = "approved",
    expires_at: datetime = APPROVAL_EXPIRES_AT,
    action_overrides: dict[str, object] | None = None,
    envelope_sha256: str | None = None,
) -> dict[str, object]:
    """Return one exact, time-bounded staging approval payload."""

    actions: dict[str, object] = {
        "staging_network_load": True,
        "production_load": False,
        "fault_injection": False,
        "paid_provider_or_mcp_calls": False,
        "runtime_flag_changes": False,
    }
    actions.update(action_overrides or {})
    return {
        "format": "terminal-runtime-staging-preflight.v1",
        "decision": decision,
        "authorization_id": "TAR06-STAGING-APPROVAL-20260831-01",
        "approved_by": "agomtradepro-personal-project-owner",
        "issued_at": APPROVAL_ISSUED_AT.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "envelope_sha256": envelope_sha256 or _envelope_sha256(manifest_payload),
        "allowed_actions": actions,
    }


def _bundle(
    *,
    base_url: str = "https://staging.example.test",
    production_hosts: list[str] | None = None,
    runtime_overrides: dict[str, object] | None = None,
    decision: str = "approved",
    expires_at: datetime = APPROVAL_EXPIRES_AT,
    action_overrides: dict[str, object] | None = None,
    envelope_sha256: str | None = None,
    raw_preflight: bytes | None = None,
) -> tuple[bytes, bytes]:
    """Build one mutually bound manifest and approval artifact pair."""

    manifest_payload = _manifest_payload(
        base_url=base_url,
        production_hosts=production_hosts,
        runtime_overrides=runtime_overrides,
    )
    preflight = raw_preflight or _canonical_json(
        _preflight_payload(
            manifest_payload,
            decision=decision,
            expires_at=expires_at,
            action_overrides=action_overrides,
            envelope_sha256=envelope_sha256,
        )
    )
    manifest_payload["approved_preflight_sha256"] = hashlib.sha256(preflight).hexdigest()
    return _canonical_json(manifest_payload), preflight


def _manifest(
    *,
    base_url: str = "https://staging.example.test",
    production_hosts: list[str] | None = None,
) -> bytes:
    """Return one exact candidate-bound staging execution manifest."""

    return _bundle(base_url=base_url, production_hosts=production_hosts)[0]


def _approved_preflight() -> bytes:
    """Return the approval artifact bound to the default manifest."""

    return _bundle()[1]


def _actors() -> tuple[TerminalRuntimeStagingActor, ...]:
    """Return the exact twenty distinct staging actors required by level 20."""

    return tuple(
        TerminalRuntimeStagingActor(alias=f"actor-{index:02d}", api_token=f"token-{index:02d}")
        for index in range(1, 21)
    )


@dataclass
class _HttpPort:
    """Deterministic HTTP double that retains no prompt or credential."""

    preflight_status: int = 200
    submit_status: int = 202
    preflight_aliases: list[str] = field(default_factory=list)
    submitted_aliases: list[str] = field(default_factory=list)

    def preflight(
        self,
        actor: TerminalRuntimeStagingActor,
    ) -> TerminalRuntimeStagingPreflightObservation:
        """Return a bounded health and queue preflight result."""

        self.preflight_aliases.append(actor.alias)
        return TerminalRuntimeStagingPreflightObservation(
            captured_at=CAPTURED_AT,
            health_status_code=self.preflight_status,
            queue_status_code=self.preflight_status,
            worker_ready=self.preflight_status == 200,
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
        """Return one accepted response with a stable 100 ms latency."""

        assert task_id == 41
        assert message == "Return STAGING_OK without tools."
        assert client_request_id
        self.submitted_aliases.append(actor.alias)
        return TerminalRuntimeStagingRequestObservation(
            actor_alias=actor.alias,
            run_id=run_id if self.submit_status == 202 else None,
            status_code=self.submit_status,
            reason_code=(None if self.submit_status == 202 else "global_queued_limit"),
            elapsed_ms=100.0,
            captured_at=CAPTURED_AT,
        )


@dataclass
class _PrometheusPort:
    """Return query values derived from the canonical contract."""

    unavailable_expression: str | None = None
    expressions: list[str] = field(default_factory=list)
    heartbeat_values: list[float | None] = field(default_factory=list)

    def query(self, expression: str) -> float | None:
        """Return a deterministic value or an explicit missing sample."""

        self.expressions.append(expression)
        if expression == "vector(1)":
            return 1.0
        if expression == self.unavailable_expression:
            return None
        if expression == "baseline:worker_heartbeat_age_seconds" and self.heartbeat_values:
            return self.heartbeat_values.pop(0)
        if expression.startswith("baseline:"):
            return 1.0
        key = expression.removeprefix("slo:")
        criterion = next(item for item in terminal_runtime_slo_criteria() if item.key == key)
        return float(criterion.threshold)


def _harness(
    *,
    http_port: _HttpPort | None = None,
    prometheus_port: _PrometheusPort | None = None,
) -> TerminalRuntimeStagingHarness:
    """Build one validated harness from injected external adapters."""

    specification = parse_terminal_runtime_staging_manifest(
        _manifest(),
        approved_preflight=_approved_preflight(),
        observed_at=CAPTURED_AT,
    )
    return TerminalRuntimeStagingHarness(
        specification=specification,
        actors=_actors(),
        http_port=http_port or _HttpPort(),
        prometheus_port=prometheus_port or _PrometheusPort(),
        clock=_captured_clock,
    )


def _report(harness: TerminalRuntimeStagingHarness) -> TerminalRuntimeBaselineReport:
    """Collect all levels without converting unavailable observations to success."""

    observer = TerminalRuntimeBaselineControlledObserver(harness, harness, harness)
    request = TerminalRuntimeBaselineCollectionRequest(
        environment=harness.specification.environment,
        candidate_identity=harness.specification.candidate_identity,
    )
    samples = tuple(
        observer.observe(
            TerminalRuntimeBaselineObservationRequest(
                environment=request.environment,
                candidate_identity=request.candidate_identity,
                concurrency=level,
            )
        )
        for level in (1, 5, 10, 20)
    )
    return TerminalRuntimeBaselineReport(
        samples=samples,
        slo_report=observer.observe_slo(request),
    )


def _level_request(
    harness: TerminalRuntimeStagingHarness,
    *,
    concurrency: int = 1,
) -> TerminalRuntimeBaselineObservationRequest:
    """Build one request bound to the harness candidate and environment."""

    return TerminalRuntimeBaselineObservationRequest(
        environment=harness.specification.environment,
        candidate_identity=harness.specification.candidate_identity,
        concurrency=concurrency,
    )


def test_manifest_rejects_a_production_target_before_network_io() -> None:
    """A caller cannot relabel the known production target as staging."""

    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="production"):
        parse_terminal_runtime_staging_manifest(
            _manifest(
                base_url="https://demo.agomtrade.pro",
                production_hosts=["unrelated-production.example.test"],
            ),
            approved_preflight=_approved_preflight(),
            observed_at=CAPTURED_AT,
        )


def test_manifest_requires_the_exact_approved_preflight_bytes() -> None:
    """A stale or substituted approval input fails before a harness is built."""

    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="preflight"):
        parse_terminal_runtime_staging_manifest(
            _manifest(),
            approved_preflight=b"other-preflight",
            observed_at=CAPTURED_AT,
        )


def test_manifest_rejects_non_json_bytes_that_only_match_the_declared_digest() -> None:
    """A digest match does not turn arbitrary bytes into an approval."""

    manifest, preflight = _bundle(raw_preflight=b"approved-preflight")

    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="JSON"):
        parse_terminal_runtime_staging_manifest(
            manifest,
            approved_preflight=preflight,
            observed_at=CAPTURED_AT,
        )


@pytest.mark.parametrize("decision", ["defer", "denied", "template"])
def test_manifest_requires_an_explicit_approved_decision(decision: str) -> None:
    """A DEFER, denial, or template cannot authorize staging traffic."""

    manifest, preflight = _bundle(decision=decision)

    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="approved"):
        parse_terminal_runtime_staging_manifest(
            manifest,
            approved_preflight=preflight,
            observed_at=CAPTURED_AT,
        )


def test_manifest_rejects_an_expired_or_overlong_approval_window() -> None:
    """Staging network authority is current and lasts no more than one day."""

    expired_manifest, expired_preflight = _bundle(expires_at=CAPTURED_AT - timedelta(seconds=1))
    long_manifest, long_preflight = _bundle(
        expires_at=APPROVAL_ISSUED_AT + timedelta(days=1, seconds=1)
    )

    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="expired"):
        parse_terminal_runtime_staging_manifest(
            expired_manifest,
            approved_preflight=expired_preflight,
            observed_at=CAPTURED_AT,
        )
    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="validity"):
        parse_terminal_runtime_staging_manifest(
            long_manifest,
            approved_preflight=long_preflight,
            observed_at=CAPTURED_AT,
        )


def test_manifest_rejects_an_approval_bound_to_a_different_envelope() -> None:
    """Approval binds every candidate, target, runtime, workload, and query field."""

    manifest, preflight = _bundle(envelope_sha256="f" * 64)

    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="envelope"):
        parse_terminal_runtime_staging_manifest(
            manifest,
            approved_preflight=preflight,
            observed_at=CAPTURED_AT,
        )


@pytest.mark.parametrize(
    ("key", "unsafe_value"),
    [
        ("staging_network_load", False),
        ("production_load", True),
        ("fault_injection", True),
        ("paid_provider_or_mcp_calls", True),
        ("runtime_flag_changes", True),
    ],
)
def test_manifest_rejects_unsafe_or_missing_approval_actions(
    key: str,
    unsafe_value: bool,
) -> None:
    """TAR-06 authority is staging-load-only and cannot expand action scope."""

    manifest, preflight = _bundle(action_overrides={key: unsafe_value})

    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="action"):
        parse_terminal_runtime_staging_manifest(
            manifest,
            approved_preflight=preflight,
            observed_at=CAPTURED_AT,
        )


@pytest.mark.parametrize(
    ("runtime_overrides", "message"),
    [
        ({"legacy_inline_concurrency": 2}, "inline"),
        ({"provider_execution_mode": "paid_openai"}, "provider"),
        ({"mcp_execution_mode": "enabled"}, "MCP"),
        ({"queued_worker_enabled": False}, "worker"),
        ({"worker_prefetch_multiplier": 4}, "prefetch"),
    ],
)
def test_manifest_rejects_an_unsafe_staging_runtime_profile(
    runtime_overrides: dict[str, object],
    message: str,
) -> None:
    """The load collector only targets an isolated, non-billable worker profile."""

    manifest, preflight = _bundle(runtime_overrides=runtime_overrides)

    with pytest.raises(TerminalRuntimeStagingConfigurationError, match=message):
        parse_terminal_runtime_staging_manifest(
            manifest,
            approved_preflight=preflight,
            observed_at=CAPTURED_AT,
        )


def test_harness_runs_the_exact_multi_actor_staircase_and_builds_ready_evidence() -> None:
    """The concrete harness drives 1/5/10/20 and computes bound evidence."""

    http_port = _HttpPort()
    prometheus_port = _PrometheusPort()
    harness = _harness(http_port=http_port, prometheus_port=prometheus_port)

    report = _report(harness)

    assert report.ready_for_capacity_gate is True
    assert len(http_port.submitted_aliases) == 36
    assert len(set(http_port.submitted_aliases[-20:])) == 20
    assert [sample.sample_count for sample in report.samples] == [1, 5, 10, 20]
    assert prometheus_port.expressions.count("baseline:worker_heartbeat_age_seconds") == 8
    source = harness.serialize_source_receipt()
    assert b"token-" not in source
    assert b"Return STAGING_OK" not in source
    assert b'"runtime_enablement":"not_authorized"' in source


def test_harness_preserves_a_missing_prometheus_sample_as_unavailable() -> None:
    """A missing metric remains unavailable and keeps the capacity gate closed."""

    harness = _harness(
        prometheus_port=_PrometheusPort(unavailable_expression="baseline:model_latency_ms")
    )

    report = _report(harness)

    metric = next(item for item in report.samples[0].metrics if item.key == "model_latency_ms")
    assert metric.status is TerminalRuntimeBaselineMetricStatus.UNAVAILABLE
    assert metric.value is None
    assert metric.reason == "prometheus_no_sample"
    assert report.ready_for_capacity_gate is False


def test_harness_aborts_before_load_when_staging_preflight_fails() -> None:
    """No queued request is sent when health or queue readiness is absent."""

    http_port = _HttpPort(preflight_status=503)
    harness = _harness(http_port=http_port)

    with pytest.raises(TerminalRuntimeStagingObservationError, match="preflight"):
        _report(harness)

    assert http_port.submitted_aliases == []


def test_harness_aborts_before_load_when_worker_heartbeat_is_unavailable() -> None:
    """A queue flag cannot impersonate a live dedicated worker heartbeat."""

    http_port = _HttpPort()
    harness = _harness(
        http_port=http_port,
        prometheus_port=_PrometheusPort(
            unavailable_expression="baseline:worker_heartbeat_age_seconds"
        ),
    )

    with pytest.raises(TerminalRuntimeStagingObservationError, match="heartbeat"):
        _report(harness)

    assert http_port.submitted_aliases == []


def test_harness_rechecks_worker_heartbeat_before_every_staircase_level() -> None:
    """A Worker that disappears after level one blocks level five before traffic."""

    http_port = _HttpPort()
    harness = _harness(
        http_port=http_port,
        prometheus_port=_PrometheusPort(heartbeat_values=[1.0, 1.0, None]),
    )

    with pytest.raises(TerminalRuntimeStagingObservationError, match="heartbeat"):
        _report(harness)

    assert http_port.submitted_aliases == ["actor-01"]


def test_harness_run_cannot_bypass_execute_with_a_forged_command_receipt() -> None:
    """The load port consumes an internal one-level authorization, not receipt fields alone."""

    http_port = _HttpPort()
    harness = _harness(http_port=http_port)
    request = _level_request(harness)
    forged_command = TerminalRuntimeBaselineCommandReceipt(
        environment=request.environment,
        candidate_identity=request.candidate_identity,
        concurrency=request.concurrency,
    )

    with pytest.raises(TerminalRuntimeStagingObservationError, match="authorized"):
        harness.run(request, forged_command)

    assert http_port.submitted_aliases == []


def test_harness_rechecks_expired_approval_before_initial_network_preflight() -> None:
    """Credential-reading delay cannot carry an expired parse result into I/O."""

    http_port = _HttpPort()
    harness = _harness(http_port=http_port)
    harness.specification = replace(
        harness.specification,
        approval=replace(
            harness.specification.approval,
            expires_at=CAPTURED_AT - timedelta(seconds=1),
        ),
    )

    with pytest.raises(TerminalRuntimeStagingObservationError, match="approval"):
        harness.execute(_level_request(harness))

    assert http_port.preflight_aliases == []


def test_harness_rechecks_approval_after_credentials_or_preflight_delay() -> None:
    """An approval expiring after parse cannot authorize the next network step."""

    http_port = _HttpPort()
    harness = _harness(http_port=http_port)
    request = _level_request(harness)
    command = harness.execute(request)
    harness.specification = replace(
        harness.specification,
        approval=replace(
            harness.specification.approval,
            expires_at=CAPTURED_AT - timedelta(seconds=1),
        ),
    )

    with pytest.raises(TerminalRuntimeStagingObservationError, match="approval"):
        harness.run(request, command)

    assert http_port.submitted_aliases == []


def test_harness_rejects_uncontracted_http_statuses() -> None:
    """A partial failed level is neither accepted nor authorized for a retry."""

    harness = _harness(http_port=_HttpPort(submit_status=500))

    with pytest.raises(TerminalRuntimeStagingObservationError, match="status"):
        _report(harness)
    with pytest.raises(TerminalRuntimeStagingObservationError, match="attempted"):
        harness.execute(_level_request(harness))


def test_harness_requires_twenty_distinct_credentials() -> None:
    """Level 20 cannot be mislabeled when fewer unique actors are available."""

    specification = parse_terminal_runtime_staging_manifest(
        _manifest(),
        approved_preflight=_approved_preflight(),
        observed_at=CAPTURED_AT,
    )
    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="twenty"):
        TerminalRuntimeStagingHarness(
            specification=specification,
            actors=_actors()[:19],
            http_port=_HttpPort(),
            prometheus_port=_PrometheusPort(),
        )


def test_slo_count_queries_remain_integers_after_prometheus_parsing() -> None:
    """Prometheus floats do not weaken exact integer SLO contracts."""

    report = _report(_harness())

    count_measurements = (
        [
            measurement
            for measurement in report.slo_report.measurements
            if measurement.key != "ordinary_web_p95_degradation_percent"
            and measurement.key != "run_api_p95_ms"
        ]
        if report.slo_report is not None
        else []
    )
    assert count_measurements
    assert all(
        measurement.status is TerminalRuntimeSloStatus.OBSERVED
        for measurement in count_measurements
    )
    assert all(type(measurement.value) is int for measurement in count_measurements)


def test_runner_credentials_are_bounded_and_secret_free_in_repr() -> None:
    """The stdin-only credential envelope accepts exactly twenty identities."""

    credential_bytes = json.dumps(
        {
            "actors": [
                {"alias": f"actor-{index:02d}", "api_token": f"secret-{index:02d}"}
                for index in range(1, 21)
            ],
            "prometheus": {"username": "metrics-user", "password": "metrics-secret"},
        }
    ).encode("utf-8")

    credentials = staging_runner.parse_staging_credentials(credential_bytes)

    assert len(credentials.actors) == 20
    assert "secret-01" not in repr(credentials)
    assert "metrics-secret" not in repr(credentials)


def test_runner_snapshot_round_trips_through_the_offline_observer() -> None:
    """Live observations serialize into the existing canonical snapshot contract."""

    report = _report(_harness())
    snapshot = staging_runner.serialize_staging_snapshot(report)

    observer = TerminalRuntimeBaselineSnapshotObserver(JsonSnapshotSource(snapshot))
    round_trip = TerminalRuntimeBaselineCollector(observer).collect(
        TerminalRuntimeBaselineCollectionRequest(
            environment=observer.environment,
            candidate_identity=observer.candidate,
        )
    )

    assert round_trip.ready_for_capacity_gate is True
    assert b"secret-" not in snapshot
    assert b"Return STAGING_OK" not in snapshot


def test_runner_content_addressed_writer_is_append_only(tmp_path: Path) -> None:
    """Identical bytes are idempotent and changed existing bytes fail closed."""

    artifact, digest, created = staging_runner._write_content_addressed(
        output_root=tmp_path,
        category="terminal-agent-staging-source",
        payload=b'{"safe":true}',
    )
    repeated, repeated_digest, repeated_created = staging_runner._write_content_addressed(
        output_root=tmp_path,
        category="terminal-agent-staging-source",
        payload=b'{"safe":true}',
    )

    assert created is True
    assert repeated_created is False
    assert repeated == artifact
    assert repeated_digest == digest
    assert artifact.with_suffix(".sha256").read_text(encoding="ascii") == f"{digest}\n"

    artifact.write_bytes(b'{"tampered":true}')
    with pytest.raises(TerminalRuntimeStagingConfigurationError, match="collision"):
        staging_runner._write_content_addressed(
            output_root=tmp_path,
            category="terminal-agent-staging-source",
            payload=b'{"safe":true}',
        )


def test_runner_default_mode_validates_without_network_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI defaults to a no-network validation summary."""

    manifest_path = tmp_path / "manifest.json"
    preflight_path = tmp_path / "approved-preflight.json"
    manifest_path.write_bytes(_manifest())
    preflight_path.write_bytes(_approved_preflight())

    def _network_forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("validation-only mode attempted network I/O")

    monkeypatch.setattr(
        staging_runner,
        "RequestsTerminalRuntimeStagingHttpClient",
        _network_forbidden,
    )
    monkeypatch.setattr(
        staging_runner,
        "RequestsTerminalRuntimePrometheusClient",
        _network_forbidden,
    )
    monkeypatch.setattr(
        staging_runner.sys,
        "argv",
        [
            "run_terminal_runtime_staging_baseline.py",
            "--manifest",
            str(manifest_path),
            "--approved-preflight",
            str(preflight_path),
        ],
    )

    assert staging_runner.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "validation_only"
    assert output["network_io"] is False
    assert output["total_request_budget"] == 36
    assert output["runtime_enablement"] == "not_authorized"


def test_runner_execution_binds_canonical_evidence_to_the_raw_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The persisted canonical artifact hashes the secret-free live receipt."""

    specification = parse_terminal_runtime_staging_manifest(
        _manifest(),
        approved_preflight=_approved_preflight(),
        observed_at=CAPTURED_AT,
    )
    credentials = staging_runner.TerminalRuntimeStagingCredentialBundle(
        actors=_actors(),
        prometheus=staging_runner.TerminalRuntimePrometheusCredentials(
            username="metrics-user",
            password="metrics-secret",
        ),
    )
    http_port = _HttpPort()
    prometheus_port = _PrometheusPort()
    monkeypatch.setattr(
        staging_runner,
        "RequestsTerminalRuntimeStagingHttpClient",
        lambda **kwargs: http_port,
    )
    monkeypatch.setattr(
        staging_runner,
        "RequestsTerminalRuntimePrometheusClient",
        lambda **kwargs: prometheus_port,
    )

    output, ready = staging_runner._execute(
        specification=specification,
        credentials=credentials,
        output_root=tmp_path,
    )

    source_path = Path(output["source_receipt"]["path"])
    evidence_path = Path(output["canonical_evidence"]["path"])
    evidence = json.loads(evidence_path.read_bytes())
    assert ready is True
    assert output["capacity_contract_result"] == "PASS"
    assert output["tar05_acceptance"] == "not_granted"
    assert output["production_claim"] is False
    assert evidence["evidence_scope"] == "controlled_staging_observation"
    assert (
        evidence["source"]["payload_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    )
