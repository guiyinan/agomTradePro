"""Pure baseline evidence contract for the multi-user Terminal runtime.

This module records the shape of a future controlled load observation.  It
does not collect metrics, contact a web server, invoke an Agent provider, or
turn missing observations into zeroes.  A real staging collector must provide
all four required concurrency levels and bind them to one immutable candidate.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final


class TerminalRuntimeBaselineContractError(ValueError):
    """Raised when a runtime baseline observation is malformed or incomplete."""


class TerminalRuntimeBaselineMetricStatus(StrEnum):
    """Whether one required runtime metric was actually observed."""

    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"


_CANDIDATE_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_OCI_REVISION_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")
_REQUIRED_CONCURRENCY: Final[frozenset[int]] = frozenset({1, 5, 10, 20})
_METRIC_UNITS: Final[dict[str, str]] = {
    "web_p50_ms": "milliseconds",
    "web_p95_ms": "milliseconds",
    "web_p99_ms": "milliseconds",
    "cpu_percent": "percent",
    "rss_bytes": "bytes",
    "daphne_active_requests": "count",
    "redis_memory_bytes": "bytes",
    "redis_connected_clients": "count",
    "db_connections": "count",
    "mcp_latency_ms": "milliseconds",
    "model_latency_ms": "milliseconds",
}
_REQUIRED_METRICS: Final[frozenset[str]] = frozenset(_METRIC_UNITS)


def _require_token(value: object, field_name: str) -> str:
    """Require a bounded, whitespace-free evidence token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise TerminalRuntimeBaselineContractError(
            f"{field_name} must be a non-empty token without whitespace"
        )
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    """Require an aware observation clock."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise TerminalRuntimeBaselineContractError(f"{field_name} must be timezone-aware")
    return value


def _require_candidate_commit(value: str | None) -> str | None:
    """Validate an optional immutable candidate commit binding."""

    if value is None:
        return None
    if type(value) is not str or _CANDIDATE_COMMIT_RE.fullmatch(value) is None:
        raise TerminalRuntimeBaselineContractError(
            "candidate_commit must be a lowercase 40-character SHA-1"
        )
    return value


def _require_sha256(value: object, field_name: str) -> str:
    """Require a lowercase SHA-256 digest for a published artifact."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise TerminalRuntimeBaselineContractError(
            f"{field_name} must be a lowercase 64-character SHA-256 digest"
        )
    return value


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineCandidate:
    """Immutable release identity shared by every capacity sample.

    A commit and release alone are not sufficient to prevent mixing samples
    collected from different images or runtime/test snapshots.  The extra
    digests are intentionally typed and exact-equal across the four levels.
    """

    candidate_commit: str
    candidate_release: str
    oci_revision: str
    runtime_manifest_digest: str
    test_matrix_digest: str

    def __post_init__(self) -> None:
        """Validate every part of the immutable candidate binding."""

        if (
            type(self.candidate_commit) is not str
            or _CANDIDATE_COMMIT_RE.fullmatch(self.candidate_commit) is None
        ):
            raise TerminalRuntimeBaselineContractError(
                "candidate_commit must be a lowercase 40-character SHA-1"
            )
        _require_token(self.candidate_release, "candidate_release")
        if (
            type(self.oci_revision) is not str
            or _OCI_REVISION_RE.fullmatch(self.oci_revision) is None
        ):
            raise TerminalRuntimeBaselineContractError(
                "oci_revision must be a lowercase commit or sha256 digest"
            )
        _require_sha256(self.runtime_manifest_digest, "runtime_manifest_digest")
        _require_sha256(self.test_matrix_digest, "test_matrix_digest")

    def validate(self) -> None:
        """Revalidate an identity before it crosses an untrusted boundary."""

        self.__post_init__()


def _validate_candidate_identity(
    value: object,
) -> TerminalRuntimeBaselineCandidate:
    """Reject substituted or forged candidate identities at sample intake."""

    if type(value) is not TerminalRuntimeBaselineCandidate:
        raise TerminalRuntimeBaselineContractError("candidate identity is invalid or forged")
    try:
        value.validate()
    except (AttributeError, TypeError, ValueError):
        raise TerminalRuntimeBaselineContractError(
            "candidate identity is invalid or forged"
        ) from None
    return value


def _require_non_negative_number(value: object, field_name: str) -> float | int:
    """Require a finite, non-negative metric number and reject bool-as-int."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TerminalRuntimeBaselineContractError(f"{field_name} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise TerminalRuntimeBaselineContractError(f"{field_name} must be finite and non-negative")
    return value


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineMetric:
    """One required metric with explicit observed/unavailable semantics."""

    key: str
    status: TerminalRuntimeBaselineMetricStatus
    value: float | int | None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Reject omitted, coerced, or ambiguous metric values."""

        if self.key not in _REQUIRED_METRICS:
            raise TerminalRuntimeBaselineContractError("unknown baseline metric key")
        if not isinstance(self.status, TerminalRuntimeBaselineMetricStatus):
            raise TerminalRuntimeBaselineContractError("metric status type was substituted")
        if self.status is TerminalRuntimeBaselineMetricStatus.OBSERVED:
            if self.value is None:
                raise TerminalRuntimeBaselineContractError(
                    f"observed metric {self.key} must have a value"
                )
            _require_non_negative_number(self.value, self.key)
            if self.reason is not None:
                raise TerminalRuntimeBaselineContractError(
                    f"observed metric {self.key} cannot carry an unavailable reason"
                )
        else:
            if self.value is not None:
                raise TerminalRuntimeBaselineContractError(
                    f"unavailable metric {self.key} cannot carry a value"
                )
            _require_token(self.reason, f"{self.key} unavailable reason")


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineSample:
    """One concurrency-level observation bound to one candidate/environment."""

    environment: str
    candidate_commit: str | None
    candidate_release: str | None
    concurrency: int
    sample_count: int
    captured_at: datetime
    metrics: tuple[TerminalRuntimeBaselineMetric, ...]
    candidate_identity: TerminalRuntimeBaselineCandidate | None = None

    def __post_init__(self) -> None:
        """Validate sample identity, clocks, cardinality, and metric keys."""

        _require_token(self.environment, "environment")
        _require_candidate_commit(self.candidate_commit)
        if (self.candidate_commit is None) != (self.candidate_release is None):
            raise TerminalRuntimeBaselineContractError(
                "candidate_commit and candidate_release must be supplied together"
            )
        if self.candidate_release is not None:
            _require_token(self.candidate_release, "candidate_release")
        if self.candidate_commit is not None and self.candidate_identity is None:
            raise TerminalRuntimeBaselineContractError(
                "complete candidate identity is required for bound samples"
            )
        if self.candidate_identity is not None:
            identity = _validate_candidate_identity(self.candidate_identity)
            if (
                self.candidate_commit != identity.candidate_commit
                or self.candidate_release != identity.candidate_release
            ):
                raise TerminalRuntimeBaselineContractError(
                    "candidate identity does not match legacy candidate fields"
                )
        if isinstance(self.concurrency, bool) or self.concurrency not in _REQUIRED_CONCURRENCY:
            raise TerminalRuntimeBaselineContractError("concurrency must be one of 1, 5, 10, or 20")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int):
            raise TerminalRuntimeBaselineContractError("sample_count must be an integer")
        if self.sample_count <= 0:
            raise TerminalRuntimeBaselineContractError("sample_count must be positive")
        _require_aware(self.captured_at, "captured_at")
        if len(self.metrics) != len(_REQUIRED_METRICS):
            raise TerminalRuntimeBaselineContractError(
                "one sample must include every required runtime metric"
            )
        keys = tuple(metric.key for metric in self.metrics)
        if len(set(keys)) != len(keys) or set(keys) != _REQUIRED_METRICS:
            raise TerminalRuntimeBaselineContractError(
                "baseline metric keys must be exact and unique"
            )
        by_key = {metric.key: metric for metric in self.metrics}
        percentile_values = tuple(
            by_key[key].value for key in ("web_p50_ms", "web_p95_ms", "web_p99_ms")
        )
        if all(value is not None for value in percentile_values) and tuple(
            value for value in percentile_values if value is not None
        ) != tuple(sorted(value for value in percentile_values if value is not None)):
            raise TerminalRuntimeBaselineContractError(
                "web percentile metrics must be non-decreasing"
            )

    @property
    def all_metrics_observed(self) -> bool:
        """Return whether this sample has no unavailable measurements."""

        return all(
            metric.status is TerminalRuntimeBaselineMetricStatus.OBSERVED for metric in self.metrics
        )


@dataclass(frozen=True, slots=True)
class TerminalRuntimeBaselineReport:
    """Complete four-level baseline evidence for one environment/candidate."""

    samples: tuple[TerminalRuntimeBaselineSample, ...]

    def __post_init__(self) -> None:
        """Require exactly one sample for each planned concurrency level."""

        if len(self.samples) != len(_REQUIRED_CONCURRENCY):
            raise TerminalRuntimeBaselineContractError(
                "baseline report requires samples for 1, 5, 10, and 20 users"
            )
        levels = tuple(sample.concurrency for sample in self.samples)
        if set(levels) != _REQUIRED_CONCURRENCY or len(set(levels)) != len(levels):
            raise TerminalRuntimeBaselineContractError(
                "baseline report concurrency levels must be exact and unique"
            )
        environments = {sample.environment for sample in self.samples}
        candidates = {sample.candidate_identity for sample in self.samples}
        if len(environments) != 1 or len(candidates) != 1:
            raise TerminalRuntimeBaselineContractError(
                "baseline report samples must share environment and candidate"
            )

    @property
    def candidate_bound(self) -> bool:
        """Return whether this report is bound to an immutable candidate."""

        return self.samples[0].candidate_identity is not None

    @property
    def ready_for_capacity_gate(self) -> bool:
        """Return whether all planned levels have complete observed metrics."""

        return self.candidate_bound and all(sample.all_metrics_observed for sample in self.samples)


def required_baseline_metric_keys() -> frozenset[str]:
    """Return the immutable metric key set expected from a collector."""

    return _REQUIRED_METRICS


def required_concurrency_levels() -> frozenset[int]:
    """Return the immutable concurrency levels required by TAR-01."""

    return _REQUIRED_CONCURRENCY


def metrics_from_iterable(
    metrics: Iterable[TerminalRuntimeBaselineMetric],
) -> tuple[TerminalRuntimeBaselineMetric, ...]:
    """Freeze an iterable of metric observations for a sample constructor."""

    return tuple(metrics)
