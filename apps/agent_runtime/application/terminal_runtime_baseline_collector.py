"""Fail-closed orchestration boundary for a future Terminal baseline collector.

The collector coordinates an injected observation port at the required
1/5/10/20 concurrency levels.  It performs no network, process, database,
broker, or Agent work itself.  A real staging adapter may implement the port;
this module refuses to return a capacity report when any required metric is
unavailable or an observation is bound to a different candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineCandidate,
    TerminalRuntimeBaselineContractError,
    TerminalRuntimeBaselineReport,
    TerminalRuntimeBaselineSample,
    required_concurrency_levels,
)


class TerminalRuntimeBaselineObservationError(TerminalRuntimeBaselineContractError):
    """Raised when a baseline observation cannot prove a complete sample."""


def _require_environment(value: object) -> str:
    """Require a non-empty, whitespace-free environment identity."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise TerminalRuntimeBaselineObservationError(
            "environment must be a non-empty token without whitespace"
        )
    return value


def _validated_candidate(
    value: object,
) -> TerminalRuntimeBaselineCandidate:
    """Reconstruct a candidate so ``object.__new__`` cannot bypass validation."""

    if type(value) is not TerminalRuntimeBaselineCandidate:
        raise TerminalRuntimeBaselineObservationError(
            "candidate_identity must be TerminalRuntimeBaselineCandidate"
        )
    try:
        candidate = TerminalRuntimeBaselineCandidate(
            candidate_commit=value.candidate_commit,
            candidate_release=value.candidate_release,
            oci_revision=value.oci_revision,
            runtime_manifest_digest=value.runtime_manifest_digest,
            test_matrix_digest=value.test_matrix_digest,
        )
    except (AttributeError, TypeError, TerminalRuntimeBaselineContractError) as exc:
        raise TerminalRuntimeBaselineObservationError(
            "candidate_identity failed canonical validation"
        ) from exc
    if candidate != value:
        raise TerminalRuntimeBaselineObservationError(
            "candidate_identity failed canonical validation"
        )
    return candidate


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineCollectionRequest:
    """Immutable identity shared by every requested baseline level."""

    environment: str
    candidate_identity: TerminalRuntimeBaselineCandidate

    def __post_init__(self) -> None:
        """Validate the collection identity before any observation is requested."""

        _require_environment(self.environment)
        _validated_candidate(self.candidate_identity)


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineObservationRequest:
    """One level request passed to an injected observation adapter."""

    environment: str
    candidate_identity: TerminalRuntimeBaselineCandidate
    concurrency: int

    def __post_init__(self) -> None:
        """Validate requested level and immutable candidate binding."""

        _require_environment(self.environment)
        _validated_candidate(self.candidate_identity)
        if (
            type(self.concurrency) is not int
            or self.concurrency not in required_concurrency_levels()
        ):
            raise TerminalRuntimeBaselineObservationError(
                "concurrency must be one of 1, 5, 10, or 20"
            )


class TerminalRuntimeBaselineObservationPort(Protocol):
    """Port implemented by a controlled staging/production observer."""

    def observe(
        self,
        request: TerminalRuntimeBaselineObservationRequest,
    ) -> TerminalRuntimeBaselineSample:
        """Return one real observation without changing its requested identity."""

        ...


class TerminalRuntimeBaselineCollector:
    """Coordinate complete baseline observations without inventing measurements."""

    def __init__(self, observer: TerminalRuntimeBaselineObservationPort) -> None:
        """Create a collector with an explicitly injected observation port."""

        self._observer = observer

    def collect(
        self,
        request: TerminalRuntimeBaselineCollectionRequest,
    ) -> TerminalRuntimeBaselineReport:
        """Collect all four levels or fail closed without returning a report.

        The injected observer is called exactly once for each required level.
        A sample with unavailable metrics, a changed environment/candidate, or
        a wrong concurrency level is rejected before report construction.
        """

        samples: list[TerminalRuntimeBaselineSample] = []
        for concurrency in sorted(required_concurrency_levels()):
            observation_request = TerminalRuntimeBaselineObservationRequest(
                environment=request.environment,
                candidate_identity=request.candidate_identity,
                concurrency=concurrency,
            )
            sample = self._observer.observe(observation_request)
            if type(sample) is not TerminalRuntimeBaselineSample:
                raise TerminalRuntimeBaselineObservationError(
                    "observation port returned an invalid baseline sample"
                )
            sample_candidate = _validated_candidate(sample.candidate_identity)
            try:
                validated_sample = TerminalRuntimeBaselineSample(
                    environment=sample.environment,
                    candidate_commit=sample.candidate_commit,
                    candidate_release=sample.candidate_release,
                    concurrency=sample.concurrency,
                    sample_count=sample.sample_count,
                    captured_at=sample.captured_at,
                    metrics=sample.metrics,
                    candidate_identity=sample_candidate,
                )
            except (AttributeError, TypeError, TerminalRuntimeBaselineContractError) as exc:
                raise TerminalRuntimeBaselineObservationError(
                    "observation port returned an invalid baseline sample"
                ) from exc
            if validated_sample != sample:
                raise TerminalRuntimeBaselineObservationError(
                    "observation port returned an invalid baseline sample"
                )
            sample = validated_sample
            if sample.environment != request.environment:
                raise TerminalRuntimeBaselineObservationError(
                    "baseline sample environment changed during collection"
                )
            if sample.candidate_identity != request.candidate_identity:
                raise TerminalRuntimeBaselineObservationError(
                    "baseline sample candidate changed during collection"
                )
            if sample.concurrency != concurrency:
                raise TerminalRuntimeBaselineObservationError(
                    "baseline sample concurrency changed during collection"
                )
            if not sample.all_metrics_observed:
                raise TerminalRuntimeBaselineObservationError(
                    f"baseline sample at concurrency {concurrency} is incomplete"
                )
            samples.append(sample)

        report = TerminalRuntimeBaselineReport(samples=tuple(samples))
        if not report.ready_for_capacity_gate:
            raise TerminalRuntimeBaselineObservationError(
                "baseline report is not ready for a capacity gate"
            )
        return report
