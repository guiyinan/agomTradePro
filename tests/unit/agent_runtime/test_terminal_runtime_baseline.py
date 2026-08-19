"""Pure TAR-01 baseline evidence contract tests."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineCandidate,
    TerminalRuntimeBaselineContractError,
    TerminalRuntimeBaselineMetric,
    TerminalRuntimeBaselineMetricStatus,
    TerminalRuntimeBaselineReport,
    TerminalRuntimeBaselineSample,
    metrics_from_iterable,
    required_baseline_metric_keys,
    required_concurrency_levels,
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

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
CANDIDATE = "a" * 40
RELEASE = "20260818130903"
CANDIDATE_IDENTITY = TerminalRuntimeBaselineCandidate(
    candidate_commit=CANDIDATE,
    candidate_release=RELEASE,
    oci_revision="b" * 40,
    runtime_manifest_digest="c" * 64,
    test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
)


def _metrics(*, unavailable: str | None = None) -> tuple[TerminalRuntimeBaselineMetric, ...]:
    return metrics_from_iterable(
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
    )


def _sample(
    concurrency: int,
    *,
    candidate_commit: str | None = CANDIDATE,
    candidate_release: str | None = RELEASE,
    candidate_identity: TerminalRuntimeBaselineCandidate | None = CANDIDATE_IDENTITY,
    unavailable: str | None = None,
) -> TerminalRuntimeBaselineSample:
    return TerminalRuntimeBaselineSample(
        environment="staging",
        candidate_commit=candidate_commit,
        candidate_release=candidate_release,
        concurrency=concurrency,
        sample_count=20,
        captured_at=NOW,
        metrics=_metrics(unavailable=unavailable),
        candidate_identity=candidate_identity,
    )


def _slo_report(*, violation: str | None = None) -> TerminalRuntimeSloReport:
    measurements = []
    for criterion in terminal_runtime_slo_criteria():
        value = criterion.threshold
        if criterion.key == violation:
            value = criterion.threshold + 1
        measurements.append(
            TerminalRuntimeSloMeasurement(
                key=criterion.key,
                status=TerminalRuntimeSloStatus.OBSERVED,
                value=value,
            )
        )
    return TerminalRuntimeSloReport(
        environment="staging",
        candidate_commit=CANDIDATE_IDENTITY.candidate_commit,
        candidate_release=CANDIDATE_IDENTITY.candidate_release,
        oci_revision=CANDIDATE_IDENTITY.oci_revision,
        runtime_manifest_digest=CANDIDATE_IDENTITY.runtime_manifest_digest,
        test_matrix_digest=CANDIDATE_IDENTITY.test_matrix_digest,
        captured_at=NOW,
        measurements=tuple(measurements),
    )


def test_report_requires_all_four_levels_and_is_ready_only_when_observed() -> None:
    report = TerminalRuntimeBaselineReport(
        samples=tuple(_sample(level) for level in sorted(required_concurrency_levels())),
        slo_report=_slo_report(),
    )

    assert report.candidate_bound is True
    assert report.ready_for_capacity_gate is True

    incomplete = TerminalRuntimeBaselineReport(
        samples=tuple(
            _sample(level, unavailable="model_latency_ms")
            for level in sorted(required_concurrency_levels())
        ),
        slo_report=_slo_report(),
    )
    assert incomplete.candidate_bound is True
    assert incomplete.ready_for_capacity_gate is False

    no_slo = TerminalRuntimeBaselineReport(
        samples=tuple(_sample(level) for level in sorted(required_concurrency_levels()))
    )
    assert no_slo.ready_for_capacity_gate is False

    breached = TerminalRuntimeBaselineReport(
        samples=tuple(_sample(level) for level in sorted(required_concurrency_levels())),
        slo_report=_slo_report(violation="run_api_p95_ms"),
    )
    assert breached.ready_for_capacity_gate is False


def test_report_rejects_missing_or_duplicate_concurrency_level() -> None:
    with pytest.raises(TerminalRuntimeBaselineContractError, match="requires samples"):
        TerminalRuntimeBaselineReport(samples=(_sample(1),))
    with pytest.raises(TerminalRuntimeBaselineContractError, match="exact and unique"):
        TerminalRuntimeBaselineReport(samples=(_sample(1), _sample(1), _sample(5), _sample(10)))


def test_report_rejects_mixed_environment_or_candidate() -> None:
    mixed = [_sample(level) for level in sorted(required_concurrency_levels())]
    mixed[-1] = TerminalRuntimeBaselineSample(
        environment="production",
        candidate_commit=CANDIDATE,
        candidate_release=RELEASE,
        concurrency=20,
        sample_count=20,
        captured_at=NOW,
        metrics=_metrics(),
        candidate_identity=CANDIDATE_IDENTITY,
    )
    with pytest.raises(TerminalRuntimeBaselineContractError, match="environment and candidate"):
        TerminalRuntimeBaselineReport(samples=tuple(mixed))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"status": TerminalRuntimeBaselineMetricStatus.OBSERVED, "value": None},
            "must have a value",
        ),
        (
            {"status": TerminalRuntimeBaselineMetricStatus.UNAVAILABLE, "value": 1.0},
            "cannot carry a value",
        ),
        (
            {"status": TerminalRuntimeBaselineMetricStatus.OBSERVED, "value": True},
            "must be numeric",
        ),
        ({"status": TerminalRuntimeBaselineMetricStatus.OBSERVED, "value": float("nan")}, "finite"),
    ],
)
def test_metric_rejects_ambiguous_or_non_finite_values(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(TerminalRuntimeBaselineContractError, match=message):
        TerminalRuntimeBaselineMetric(key="web_p95_ms", reason="not collected", **kwargs)


def test_sample_rejects_naive_clock_and_unbound_candidate_pair() -> None:
    with pytest.raises(TerminalRuntimeBaselineContractError, match="timezone-aware"):
        TerminalRuntimeBaselineSample(
            environment="staging",
            candidate_commit=CANDIDATE,
            candidate_release=RELEASE,
            concurrency=1,
            sample_count=20,
            captured_at=NOW.replace(tzinfo=None),
            metrics=_metrics(),
            candidate_identity=CANDIDATE_IDENTITY,
        )
    with pytest.raises(TerminalRuntimeBaselineContractError, match="supplied together"):
        _sample(1, candidate_commit=CANDIDATE, candidate_release=None)


def test_sample_rejects_backwards_web_percentiles() -> None:
    metrics = list(_metrics())
    metrics[sorted(required_baseline_metric_keys()).index("web_p95_ms")] = (
        TerminalRuntimeBaselineMetric(
            key="web_p95_ms",
            status=TerminalRuntimeBaselineMetricStatus.OBSERVED,
            value=0.5,
        )
    )
    with pytest.raises(TerminalRuntimeBaselineContractError, match="non-decreasing"):
        TerminalRuntimeBaselineSample(
            environment="staging",
            candidate_commit=CANDIDATE,
            candidate_release=RELEASE,
            concurrency=1,
            sample_count=20,
            captured_at=NOW,
            metrics=tuple(metrics),
            candidate_identity=CANDIDATE_IDENTITY,
        )


def test_report_rejects_incomplete_or_mixed_candidate_identity() -> None:
    with pytest.raises(TerminalRuntimeBaselineContractError, match="complete candidate identity"):
        _sample(1, candidate_identity=None)

    mixed = [_sample(level) for level in sorted(required_concurrency_levels())]
    mixed[-1] = _sample(
        20,
        candidate_identity=TerminalRuntimeBaselineCandidate(
            candidate_commit=CANDIDATE,
            candidate_release=RELEASE,
            oci_revision="e" * 40,
            runtime_manifest_digest="c" * 64,
            test_matrix_digest="d" * 64,
        ),
    )
    with pytest.raises(TerminalRuntimeBaselineContractError, match="environment and candidate"):
        TerminalRuntimeBaselineReport(samples=tuple(mixed))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("oci_revision", "not-a-revision"),
        ("runtime_manifest_digest", "f" * 63),
        ("test_matrix_digest", "G" * 64),
    ],
)
def test_candidate_identity_rejects_missing_or_forged_artifact_binding(
    field: str, value: str
) -> None:
    values = {
        "candidate_commit": CANDIDATE,
        "candidate_release": RELEASE,
        "oci_revision": "b" * 40,
        "runtime_manifest_digest": "c" * 64,
        "test_matrix_digest": "d" * 64,
    }
    values[field] = value
    with pytest.raises(TerminalRuntimeBaselineContractError):
        TerminalRuntimeBaselineCandidate(**values)


def test_sample_rejects_forged_candidate_identity_object() -> None:
    """A forged frozen dataclass cannot bypass identity validation at intake."""

    forged = object.__new__(TerminalRuntimeBaselineCandidate)
    object.__setattr__(forged, "candidate_commit", CANDIDATE)
    object.__setattr__(forged, "candidate_release", RELEASE)
    object.__setattr__(forged, "oci_revision", "not-a-revision")
    object.__setattr__(forged, "runtime_manifest_digest", "c" * 64)
    object.__setattr__(forged, "test_matrix_digest", "d" * 64)

    with pytest.raises(TerminalRuntimeBaselineContractError, match="invalid or forged"):
        _sample(1, candidate_identity=forged)


def test_sample_rejects_forged_metric_and_float_concurrency() -> None:
    forged = object.__new__(TerminalRuntimeBaselineMetric)
    object.__setattr__(forged, "key", "web_p50_ms")
    object.__setattr__(forged, "status", TerminalRuntimeBaselineMetricStatus.OBSERVED)
    object.__setattr__(forged, "value", float("nan"))
    object.__setattr__(forged, "reason", None)
    metrics = list(_metrics())
    metrics[sorted(required_baseline_metric_keys()).index("web_p50_ms")] = forged

    with pytest.raises(TerminalRuntimeBaselineContractError, match="canonical validation"):
        TerminalRuntimeBaselineSample(
            environment="staging",
            candidate_commit=CANDIDATE,
            candidate_release=RELEASE,
            concurrency=1,
            sample_count=20,
            captured_at=NOW,
            metrics=tuple(metrics),
            candidate_identity=CANDIDATE_IDENTITY,
        )
    with pytest.raises(TerminalRuntimeBaselineContractError, match="concurrency"):
        TerminalRuntimeBaselineSample(
            environment="staging",
            candidate_commit=CANDIDATE,
            candidate_release=RELEASE,
            concurrency=1.0,  # type: ignore[arg-type]
            sample_count=20,
            captured_at=NOW,
            metrics=_metrics(),
            candidate_identity=CANDIDATE_IDENTITY,
        )


def test_contract_module_is_stdlib_only_and_does_not_collect_or_call_runtime() -> None:
    source_path = Path("apps/agent_runtime/application/terminal_runtime_baseline.py")
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
    assert ".objects" not in source
    assert "OpenAIAgentsTerminalService" not in source
    assert "requests" not in imported_names
