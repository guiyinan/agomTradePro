"""Fail-closed hard SLO evidence contract for TAR-01.

The contract evaluates measurements rather than accepting a caller-provided
``passed`` flag.  Missing observations and threshold violations both keep the
capacity gate closed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix_digest,
)


class TerminalRuntimeSloContractError(ValueError):
    """Raised when hard-SLO evidence is malformed or substituted."""


class TerminalRuntimeSloStatus(StrEnum):
    """Whether a required hard-SLO measurement was observed."""

    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"


class TerminalRuntimeSloComparator(StrEnum):
    """Supported deterministic comparisons for hard-SLO measurements."""

    MAXIMUM = "maximum"
    EXACT = "exact"


@dataclass(frozen=True, slots=True)
class TerminalRuntimeSloCriterion:
    """One immutable threshold derived from plan section 11.1."""

    key: str
    unit: str
    comparator: TerminalRuntimeSloComparator
    threshold: float | int


_CRITERIA: Final[tuple[TerminalRuntimeSloCriterion, ...]] = (
    TerminalRuntimeSloCriterion(
        "run_api_p95_ms", "milliseconds", TerminalRuntimeSloComparator.MAXIMUM, 500
    ),
    TerminalRuntimeSloCriterion(
        "run_api_provider_calls", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "run_api_mcp_calls", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion("ordinary_web_5xx", "count", TerminalRuntimeSloComparator.EXACT, 0),
    TerminalRuntimeSloCriterion(
        "ordinary_web_p95_degradation_percent", "percent", TerminalRuntimeSloComparator.MAXIMUM, 10
    ),
    TerminalRuntimeSloCriterion(
        "daphne_chat_load_restarts", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "idempotent_created_runs", "count", TerminalRuntimeSloComparator.EXACT, 1
    ),
    TerminalRuntimeSloCriterion(
        "idempotent_model_calls", "count", TerminalRuntimeSloComparator.EXACT, 1
    ),
    TerminalRuntimeSloCriterion("cross_user_leaks", "count", TerminalRuntimeSloComparator.EXACT, 0),
    TerminalRuntimeSloCriterion(
        "unrecoverable_running_tasks", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "duplicate_non_idempotent_side_effects", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "queue_boundary_violations", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "unbounded_queue_growth_events", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "timeout_boundary_violations", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "late_terminal_overwrites", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "cancel_checkpoint_violations", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "event_recovery_violations", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "queue_isolation_violations", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
    TerminalRuntimeSloCriterion(
        "secret_occurrences", "count", TerminalRuntimeSloComparator.EXACT, 0
    ),
)
_BY_KEY: Final[dict[str, TerminalRuntimeSloCriterion]] = {
    criterion.key: criterion for criterion in _CRITERIA
}
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_OCI_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")


def _require_token(value: object, field_name: str) -> str:
    """Require a stable non-empty token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise TerminalRuntimeSloContractError(f"{field_name} must be a stable token")
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware evidence timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise TerminalRuntimeSloContractError(f"{field_name} must be timezone-aware")
    return value


def _require_number(value: object, field_name: str) -> float | int:
    """Require a finite non-negative numeric measurement, excluding bool."""

    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise TerminalRuntimeSloContractError(f"{field_name} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise TerminalRuntimeSloContractError(f"{field_name} must be finite and non-negative")
    return value


@dataclass(frozen=True, slots=True)
class TerminalRuntimeSloMeasurement:
    """One observed or explicitly unavailable hard-SLO measurement."""

    key: str
    status: TerminalRuntimeSloStatus
    value: float | int | None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Validate exact keys and observed/unavailable semantics."""

        if self.key not in _BY_KEY:
            raise TerminalRuntimeSloContractError("unknown hard SLO key")
        if not isinstance(self.status, TerminalRuntimeSloStatus):
            raise TerminalRuntimeSloContractError("hard SLO status type was substituted")
        if self.status is TerminalRuntimeSloStatus.OBSERVED:
            if self.value is None:
                raise TerminalRuntimeSloContractError("observed hard SLO requires a value")
            _require_number(self.value, self.key)
            if _BY_KEY[self.key].unit == "count" and type(self.value) is not int:
                raise TerminalRuntimeSloContractError("count hard SLO values must be integers")
            if self.reason is not None:
                raise TerminalRuntimeSloContractError("observed hard SLO cannot carry a reason")
        else:
            if self.value is not None:
                raise TerminalRuntimeSloContractError("unavailable hard SLO cannot carry a value")
            _require_token(self.reason, "unavailable reason")

    @property
    def threshold_satisfied(self) -> bool:
        """Evaluate the canonical threshold without trusting a passed flag."""

        if self.status is not TerminalRuntimeSloStatus.OBSERVED or self.value is None:
            return False
        criterion = _BY_KEY[self.key]
        if criterion.comparator is TerminalRuntimeSloComparator.EXACT:
            return self.value == criterion.threshold
        return self.value <= criterion.threshold


@dataclass(frozen=True, slots=True)
class TerminalRuntimeSloReport:
    """Complete hard-SLO evidence bound to one immutable candidate."""

    environment: str
    candidate_commit: str
    candidate_release: str
    oci_revision: str
    runtime_manifest_digest: str
    test_matrix_digest: str
    captured_at: datetime
    measurements: tuple[TerminalRuntimeSloMeasurement, ...]

    def __post_init__(self) -> None:
        """Require exact candidate identity and every hard-SLO measurement."""

        _require_token(self.environment, "environment")
        if (
            type(self.candidate_commit) is not str
            or _COMMIT_RE.fullmatch(self.candidate_commit) is None
        ):
            raise TerminalRuntimeSloContractError("candidate_commit is invalid")
        _require_token(self.candidate_release, "candidate_release")
        if type(self.oci_revision) is not str or _OCI_RE.fullmatch(self.oci_revision) is None:
            raise TerminalRuntimeSloContractError("oci_revision is invalid")
        for field_name in ("runtime_manifest_digest", "test_matrix_digest"):
            value = getattr(self, field_name)
            if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
                raise TerminalRuntimeSloContractError(f"{field_name} is invalid")
        _require_aware(self.captured_at, "captured_at")
        if type(self.measurements) is not tuple or len(self.measurements) != len(_CRITERIA):
            raise TerminalRuntimeSloContractError("hard SLO report must include every criterion")
        if self.test_matrix_digest != canonical_terminal_runtime_test_matrix_digest():
            raise TerminalRuntimeSloContractError(
                "test_matrix_digest does not match the canonical matrix"
            )
        validated_measurements = []
        for measurement in self.measurements:
            if type(measurement) is not TerminalRuntimeSloMeasurement:
                raise TerminalRuntimeSloContractError("hard SLO measurement type was substituted")
            try:
                validated = TerminalRuntimeSloMeasurement(
                    key=measurement.key,
                    status=measurement.status,
                    value=measurement.value,
                    reason=measurement.reason,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise TerminalRuntimeSloContractError(
                    "hard SLO measurement failed canonical validation"
                ) from exc
            if validated != measurement:
                raise TerminalRuntimeSloContractError(
                    "hard SLO measurement failed canonical validation"
                )
            validated_measurements.append(validated)
        keys = tuple(measurement.key for measurement in validated_measurements)
        if len(set(keys)) != len(keys) or set(keys) != set(_BY_KEY):
            raise TerminalRuntimeSloContractError("hard SLO keys must be exact and unique")

    @property
    def ready_for_capacity_gate(self) -> bool:
        """Return true only when every hard SLO was observed and satisfied."""

        return all(measurement.threshold_satisfied for measurement in self.measurements)

    def validate(self) -> None:
        """Revalidate this report after an untrusted observer boundary."""

        self.__post_init__()


def terminal_runtime_slo_criteria() -> tuple[TerminalRuntimeSloCriterion, ...]:
    """Return the immutable ordered hard-SLO criteria."""

    return _CRITERIA
