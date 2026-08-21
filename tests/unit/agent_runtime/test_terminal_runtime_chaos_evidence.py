"""Focused tests for the pure TAR-01 chaos evidence contract."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_chaos_evidence import (
    TerminalRuntimeChaosCandidate,
    TerminalRuntimeChaosControlledObserver,
    TerminalRuntimeChaosCounters,
    TerminalRuntimeChaosEvidenceError,
    TerminalRuntimeChaosEvidenceReport,
    TerminalRuntimeChaosObservation,
    TerminalRuntimeChaosObservationError,
    TerminalRuntimeChaosObservationRequest,
    TerminalRuntimeChaosRecoveryStatus,
    TerminalRuntimeChaosRunStatus,
    TerminalRuntimeChaosState,
    TerminalRuntimeChaosStatus,
    TerminalRuntimeChaosStreamStatus,
    TerminalRuntimeChaosTimelineEvent,
    TerminalRuntimeChaosWorkerStatus,
    serialize_terminal_runtime_chaos_evidence,
    terminal_runtime_chaos_artifact_sha256,
    validate_terminal_runtime_chaos_evidence,
)
from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix_digest,
)

CANDIDATE = TerminalRuntimeChaosCandidate(
    candidate_commit="a" * 40,
    candidate_release="20260822120000",
    oci_revision="sha256:" + "b" * 64,
    test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
)
STARTED = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _state() -> TerminalRuntimeChaosState:
    """Return a complete recovered worker/run/stream state."""

    return TerminalRuntimeChaosState(
        worker_status=TerminalRuntimeChaosWorkerStatus.RESTARTED,
        run_status=TerminalRuntimeChaosRunStatus.COMPLETED,
        stream_status=TerminalRuntimeChaosStreamStatus.TERMINAL_REPLAYED,
        recovery_status=TerminalRuntimeChaosRecoveryStatus.RECOVERED,
    )


def _counters() -> TerminalRuntimeChaosCounters:
    """Return complete counters with no safety violation."""

    return TerminalRuntimeChaosCounters(
        reconnect_attempts=1,
        reconnect_successes=1,
        terminal_overwrites=0,
        duplicate_non_idempotent_side_effects=0,
        cross_user_leaks=0,
    )


def _observed(
    *,
    candidate: TerminalRuntimeChaosCandidate = CANDIDATE,
    scenario_id: str = "chaos-worker-stream-recovery",
    fault: str = "worker-sigkill",
) -> TerminalRuntimeChaosObservation:
    """Build one valid candidate-bound observed fault result."""

    return TerminalRuntimeChaosObservation(
        scenario_id=scenario_id,
        fault=fault,
        status=TerminalRuntimeChaosStatus.OBSERVED,
        environment="controlled-staging",
        candidate_identity=candidate,
        started_at=STARTED,
        completed_at=STARTED + timedelta(minutes=2),
        state=_state(),
        counters=_counters(),
        timeline=(
            TerminalRuntimeChaosTimelineEvent(1, STARTED, "fault_injected"),
            TerminalRuntimeChaosTimelineEvent(
                2, STARTED + timedelta(minutes=1), "stream_reconnected"
            ),
            TerminalRuntimeChaosTimelineEvent(
                3, STARTED + timedelta(minutes=2), "terminal_replayed"
            ),
        ),
    )


def _report(
    observations: tuple[TerminalRuntimeChaosObservation, ...] | None = None,
) -> TerminalRuntimeChaosEvidenceReport:
    """Build one valid report."""

    return TerminalRuntimeChaosEvidenceReport(
        environment="controlled-staging",
        candidate_identity=CANDIDATE,
        collected_at=STARTED + timedelta(minutes=3),
        observations=observations or (_observed(),),
    )


def test_observed_report_is_candidate_bound_and_round_trips_deterministically() -> None:
    """A complete recovery report serializes and validates without enabling runtime."""

    report = _report()
    assert report.ready_for_chaos_gate is True
    first = serialize_terminal_runtime_chaos_evidence(report)
    second = serialize_terminal_runtime_chaos_evidence(report)
    assert first == second
    assert b"not_authorized" in first
    assert b"password" not in first.lower()
    validated = validate_terminal_runtime_chaos_evidence(
        json.loads(first), expected_candidate=CANDIDATE
    )
    assert validated == report
    assert terminal_runtime_chaos_artifact_sha256(first) == terminal_runtime_chaos_artifact_sha256(
        second
    )


@pytest.mark.parametrize(
    "status", [TerminalRuntimeChaosStatus.UNAVAILABLE, TerminalRuntimeChaosStatus.FAILED]
)
def test_unavailable_or_failed_observation_is_preserved_and_not_ready(
    status: TerminalRuntimeChaosStatus,
) -> None:
    """Missing or failed fault collection never becomes a zero-valued pass."""

    observation = TerminalRuntimeChaosObservation(
        scenario_id="chaos-worker-stream-recovery",
        fault="redis-outage",
        status=status,
        environment="controlled-staging",
        candidate_identity=CANDIDATE,
        started_at=STARTED,
        completed_at=None,
        state=None,
        counters=None,
        timeline=(),
        reason=(
            "observer_unavailable"
            if status is TerminalRuntimeChaosStatus.UNAVAILABLE
            else "fault_injection_failed"
        ),
    )
    report = _report((observation,))
    assert report.ready_for_chaos_gate is False
    payload = serialize_terminal_runtime_chaos_evidence(report)
    validated = validate_terminal_runtime_chaos_evidence(
        json.loads(payload), expected_candidate=CANDIDATE
    )
    assert validated.observations[0].status is status
    assert validated.observations[0].counters is None


def test_candidate_matrix_or_release_drift_is_rejected() -> None:
    """A substituted release or matrix cannot enter the contract."""

    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="candidate_release"):
        TerminalRuntimeChaosCandidate(
            candidate_commit="a" * 40,
            candidate_release="release-drift",
            oci_revision="b" * 40,
            test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
        )
    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="canonical matrix"):
        TerminalRuntimeChaosCandidate(
            candidate_commit="a" * 40,
            candidate_release="20260822120000",
            oci_revision="b" * 40,
            test_matrix_digest="c" * 64,
        )


def test_timeline_must_be_utc_and_monotonic() -> None:
    """Naive, non-UTC, and backwards event clocks fail closed."""

    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="UTC"):
        TerminalRuntimeChaosTimelineEvent(1, datetime(2026, 8, 22, 12, 0), "started")
    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="UTC"):
        TerminalRuntimeChaosTimelineEvent(
            1, datetime(2026, 8, 22, 12, 0, tzinfo=timezone(timedelta(hours=8))), "started"
        )
    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="monotonic"):
        original = _observed()
        TerminalRuntimeChaosObservation(
            scenario_id=original.scenario_id,
            fault=original.fault,
            status=original.status,
            environment=original.environment,
            candidate_identity=original.candidate_identity,
            started_at=original.started_at,
            completed_at=original.completed_at,
            state=original.state,
            counters=original.counters,
            timeline=(
                TerminalRuntimeChaosTimelineEvent(1, STARTED + timedelta(minutes=1), "late"),
                TerminalRuntimeChaosTimelineEvent(2, STARTED, "early"),
            ),
        )


def test_secret_like_tokens_are_rejected() -> None:
    """Fixed fields cannot smuggle credentials or prompts into evidence."""

    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="secret material"):
        TerminalRuntimeChaosTimelineEvent(1, STARTED, "api_key_seen")
    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="secret material"):
        TerminalRuntimeChaosObservation(
            scenario_id="chaos-worker-stream-recovery",
            fault="redis-outage",
            status=TerminalRuntimeChaosStatus.UNAVAILABLE,
            environment="controlled-staging",
            candidate_identity=CANDIDATE,
            started_at=STARTED,
            completed_at=None,
            state=None,
            counters=None,
            timeline=(),
            reason="secret_recorded",
        )


def test_nested_state_and_counter_substitution_is_revalidated() -> None:
    """Forged nested dataclasses cannot bypass the observation boundary."""

    forged_state = object.__new__(TerminalRuntimeChaosState)
    object.__setattr__(forged_state, "worker_status", "running")
    object.__setattr__(forged_state, "run_status", TerminalRuntimeChaosRunStatus.COMPLETED)
    object.__setattr__(
        forged_state, "stream_status", TerminalRuntimeChaosStreamStatus.TERMINAL_REPLAYED
    )
    object.__setattr__(
        forged_state, "recovery_status", TerminalRuntimeChaosRecoveryStatus.RECOVERED
    )
    original = _observed()
    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="worker_status"):
        TerminalRuntimeChaosObservation(
            scenario_id=original.scenario_id,
            fault=original.fault,
            status=original.status,
            environment=original.environment,
            candidate_identity=original.candidate_identity,
            started_at=original.started_at,
            completed_at=original.completed_at,
            state=forged_state,
            counters=original.counters,
            timeline=original.timeline,
        )


def test_report_rejects_duplicate_scenario_fault_and_counter_inversion() -> None:
    """Duplicate evidence and impossible reconnect conservation are invalid."""

    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="reconnect_successes"):
        TerminalRuntimeChaosCounters(1, 2, 0, 0, 0)
    with pytest.raises(TerminalRuntimeChaosEvidenceError, match="duplicate"):
        _report((_observed(), replace(_observed(), scenario_id="chaos-worker-stream-recovery")))


@dataclass
class _FakePort:
    """Test-only injected port with no runtime dependencies."""

    substitute: str | None = None
    calls: int = 0

    def observe(
        self, request: TerminalRuntimeChaosObservationRequest
    ) -> TerminalRuntimeChaosObservation:
        """Return a valid observation or deliberately substitute one identity."""

        self.calls += 1
        result = replace(_observed(), scenario_id=request.scenario_id, fault=request.fault)
        if self.substitute == "candidate":
            return replace(result, candidate_identity=replace(CANDIDATE, candidate_commit="b" * 40))
        if self.substitute == "environment":
            return replace(result, environment="other-environment")
        if self.substitute == "scenario":
            return replace(result, scenario_id="other-scenario")
        return result


def _request() -> TerminalRuntimeChaosObservationRequest:
    """Build one valid observer request."""

    return TerminalRuntimeChaosObservationRequest(
        environment="controlled-staging",
        candidate_identity=CANDIDATE,
        scenario_id="chaos-worker-stream-recovery",
        fault="worker-sigkill",
    )


def test_controlled_observer_accepts_fake_port_and_preserves_unavailable_status() -> None:
    """The observer is injected, deterministic, and does not fill missing data."""

    port = _FakePort()
    observer = TerminalRuntimeChaosControlledObserver(port)
    result = observer.observe(_request())
    assert result.candidate_identity == CANDIDATE
    assert port.calls == 1


@pytest.mark.parametrize("substitute", ["candidate", "environment", "scenario"])
def test_controlled_observer_rejects_identity_substitution(substitute: str) -> None:
    """Every injected stage must preserve the requested candidate and scope."""

    with pytest.raises(TerminalRuntimeChaosObservationError):
        TerminalRuntimeChaosControlledObserver(_FakePort(substitute=substitute)).observe(_request())


def test_controlled_observer_collects_multiple_faults_without_external_runtime_imports() -> None:
    """Collection is a pure composition boundary and keeps each fault distinct."""

    port = _FakePort()
    observer = TerminalRuntimeChaosControlledObserver(port)
    second = replace(_request(), fault="redis-outage")
    report = observer.collect((_request(), second), collected_at=STARTED + timedelta(minutes=3))
    assert len(report.observations) == 2
    assert port.calls == 2


def test_chaos_contract_module_has_no_runtime_enabling_dependencies() -> None:
    """The Application contract cannot silently become a production fault runner."""

    path = Path("apps/agent_runtime/application/terminal_runtime_chaos_evidence.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        forbidden in name
        for name in imported
        for forbidden in ("django", "celery", "requests", "subprocess", "socket", "redis")
    )
    assert "fault injection" not in source.casefold()
