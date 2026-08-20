"""Pure bounded-admission decision contract for the future Terminal queue.

The contract evaluates an explicitly observed counter snapshot against the
already-frozen TAR-01 queue policy.  It performs no database query, lock,
broker publish, Celery dispatch, route handling, or Agent work.  A future TAR-02
composition root must obtain the snapshot and serialize the decision inside a
durable admission transaction; this module deliberately cannot make that
transaction appear to be safe by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from apps.agent_runtime.application.terminal_runtime_queue_policy import (
    TerminalAdmissionLimits,
    TerminalRunDeadlines,
    TerminalRuntimeFeatureFlags,
    TerminalRuntimeQueuePolicy,
    TerminalRuntimeQueuePolicyError,
    TerminalWorkerQueueLimits,
)
from apps.agent_runtime.domain.terminal_agent_run_contract import TerminalRunContractError


class TerminalRuntimeAdmissionError(TerminalRunContractError):
    """Raised when an admission snapshot or policy cannot be validated."""


class TerminalAdmissionDecisionReason(StrEnum):
    """Stable reasons for a queued admission decision."""

    ACCEPTED = "accepted_queued"
    SUBMISSIONS_PAUSED = "submissions_paused"
    QUEUED_UNAVAILABLE = "queued_unavailable"
    PER_USER_ACTIVE_LIMIT = "per_user_active_limit"
    PER_USER_QUEUED_LIMIT = "per_user_queued_limit"
    GLOBAL_ACTIVE_LIMIT = "global_active_limit"
    GLOBAL_QUEUED_LIMIT = "global_queued_limit"


@dataclass(frozen=True, slots=True)
class TerminalAdmissionSnapshot:
    """Explicit owner and global counters observed before one admission."""

    actor_user_id: int
    user_active: int
    user_queued: int
    global_active: int
    global_queued: int
    worker_ready: bool

    def __post_init__(self) -> None:
        """Reject ambiguous, negative, or internally impossible counters."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise TerminalRuntimeAdmissionError("actor_user_id must be a positive integer")
        for field_name in ("user_active", "user_queued", "global_active", "global_queued"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise TerminalRuntimeAdmissionError(f"{field_name} must be a non-negative integer")
        if self.user_active > self.global_active:
            raise TerminalRuntimeAdmissionError("user_active cannot exceed global_active")
        if self.user_queued > self.global_queued:
            raise TerminalRuntimeAdmissionError("user_queued cannot exceed global_queued")
        if type(self.worker_ready) is not bool:
            raise TerminalRuntimeAdmissionError("worker_ready must be a boolean")

    def validate(self) -> None:
        """Revalidate this snapshot before it crosses an adapter boundary."""

        self.__post_init__()


@dataclass(frozen=True, slots=True)
class TerminalAdmissionDecision:
    """Immutable result of one bounded queued-admission evaluation."""

    actor_user_id: int
    accepted: bool
    reason: TerminalAdmissionDecisionReason

    def __post_init__(self) -> None:
        """Ensure the accepted flag cannot contradict the stable reason."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise TerminalRuntimeAdmissionError("actor_user_id must be a positive integer")
        if type(self.accepted) is not bool:
            raise TerminalRuntimeAdmissionError("accepted must be a boolean")
        if not isinstance(self.reason, TerminalAdmissionDecisionReason):
            raise TerminalRuntimeAdmissionError("reason must be TerminalAdmissionDecisionReason")
        if self.accepted is not (self.reason is TerminalAdmissionDecisionReason.ACCEPTED):
            raise TerminalRuntimeAdmissionError("accepted flag contradicts admission reason")


def _validate_policy(policy: object) -> TerminalRuntimeQueuePolicy:
    """Revalidate a policy and its nested immutable contracts."""

    if type(policy) is not TerminalRuntimeQueuePolicy:
        raise TerminalRuntimeAdmissionError("policy type is invalid")
    try:
        worker_limits = policy.worker_limits
        admission_limits = policy.admission_limits
        deadlines = policy.deadlines
        feature_flags = policy.feature_flags
        if type(worker_limits) is not TerminalWorkerQueueLimits:
            raise TerminalRuntimeAdmissionError("worker limits type is invalid")
        if type(admission_limits) is not TerminalAdmissionLimits:
            raise TerminalRuntimeAdmissionError("admission limits type is invalid")
        if type(deadlines) is not TerminalRunDeadlines:
            raise TerminalRuntimeAdmissionError("deadline type is invalid")
        if type(feature_flags) is not TerminalRuntimeFeatureFlags:
            raise TerminalRuntimeAdmissionError("feature flag type is invalid")
        worker_limits.__post_init__()
        admission_limits.__post_init__()
        deadlines.__post_init__()
        feature_flags.__post_init__()
        policy.__post_init__()
    except (AttributeError, TypeError, ValueError, TerminalRuntimeQueuePolicyError) as exc:
        if isinstance(exc, TerminalRuntimeAdmissionError):
            raise
        raise TerminalRuntimeAdmissionError("policy failed canonical validation") from exc
    return policy


def _reject(
    actor_user_id: int, reason: TerminalAdmissionDecisionReason
) -> TerminalAdmissionDecision:
    """Build one stable rejected decision."""

    return TerminalAdmissionDecision(actor_user_id=actor_user_id, accepted=False, reason=reason)


def evaluate_terminal_admission(
    policy: TerminalRuntimeQueuePolicy,
    snapshot: TerminalAdmissionSnapshot,
) -> TerminalAdmissionDecision:
    """Evaluate one explicit snapshot without performing admission I/O.

    Equality with any configured cap rejects the request.  Queued admission
    also rejects when either queued flag is disabled or the worker is not
    ready; restricted-inline fallback is never treated as queued acceptance.
    """

    canonical_policy = _validate_policy(policy)
    if type(snapshot) is not TerminalAdmissionSnapshot:
        raise TerminalRuntimeAdmissionError("snapshot type is invalid")
    try:
        snapshot.validate()
    except (AttributeError, TypeError, ValueError, TerminalRuntimeAdmissionError) as exc:
        if isinstance(exc, TerminalRuntimeAdmissionError):
            raise
        raise TerminalRuntimeAdmissionError("snapshot failed canonical validation") from exc

    flags = canonical_policy.feature_flags
    if flags.emergency_stop:
        return _reject(snapshot.actor_user_id, TerminalAdmissionDecisionReason.SUBMISSIONS_PAUSED)
    if not (flags.queued_intake_enabled and flags.queued_worker_enabled and snapshot.worker_ready):
        return _reject(snapshot.actor_user_id, TerminalAdmissionDecisionReason.QUEUED_UNAVAILABLE)

    limits = canonical_policy.admission_limits
    if snapshot.user_active >= limits.per_user_active:
        return _reject(
            snapshot.actor_user_id,
            TerminalAdmissionDecisionReason.PER_USER_ACTIVE_LIMIT,
        )
    if snapshot.user_queued >= limits.per_user_queued:
        return _reject(
            snapshot.actor_user_id,
            TerminalAdmissionDecisionReason.PER_USER_QUEUED_LIMIT,
        )
    if snapshot.global_active >= limits.global_active:
        return _reject(snapshot.actor_user_id, TerminalAdmissionDecisionReason.GLOBAL_ACTIVE_LIMIT)
    if snapshot.global_queued >= limits.global_queued:
        return _reject(snapshot.actor_user_id, TerminalAdmissionDecisionReason.GLOBAL_QUEUED_LIMIT)
    return TerminalAdmissionDecision(
        actor_user_id=snapshot.actor_user_id,
        accepted=True,
        reason=TerminalAdmissionDecisionReason.ACCEPTED,
    )


# Preserve a descriptive alias for composition roots that name the runtime.
evaluate_terminal_runtime_admission = evaluate_terminal_admission


__all__ = [
    "TerminalAdmissionDecision",
    "TerminalAdmissionDecisionReason",
    "TerminalAdmissionSnapshot",
    "TerminalRuntimeAdmissionError",
    "evaluate_terminal_admission",
    "evaluate_terminal_runtime_admission",
]
