"""Focused tests for the injected TAR-01 controlled observer adapter."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineCandidate,
    TerminalRuntimeBaselineMetric,
    TerminalRuntimeBaselineMetricStatus,
    TerminalRuntimeBaselineSample,
    required_baseline_metric_keys,
)
from apps.agent_runtime.application.terminal_runtime_baseline_collector import (
    TerminalRuntimeBaselineCollectionRequest,
    TerminalRuntimeBaselineCollector,
    TerminalRuntimeBaselineObservationError,
    TerminalRuntimeBaselineObservationRequest,
)
from apps.agent_runtime.application.terminal_runtime_slo import (
    TerminalRuntimeSloMeasurement,
    TerminalRuntimeSloStatus,
    terminal_runtime_slo_criteria,
)
from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix_digest,
)
from apps.agent_runtime.infrastructure.terminal_runtime_controlled_observer import (
    TerminalRuntimeBaselineCommandReceipt,
    TerminalRuntimeBaselineControlledObserver,
    TerminalRuntimeBaselineLoadReceipt,
    TerminalRuntimeBaselineMetricSnapshot,
    TerminalRuntimeBaselineSloSnapshot,
    TerminalRuntimeControlledObservationError,
)

CANDIDATE = TerminalRuntimeBaselineCandidate(
    candidate_commit="a" * 40,
    candidate_release="20260820120000",
    oci_revision="b" * 40,
    runtime_manifest_digest="c" * 64,
    test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
)
CAPTURED_AT = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _request(concurrency: int = 1) -> TerminalRuntimeBaselineObservationRequest:
    """Build one valid observation request."""

    return TerminalRuntimeBaselineObservationRequest(
        environment="controlled-staging",
        candidate_identity=CANDIDATE,
        concurrency=concurrency,
    )


def _collection_request() -> TerminalRuntimeBaselineCollectionRequest:
    """Build one valid complete-collection request."""

    return TerminalRuntimeBaselineCollectionRequest(
        environment="controlled-staging",
        candidate_identity=CANDIDATE,
    )


def _metrics(unavailable: str | None = None) -> tuple[TerminalRuntimeBaselineMetric, ...]:
    """Return every required metric with explicit observed/unavailable state."""

    return tuple(
        TerminalRuntimeBaselineMetric(
            key=key,
            status=(
                TerminalRuntimeBaselineMetricStatus.UNAVAILABLE
                if key == unavailable
                else TerminalRuntimeBaselineMetricStatus.OBSERVED
            ),
            value=None if key == unavailable else 1.0,
            reason="collector_unavailable" if key == unavailable else None,
        )
        for key in sorted(required_baseline_metric_keys())
    )


def _slo_measurements() -> tuple[TerminalRuntimeSloMeasurement, ...]:
    """Return every hard-SLO measurement exactly at its canonical threshold."""

    return tuple(
        TerminalRuntimeSloMeasurement(
            key=criterion.key,
            status=TerminalRuntimeSloStatus.OBSERVED,
            value=criterion.threshold,
        )
        for criterion in terminal_runtime_slo_criteria()
    )


@dataclass
class _ControlledHarness:
    """Test-only command/load/metric implementation with no runtime I/O."""

    wrong_stage: str | None = None
    wrong_candidate_stage: str | None = None
    wrong_concurrency_stage: str | None = None
    missing_metric: bool = False
    unavailable_metric: str | None = None
    calls: list[tuple[str, int]] = field(default_factory=list)
    slo_calls: int = 0

    def _environment(self, stage: str, request_environment: str) -> str:
        """Return a deliberately substituted identity only for negative tests."""

        return "other-environment" if self.wrong_stage == stage else request_environment

    def _candidate(
        self,
        stage: str,
        request_candidate: TerminalRuntimeBaselineCandidate,
    ) -> TerminalRuntimeBaselineCandidate:
        """Return a deliberately substituted candidate for one negative test."""

        if self.wrong_candidate_stage == stage:
            return replace(request_candidate, candidate_release="other-release")
        return request_candidate

    def _concurrency(self, stage: str, request_concurrency: int) -> int:
        """Return a deliberately substituted level for one negative test."""

        return 5 if self.wrong_concurrency_stage == stage else request_concurrency

    def execute(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
    ) -> TerminalRuntimeBaselineCommandReceipt:
        """Record and return the requested command receipt."""

        self.calls.append(("command", request.concurrency))
        return TerminalRuntimeBaselineCommandReceipt(
            environment=self._environment("command", request.environment),
            candidate_identity=self._candidate("command", request.candidate_identity),
            concurrency=self._concurrency("command", request.concurrency),
        )

    def run(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
        command: TerminalRuntimeBaselineCommandReceipt,
    ) -> TerminalRuntimeBaselineLoadReceipt:
        """Record and return the requested load receipt."""

        self.calls.append(("load", request.concurrency))
        return TerminalRuntimeBaselineLoadReceipt(
            environment=self._environment("load", request.environment),
            candidate_identity=self._candidate("load", request.candidate_identity),
            concurrency=self._concurrency("load", request.concurrency),
            sample_count=20,
        )

    def collect(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
        load: TerminalRuntimeBaselineLoadReceipt,
    ) -> TerminalRuntimeBaselineMetricSnapshot:
        """Record and return explicit metric values without filling omissions."""

        self.calls.append(("metric", request.concurrency))
        metrics = _metrics(self.unavailable_metric)
        if self.missing_metric:
            metrics = metrics[:-1]
        return TerminalRuntimeBaselineMetricSnapshot(
            environment=self._environment("metric", request.environment),
            candidate_identity=self._candidate("metric", request.candidate_identity),
            concurrency=self._concurrency("metric", request.concurrency),
            captured_at=CAPTURED_AT,
            metrics=metrics,
        )

    def collect_slo(
        self,
        request: TerminalRuntimeBaselineCollectionRequest,
    ) -> TerminalRuntimeBaselineSloSnapshot:
        """Record and return explicit hard-SLO values."""

        self.slo_calls += 1
        return TerminalRuntimeBaselineSloSnapshot(
            environment=self._environment("slo", request.environment),
            candidate_identity=request.candidate_identity,
            captured_at=CAPTURED_AT,
            measurements=_slo_measurements(),
        )


def _observer(harness: _ControlledHarness) -> TerminalRuntimeBaselineControlledObserver:
    """Build the adapter from only the three injected harness ports."""

    return TerminalRuntimeBaselineControlledObserver(harness, harness, harness)


def test_controlled_observer_runs_all_levels_and_hard_slo_through_injected_ports() -> None:
    """The collector receives four exact levels and one bound hard-SLO report."""

    harness = _ControlledHarness()
    report = TerminalRuntimeBaselineCollector(_observer(harness)).collect(_collection_request())

    assert report.ready_for_capacity_gate is True
    assert [level for stage, level in harness.calls if stage == "command"] == [1, 5, 10, 20]
    assert [level for stage, level in harness.calls if stage == "load"] == [1, 5, 10, 20]
    assert [level for stage, level in harness.calls if stage == "metric"] == [1, 5, 10, 20]
    assert harness.slo_calls == 1


def test_controlled_observer_preserves_explicit_unavailable_metric() -> None:
    """Missing data remains unavailable and the collector closes the capacity gate."""

    harness = _ControlledHarness(unavailable_metric="model_latency_ms")
    sample = _observer(harness).observe(_request())

    metric = next(item for item in sample.metrics if item.key == "model_latency_ms")
    assert metric.status is TerminalRuntimeBaselineMetricStatus.UNAVAILABLE
    assert metric.value is None
    with pytest.raises(TerminalRuntimeBaselineObservationError, match="incomplete"):
        TerminalRuntimeBaselineCollector(_observer(harness)).collect(_collection_request())
    assert harness.slo_calls == 0


def test_controlled_observer_rejects_missing_metric_instead_of_defaulting_to_zero() -> None:
    """A harness cannot omit a metric and have the adapter invent a zero."""

    harness = _ControlledHarness(missing_metric=True)
    with pytest.raises(TerminalRuntimeControlledObservationError, match="metric snapshot"):
        _observer(harness).observe(_request())


@pytest.mark.parametrize("stage", ["command", "load", "metric"])
def test_controlled_observer_rejects_environment_substitution(stage: str) -> None:
    """Every injected stage must preserve the requested environment."""

    harness = _ControlledHarness(wrong_stage=stage)
    with pytest.raises(TerminalRuntimeControlledObservationError, match="environment"):
        _observer(harness).observe(_request())

    assert all(record[0] != "metric" for record in harness.calls) if stage != "metric" else True


def test_controlled_observer_rejects_slo_environment_substitution() -> None:
    """Hard-SLO evidence cannot be taken from another environment."""

    harness = _ControlledHarness(wrong_stage="slo")
    with pytest.raises(TerminalRuntimeControlledObservationError, match="SLO environment"):
        _observer(harness).observe_slo(_collection_request())


@pytest.mark.parametrize("stage", ["command", "load", "metric"])
def test_controlled_observer_rejects_candidate_substitution(stage: str) -> None:
    """Every injected level must preserve the immutable candidate identity."""

    harness = _ControlledHarness(wrong_candidate_stage=stage)
    with pytest.raises(TerminalRuntimeControlledObservationError, match="candidate"):
        _observer(harness).observe(_request())


@pytest.mark.parametrize("stage", ["command", "load", "metric"])
def test_controlled_observer_rejects_concurrency_substitution(stage: str) -> None:
    """Every injected level must preserve the requested concurrency."""

    harness = _ControlledHarness(wrong_concurrency_stage=stage)
    with pytest.raises(TerminalRuntimeControlledObservationError, match="concurrency"):
        _observer(harness).observe(_request())


def test_controlled_observer_module_has_no_runtime_enabling_dependencies() -> None:
    """The adapter remains an injected boundary, not a production runner."""

    path = Path("apps/agent_runtime/infrastructure/terminal_runtime_controlled_observer.py")
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
        for forbidden in ("django", "celery", "requests", "subprocess", "socket")
    )
    assert "TerminalQueued" not in source
    assert "OpenAIAgentsTerminalService" not in source
    assert "default" not in source.casefold()


def test_controlled_observer_result_is_a_canonical_baseline_sample() -> None:
    """The adapter returns the exact candidate identity supplied by the request."""

    sample = _observer(_ControlledHarness()).observe(_request(20))

    assert type(sample) is TerminalRuntimeBaselineSample
    assert sample.candidate_identity == CANDIDATE
    assert sample.environment == "controlled-staging"
    assert sample.concurrency == 20
