"""Pure fail-closed tests for the future Terminal baseline observation port."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineCandidate,
    TerminalRuntimeBaselineContractError,
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
    TerminalRuntimeSloReport,
    TerminalRuntimeSloStatus,
    terminal_runtime_slo_criteria,
)
from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix_digest,
)

CANDIDATE = TerminalRuntimeBaselineCandidate(
    candidate_commit="a" * 40,
    candidate_release="20260819090000",
    oci_revision="b" * 40,
    runtime_manifest_digest="c" * 64,
    test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
)
NOW = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)


def _sample(
    request: TerminalRuntimeBaselineObservationRequest,
    *,
    unavailable: str | None = None,
    candidate: TerminalRuntimeBaselineCandidate = CANDIDATE,
    concurrency: int | None = None,
) -> TerminalRuntimeBaselineSample:
    return TerminalRuntimeBaselineSample(
        environment=request.environment,
        candidate_commit=candidate.candidate_commit,
        candidate_release=candidate.candidate_release,
        concurrency=request.concurrency if concurrency is None else concurrency,
        sample_count=20,
        captured_at=NOW,
        metrics=tuple(
            TerminalRuntimeBaselineMetric(
                key=key,
                status=(
                    TerminalRuntimeBaselineMetricStatus.UNAVAILABLE
                    if key == unavailable
                    else TerminalRuntimeBaselineMetricStatus.OBSERVED
                ),
                value=None if key == unavailable else 1.0,
                reason="not_collected" if key == unavailable else None,
            )
            for key in sorted(required_baseline_metric_keys())
        ),
        candidate_identity=candidate,
    )


@dataclass
class _FakeObserver:
    """Test-only observer standing in for an external controlled collector."""

    unavailable: str | None = None
    wrong_candidate: TerminalRuntimeBaselineCandidate | None = None
    wrong_concurrency: int | None = None
    slo_violation: str | None = None
    calls: list[TerminalRuntimeBaselineObservationRequest] = field(default_factory=list)
    slo_calls: list[TerminalRuntimeBaselineCollectionRequest] = field(default_factory=list)

    def observe(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
    ) -> TerminalRuntimeBaselineSample:
        """Record request and return a deterministic test observation."""

        self.calls.append(request)
        return _sample(
            request,
            unavailable=self.unavailable,
            candidate=self.wrong_candidate or request.candidate_identity,
            concurrency=self.wrong_concurrency,
        )

    def observe_slo(
        self,
        request: TerminalRuntimeBaselineCollectionRequest,
    ) -> TerminalRuntimeSloReport:
        """Return deterministic hard-SLO evidence for the requested candidate."""

        self.slo_calls.append(request)
        measurements = []
        for criterion in terminal_runtime_slo_criteria():
            value = criterion.threshold
            if criterion.key == self.slo_violation:
                value = criterion.threshold + 1
            measurements.append(
                TerminalRuntimeSloMeasurement(
                    key=criterion.key,
                    status=TerminalRuntimeSloStatus.OBSERVED,
                    value=value,
                )
            )
        candidate = request.candidate_identity
        return TerminalRuntimeSloReport(
            environment=request.environment,
            candidate_commit=candidate.candidate_commit,
            candidate_release=candidate.candidate_release,
            oci_revision=candidate.oci_revision,
            runtime_manifest_digest=candidate.runtime_manifest_digest,
            test_matrix_digest=candidate.test_matrix_digest,
            captured_at=NOW,
            measurements=tuple(measurements),
        )


def _request() -> TerminalRuntimeBaselineCollectionRequest:
    return TerminalRuntimeBaselineCollectionRequest(
        environment="staging",
        candidate_identity=CANDIDATE,
    )


def test_collector_requests_each_level_once_and_returns_complete_report() -> None:
    observer = _FakeObserver()

    report = TerminalRuntimeBaselineCollector(observer).collect(_request())

    assert [call.concurrency for call in observer.calls] == [1, 5, 10, 20]
    assert observer.slo_calls == [_request()]
    assert report.candidate_bound is True
    assert report.ready_for_capacity_gate is True


def test_collector_rejects_unavailable_metrics_before_returning_capacity_evidence() -> None:
    observer = _FakeObserver(unavailable="model_latency_ms")

    with pytest.raises(TerminalRuntimeBaselineObservationError, match="incomplete"):
        TerminalRuntimeBaselineCollector(observer).collect(_request())

    assert len(observer.calls) == 1
    assert observer.slo_calls == []


def test_collector_rejects_observed_metrics_when_a_hard_slo_is_breached() -> None:
    observer = _FakeObserver(slo_violation="run_api_p95_ms")

    with pytest.raises(TerminalRuntimeBaselineObservationError, match="does not satisfy"):
        TerminalRuntimeBaselineCollector(observer).collect(_request())

    assert len(observer.calls) == 4
    assert len(observer.slo_calls) == 1


def test_collector_rejects_candidate_or_level_substitution() -> None:
    wrong_candidate = TerminalRuntimeBaselineCandidate(
        candidate_commit="e" * 40,
        candidate_release="20260819090000",
        oci_revision="b" * 40,
        runtime_manifest_digest="c" * 64,
        test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
    )
    with pytest.raises(TerminalRuntimeBaselineObservationError, match="candidate"):
        TerminalRuntimeBaselineCollector(_FakeObserver(wrong_candidate=wrong_candidate)).collect(
            _request()
        )

    with pytest.raises(TerminalRuntimeBaselineObservationError, match="concurrency"):
        TerminalRuntimeBaselineCollector(_FakeObserver(wrong_concurrency=5)).collect(_request())


def test_collection_identity_rejects_invalid_environment_or_candidate() -> None:
    with pytest.raises(TerminalRuntimeBaselineObservationError, match="environment"):
        TerminalRuntimeBaselineCollectionRequest(
            environment="bad env", candidate_identity=CANDIDATE
        )
    with pytest.raises(TerminalRuntimeBaselineObservationError, match="candidate_identity"):
        TerminalRuntimeBaselineCollectionRequest(
            environment="staging",
            candidate_identity="not-a-candidate",  # type: ignore[arg-type]
        )


def test_collection_identity_revalidates_object_new_forged_candidate() -> None:
    forged = object.__new__(TerminalRuntimeBaselineCandidate)
    object.__setattr__(forged, "candidate_commit", "not-a-commit")
    object.__setattr__(forged, "candidate_release", "20260819090000")
    object.__setattr__(forged, "oci_revision", "b" * 40)
    object.__setattr__(forged, "runtime_manifest_digest", "c" * 64)
    object.__setattr__(forged, "test_matrix_digest", "d" * 64)

    with pytest.raises(TerminalRuntimeBaselineObservationError, match="canonical"):
        TerminalRuntimeBaselineCollectionRequest(
            environment="staging",
            candidate_identity=forged,
        )


def test_collector_module_is_pure_and_has_no_runtime_adapter_dependency() -> None:
    source_path = Path("apps/agent_runtime/application/terminal_runtime_baseline_collector.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert all(not name.startswith("django") for name in imported_names)
    assert all("infrastructure" not in name for name in imported_names)
    assert "requests" not in imported_names
    assert "celery" not in imported_names
    assert "OpenAIAgentsTerminalService" not in source
    assert ".objects" not in source
    assert "TerminalRuntimeBaselineObservationPort" in source
    assert TerminalRuntimeBaselineContractError in TerminalRuntimeBaselineObservationError.__mro__
