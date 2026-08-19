"""Fail-closed adapter for a controlled Terminal runtime load harness.

This module only composes explicitly injected command, load, and metric ports.
It does not know how to reach HTTP, a process, a broker, a database, Celery,
or an Agent provider.  A staging harness can implement the three ports and
return typed receipts; this adapter binds every receipt to the requested
environment, candidate, and concurrency before building application evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineCandidate,
    TerminalRuntimeBaselineContractError,
    TerminalRuntimeBaselineMetric,
    TerminalRuntimeBaselineSample,
)
from apps.agent_runtime.application.terminal_runtime_baseline_collector import (
    TerminalRuntimeBaselineCollectionRequest,
    TerminalRuntimeBaselineObservationError,
    TerminalRuntimeBaselineObservationPort,
    TerminalRuntimeBaselineObservationRequest,
)
from apps.agent_runtime.application.terminal_runtime_slo import (
    TerminalRuntimeSloMeasurement,
    TerminalRuntimeSloReport,
)
from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix_digest,
)


class TerminalRuntimeControlledObservationError(TerminalRuntimeBaselineObservationError):
    """Raised when a controlled harness receipt cannot prove its binding."""


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineCommandReceipt:
    """Receipt proving that one requested load command was executed."""

    environment: str
    candidate_identity: TerminalRuntimeBaselineCandidate
    concurrency: int


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineLoadReceipt:
    """Receipt proving the controlled load sample cardinality and binding."""

    environment: str
    candidate_identity: TerminalRuntimeBaselineCandidate
    concurrency: int
    sample_count: int


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineMetricSnapshot:
    """Typed metric values returned by a controlled harness metric reader."""

    environment: str
    candidate_identity: TerminalRuntimeBaselineCandidate
    concurrency: int
    captured_at: datetime
    metrics: tuple[TerminalRuntimeBaselineMetric, ...]


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineSloSnapshot:
    """Typed hard-SLO values returned by a controlled harness metric reader."""

    environment: str
    candidate_identity: TerminalRuntimeBaselineCandidate
    captured_at: datetime
    measurements: tuple[TerminalRuntimeSloMeasurement, ...]


class TerminalRuntimeBaselineCommandPort(Protocol):
    """Injected port that executes one bounded load command."""

    def execute(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
    ) -> TerminalRuntimeBaselineCommandReceipt:
        """Execute the requested command and return its typed receipt."""

        ...


class TerminalRuntimeBaselineLoadPort(Protocol):
    """Injected port that runs the requested controlled load level."""

    def run(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
        command: TerminalRuntimeBaselineCommandReceipt,
    ) -> TerminalRuntimeBaselineLoadReceipt:
        """Run one level without substituting its command identity."""

        ...


class TerminalRuntimeBaselineMetricPort(Protocol):
    """Injected port that reads metrics from an already controlled run."""

    def collect(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
        load: TerminalRuntimeBaselineLoadReceipt,
    ) -> TerminalRuntimeBaselineMetricSnapshot:
        """Return explicit observed/unavailable metrics for one load level."""

        ...

    def collect_slo(
        self,
        request: TerminalRuntimeBaselineCollectionRequest,
    ) -> TerminalRuntimeBaselineSloSnapshot:
        """Return explicit hard-SLO measurements for the same candidate."""

        ...


class _LevelReceipt(Protocol):
    """Structural view shared by command, load, and metric receipts."""

    environment: str
    candidate_identity: TerminalRuntimeBaselineCandidate
    concurrency: int


def _fail(message: str) -> TerminalRuntimeControlledObservationError:
    """Build a stable error without echoing external receipt values."""

    return TerminalRuntimeControlledObservationError(message)


def _validate_candidate_binding(
    value: object,
    expected: TerminalRuntimeBaselineCandidate,
    stage: str,
) -> None:
    """Require an exact, canonical candidate object from a harness receipt."""

    if type(value) is not TerminalRuntimeBaselineCandidate:
        raise _fail(f"{stage} candidate identity is invalid")
    try:
        value.validate()
    except (AttributeError, TypeError, ValueError) as exc:
        raise _fail(f"{stage} candidate identity is invalid") from exc
    if value != expected:
        raise _fail(f"{stage} candidate identity changed")


def _validate_observation_request(
    request: object,
) -> TerminalRuntimeBaselineObservationRequest:
    """Revalidate a level request before invoking any injected port."""

    if type(request) is not TerminalRuntimeBaselineObservationRequest:
        raise _fail("observation request type is invalid")
    try:
        candidate = request.candidate_identity
        _validate_candidate_binding(candidate, candidate, "request")
        if candidate.test_matrix_digest != canonical_terminal_runtime_test_matrix_digest():
            raise _fail("request test matrix digest is not canonical")
        canonical = TerminalRuntimeBaselineObservationRequest(
            environment=request.environment,
            candidate_identity=candidate,
            concurrency=request.concurrency,
        )
    except (AttributeError, TypeError, ValueError, TerminalRuntimeBaselineContractError) as exc:
        if isinstance(exc, TerminalRuntimeControlledObservationError):
            raise
        raise _fail("observation request failed canonical validation") from exc
    if canonical != request:
        raise _fail("observation request failed canonical validation")
    return canonical


def _validate_collection_request(
    request: object,
) -> TerminalRuntimeBaselineCollectionRequest:
    """Revalidate the collection identity before reading hard-SLO metrics."""

    if type(request) is not TerminalRuntimeBaselineCollectionRequest:
        raise _fail("collection request type is invalid")
    try:
        candidate = request.candidate_identity
        _validate_candidate_binding(candidate, candidate, "request")
        canonical = TerminalRuntimeBaselineCollectionRequest(
            environment=request.environment,
            candidate_identity=candidate,
        )
    except (AttributeError, TypeError, ValueError, TerminalRuntimeBaselineContractError) as exc:
        if isinstance(exc, TerminalRuntimeControlledObservationError):
            raise
        raise _fail("collection request failed canonical validation") from exc
    if canonical != request:
        raise _fail("collection request failed canonical validation")
    return canonical


def _validate_level_receipt(
    value: object,
    expected_type: type[object],
    request: TerminalRuntimeBaselineObservationRequest,
    stage: str,
) -> None:
    """Require exact receipt type and environment/candidate/level identity."""

    if type(value) is not expected_type:
        raise _fail(f"{stage} receipt type is invalid")
    receipt = cast(_LevelReceipt, value)
    try:
        environment = receipt.environment
        candidate = receipt.candidate_identity
        concurrency = receipt.concurrency
    except AttributeError as exc:
        raise _fail(f"{stage} receipt is invalid") from exc
    if environment != request.environment:
        raise _fail(f"{stage} environment changed")
    _validate_candidate_binding(candidate, request.candidate_identity, stage)
    if concurrency != request.concurrency:
        raise _fail(f"{stage} concurrency changed")


def _validate_slo_receipt(
    value: object,
    request: TerminalRuntimeBaselineCollectionRequest,
) -> None:
    """Require exact hard-SLO receipt type and collection identity."""

    if type(value) is not TerminalRuntimeBaselineSloSnapshot:
        raise _fail("SLO receipt type is invalid")
    try:
        environment = value.environment
        candidate = value.candidate_identity
    except AttributeError as exc:
        raise _fail("SLO receipt is invalid") from exc
    if environment != request.environment:
        raise _fail("SLO environment changed")
    _validate_candidate_binding(candidate, request.candidate_identity, "SLO")


class TerminalRuntimeBaselineControlledObserver(TerminalRuntimeBaselineObservationPort):
    """Adapt injected controlled-harness ports to the Application observer port."""

    def __init__(
        self,
        command_port: TerminalRuntimeBaselineCommandPort,
        load_port: TerminalRuntimeBaselineLoadPort,
        metric_port: TerminalRuntimeBaselineMetricPort,
    ) -> None:
        """Create an observer without acquiring any runtime dependency itself."""

        self._command_port = command_port
        self._load_port = load_port
        self._metric_port = metric_port

    def observe(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
    ) -> TerminalRuntimeBaselineSample:
        """Execute one injected load/metric sequence and return bound evidence."""

        canonical_request = _validate_observation_request(request)
        command = self._command_port.execute(canonical_request)
        _validate_level_receipt(
            command,
            TerminalRuntimeBaselineCommandReceipt,
            canonical_request,
            "command",
        )
        load = self._load_port.run(canonical_request, command)
        _validate_level_receipt(
            load,
            TerminalRuntimeBaselineLoadReceipt,
            canonical_request,
            "load",
        )
        metric_snapshot = self._metric_port.collect(canonical_request, load)
        _validate_level_receipt(
            metric_snapshot,
            TerminalRuntimeBaselineMetricSnapshot,
            canonical_request,
            "metric",
        )
        try:
            return TerminalRuntimeBaselineSample(
                environment=canonical_request.environment,
                candidate_commit=canonical_request.candidate_identity.candidate_commit,
                candidate_release=canonical_request.candidate_identity.candidate_release,
                concurrency=canonical_request.concurrency,
                sample_count=load.sample_count,
                captured_at=metric_snapshot.captured_at,
                metrics=metric_snapshot.metrics,
                candidate_identity=canonical_request.candidate_identity,
            )
        except (AttributeError, TypeError, ValueError, TerminalRuntimeBaselineContractError) as exc:
            raise _fail("metric snapshot failed canonical validation") from exc

    def observe_slo(
        self,
        request: TerminalRuntimeBaselineCollectionRequest,
    ) -> TerminalRuntimeSloReport:
        """Read injected hard-SLO measurements and bind them to the candidate."""

        canonical_request = _validate_collection_request(request)
        slo_snapshot = self._metric_port.collect_slo(canonical_request)
        _validate_slo_receipt(slo_snapshot, canonical_request)
        try:
            return TerminalRuntimeSloReport(
                environment=canonical_request.environment,
                candidate_commit=canonical_request.candidate_identity.candidate_commit,
                candidate_release=canonical_request.candidate_identity.candidate_release,
                oci_revision=canonical_request.candidate_identity.oci_revision,
                runtime_manifest_digest=canonical_request.candidate_identity.runtime_manifest_digest,
                test_matrix_digest=canonical_request.candidate_identity.test_matrix_digest,
                captured_at=slo_snapshot.captured_at,
                measurements=slo_snapshot.measurements,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise _fail("hard SLO snapshot failed canonical validation") from exc


# Keep the adjective-first spelling available to controlled harness callers.
ControlledTerminalRuntimeBaselineObserver = TerminalRuntimeBaselineControlledObserver


__all__ = [
    "ControlledTerminalRuntimeBaselineObserver",
    "TerminalRuntimeBaselineCommandPort",
    "TerminalRuntimeBaselineCommandReceipt",
    "TerminalRuntimeBaselineControlledObserver",
    "TerminalRuntimeBaselineLoadPort",
    "TerminalRuntimeBaselineLoadReceipt",
    "TerminalRuntimeBaselineMetricPort",
    "TerminalRuntimeBaselineMetricSnapshot",
    "TerminalRuntimeBaselineSloSnapshot",
    "TerminalRuntimeControlledObservationError",
]
