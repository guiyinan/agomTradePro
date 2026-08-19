"""Pure hard-SLO contract tests for TAR-01."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_slo import (
    TerminalRuntimeSloContractError,
    TerminalRuntimeSloMeasurement,
    TerminalRuntimeSloReport,
    TerminalRuntimeSloStatus,
    terminal_runtime_slo_criteria,
)
from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix_digest,
)

NOW = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)


def _measurements(
    *,
    unavailable: str | None = None,
    violation: str | None = None,
) -> tuple[TerminalRuntimeSloMeasurement, ...]:
    values = []
    for criterion in terminal_runtime_slo_criteria():
        value: float | int | None = criterion.threshold
        if criterion.key == violation:
            value = criterion.threshold + 1
        values.append(
            TerminalRuntimeSloMeasurement(
                key=criterion.key,
                status=(
                    TerminalRuntimeSloStatus.UNAVAILABLE
                    if criterion.key == unavailable
                    else TerminalRuntimeSloStatus.OBSERVED
                ),
                value=None if criterion.key == unavailable else value,
                reason="probe_unavailable" if criterion.key == unavailable else None,
            )
        )
    return tuple(values)


def _report(
    *,
    unavailable: str | None = None,
    violation: str | None = None,
) -> TerminalRuntimeSloReport:
    return TerminalRuntimeSloReport(
        environment="staging",
        candidate_commit="a" * 40,
        candidate_release="20260819140000",
        oci_revision="b" * 40,
        runtime_manifest_digest="c" * 64,
        test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
        captured_at=NOW,
        measurements=_measurements(unavailable=unavailable, violation=violation),
    )


def test_complete_threshold_evidence_is_ready_without_caller_passed_flag() -> None:
    report = _report()

    assert report.ready_for_capacity_gate is True
    assert all(measurement.threshold_satisfied for measurement in report.measurements)
    assert not hasattr(report, "passed")


@pytest.mark.parametrize(
    "key",
    [
        "run_api_p95_ms",
        "ordinary_web_p95_degradation_percent",
        "idempotent_created_runs",
        "secret_occurrences",
    ],
)
def test_threshold_breach_fails_capacity_gate(key: str) -> None:
    assert _report(violation=key).ready_for_capacity_gate is False


def test_unavailable_measurement_fails_capacity_gate_without_zero_fill() -> None:
    report = _report(unavailable="queue_isolation_violations")

    assert report.ready_for_capacity_gate is False
    unavailable = next(
        measurement
        for measurement in report.measurements
        if measurement.key == "queue_isolation_violations"
    )
    assert unavailable.value is None
    assert unavailable.reason == "probe_unavailable"


def test_report_rejects_missing_duplicate_or_substituted_measurements() -> None:
    with pytest.raises(TerminalRuntimeSloContractError, match="every criterion"):
        TerminalRuntimeSloReport(
            environment="staging",
            candidate_commit="a" * 40,
            candidate_release="20260819140000",
            oci_revision="b" * 40,
            runtime_manifest_digest="c" * 64,
            test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
            captured_at=NOW,
            measurements=_measurements()[:-1],
        )
    with pytest.raises(TerminalRuntimeSloContractError, match="type was substituted"):
        TerminalRuntimeSloMeasurement(
            key="secret_occurrences",
            status="observed",  # type: ignore[arg-type]
            value=0,
        )
    with pytest.raises(TerminalRuntimeSloContractError, match="must be integers"):
        TerminalRuntimeSloMeasurement(
            key="secret_occurrences",
            status=TerminalRuntimeSloStatus.OBSERVED,
            value=0.0,
        )


def test_report_rejects_object_new_forged_measurement() -> None:
    forged = object.__new__(TerminalRuntimeSloMeasurement)
    object.__setattr__(forged, "key", "secret_occurrences")
    object.__setattr__(forged, "status", TerminalRuntimeSloStatus.OBSERVED)
    object.__setattr__(forged, "value", -1)
    object.__setattr__(forged, "reason", None)
    measurements = list(_measurements())
    measurements[-1] = forged

    with pytest.raises(TerminalRuntimeSloContractError, match="canonical validation"):
        TerminalRuntimeSloReport(
            environment="staging",
            candidate_commit="a" * 40,
            candidate_release="20260819140000",
            oci_revision="b" * 40,
            runtime_manifest_digest="c" * 64,
            test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
            captured_at=NOW,
            measurements=tuple(measurements),
        )


def test_report_rejects_noncanonical_test_matrix_digest() -> None:
    with pytest.raises(TerminalRuntimeSloContractError, match="canonical matrix"):
        TerminalRuntimeSloReport(
            environment="staging",
            candidate_commit="a" * 40,
            candidate_release="20260819140000",
            oci_revision="b" * 40,
            runtime_manifest_digest="c" * 64,
            test_matrix_digest="d" * 64,
            captured_at=NOW,
            measurements=_measurements(),
        )


def test_slo_module_is_stdlib_only_and_does_not_observe_runtime() -> None:
    source = Path("apps/agent_runtime/application/terminal_runtime_slo.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert all(not name.startswith("django") for name in imported)
    assert all("infrastructure" not in name for name in imported)
    assert "requests" not in imported
    assert ".objects" not in source
