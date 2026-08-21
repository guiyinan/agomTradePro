"""Dormant TAR-01 load-matrix contract tests.

These tests exercise only the injected offline observer boundary.  They do not
create HTTP load, contact a broker, or make a production capacity claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineCandidate,
    TerminalRuntimeBaselineMetric,
    TerminalRuntimeBaselineMetricStatus,
    TerminalRuntimeBaselineReport,
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
)

_CANDIDATE = TerminalRuntimeBaselineCandidate(
    candidate_commit="a" * 40,
    candidate_release="20260821120000",
    oci_revision="b" * 40,
    runtime_manifest_digest="c" * 64,
    test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
)
_CAPTURED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


@dataclass
class _OfflineLoadHarness:
    """Minimal no-I/O harness used to prove the load boundary wiring."""

    unavailable_metric: str | None = None
    calls: list[tuple[str, int]] = field(default_factory=list)

    def execute(
        self, request: TerminalRuntimeBaselineObservationRequest
    ) -> TerminalRuntimeBaselineCommandReceipt:
        """Return an exact command receipt for one requested level."""

        self.calls.append(("command", request.concurrency))
        return TerminalRuntimeBaselineCommandReceipt(
            environment=request.environment,
            candidate_identity=request.candidate_identity,
            concurrency=request.concurrency,
        )

    def run(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
        command: TerminalRuntimeBaselineCommandReceipt,
    ) -> TerminalRuntimeBaselineLoadReceipt:
        """Return a bounded sample cardinality without running a load tool."""

        self.calls.append(("load", request.concurrency))
        return TerminalRuntimeBaselineLoadReceipt(
            environment=request.environment,
            candidate_identity=command.candidate_identity,
            concurrency=request.concurrency,
            sample_count=request.concurrency,
        )

    def collect(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
        load: TerminalRuntimeBaselineLoadReceipt,
    ) -> TerminalRuntimeBaselineMetricSnapshot:
        """Return explicit metric states, preserving unavailable values."""

        self.calls.append(("metric", request.concurrency))
        metrics = tuple(
            TerminalRuntimeBaselineMetric(
                key=key,
                status=(
                    TerminalRuntimeBaselineMetricStatus.UNAVAILABLE
                    if key == self.unavailable_metric
                    else TerminalRuntimeBaselineMetricStatus.OBSERVED
                ),
                value=None if key == self.unavailable_metric else 1.0,
                reason="offline_harness_unavailable" if key == self.unavailable_metric else None,
            )
            for key in sorted(required_baseline_metric_keys())
        )
        return TerminalRuntimeBaselineMetricSnapshot(
            environment=request.environment,
            candidate_identity=load.candidate_identity,
            concurrency=request.concurrency,
            captured_at=_CAPTURED_AT,
            metrics=metrics,
        )

    def collect_slo(
        self, request: TerminalRuntimeBaselineCollectionRequest
    ) -> TerminalRuntimeBaselineSloSnapshot:
        """Return threshold-shaped values without claiming they were observed."""

        return TerminalRuntimeBaselineSloSnapshot(
            environment=request.environment,
            candidate_identity=request.candidate_identity,
            captured_at=_CAPTURED_AT,
            measurements=tuple(
                TerminalRuntimeSloMeasurement(
                    key=criterion.key,
                    status=TerminalRuntimeSloStatus.OBSERVED,
                    value=criterion.threshold,
                )
                for criterion in terminal_runtime_slo_criteria()
            ),
        )


def _collect(harness: _OfflineLoadHarness):
    """Collect one offline report through the production boundary types."""

    request = TerminalRuntimeBaselineCollectionRequest(
        environment="offline-contract",
        candidate_identity=_CANDIDATE,
    )
    return TerminalRuntimeBaselineCollector(
        TerminalRuntimeBaselineControlledObserver(harness, harness, harness)
    ).collect(request)


def test_offline_load_matrix_requests_each_level_once() -> None:
    """The 1/5/10/20 contract is exact and candidate-bound."""

    harness = _OfflineLoadHarness()
    report = _collect(harness)

    assert type(report) is TerminalRuntimeBaselineReport
    assert report.ready_for_capacity_gate is True
    assert [level for stage, level in harness.calls if stage == "command"] == [1, 5, 10, 20]
    assert [level for stage, level in harness.calls if stage == "load"] == [1, 5, 10, 20]
    assert [level for stage, level in harness.calls if stage == "metric"] == [1, 5, 10, 20]


def test_offline_load_matrix_keeps_gate_closed_for_unavailable_metric() -> None:
    """An unavailable metric cannot be converted into a capacity pass."""

    harness = _OfflineLoadHarness(unavailable_metric="model_latency_ms")
    with pytest.raises(TerminalRuntimeBaselineObservationError, match="incomplete"):
        _collect(harness)
