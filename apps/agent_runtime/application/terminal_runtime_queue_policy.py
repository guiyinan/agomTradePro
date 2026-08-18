"""Pure TAR-01 queue, deadline, and migration-flag contracts.

This module freezes the *shape and safety relationships* for the future
queued Terminal Agent runtime.  It deliberately does not provide defaults,
read environment variables, contact a broker, or decide production capacity.
TAR-02/TAR-03 will inject a validated configuration and implement the
database, worker, broker, and stream adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalRunContractError,
    TerminalRuntimeMode,
)


class TerminalRuntimeQueuePolicyError(TerminalRunContractError):
    """Raised when a bounded runtime policy violates a frozen relationship."""


TERMINAL_AGENT_QUEUE_NAME: Final[str] = "terminal_agent"
TERMINAL_AGENT_STREAM_NAMESPACE: Final[str] = "terminal_agent"
LEGACY_INLINE_CONCURRENCY_CAP: Final[int] = 1
LEGACY_INLINE_TIMEOUT_CAP_SECONDS: Final[int] = 60


class TerminalFallbackMode(StrEnum):
    """Migration behavior when the preferred queued path is unavailable."""

    PAUSE = "pause"
    RESTRICTED_INLINE = "restricted_inline"


class TerminalAdmissionReason(StrEnum):
    """Stable reasons returned by the pure mode-selection contract."""

    ACCEPTED_LOCAL_CLI = "accepted_local_cli"
    ACCEPTED_QUEUED = "accepted_queued"
    ACCEPTED_RESTRICTED_INLINE = "accepted_restricted_inline"
    LEGACY_INLINE_DISABLED = "legacy_inline_disabled"
    QUEUED_UNAVAILABLE = "queued_unavailable"
    SUBMISSIONS_PAUSED = "submissions_paused"


def _require_positive_int(value: object, field_name: str) -> int:
    """Require a positive integer without accepting bool as an integer."""

    if type(value) is not int or value <= 0:
        raise TerminalRuntimeQueuePolicyError(f"{field_name} must be a positive integer")
    return value


def _require_bool(value: object, field_name: str) -> bool:
    """Require an actual boolean rather than a truthy configuration value."""

    if type(value) is not bool:
        raise TerminalRuntimeQueuePolicyError(f"{field_name} must be a boolean")
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware clock for derived deadlines."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise TerminalRuntimeQueuePolicyError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class TerminalWorkerQueueLimits:
    """Explicit worker, broker, and stream bounds for a future adapter.

    Every capacity is supplied by the eventual configuration composition
    root.  The values in this contract are not measured capacity evidence and
    no constructor defaults are provided intentionally.
    """

    queue_name: str
    stream_namespace: str
    worker_concurrency: int
    broker_prefetch_count: int
    queue_max_depth: int
    stream_max_length: int
    stream_ttl_seconds: int
    max_tasks_per_child: int

    def __post_init__(self) -> None:
        """Validate names and positive finite bounds."""

        if self.queue_name != TERMINAL_AGENT_QUEUE_NAME:
            raise TerminalRuntimeQueuePolicyError(
                f"queue_name must be {TERMINAL_AGENT_QUEUE_NAME!r}"
            )
        if self.stream_namespace != TERMINAL_AGENT_STREAM_NAMESPACE:
            raise TerminalRuntimeQueuePolicyError(
                f"stream_namespace must be {TERMINAL_AGENT_STREAM_NAMESPACE!r}"
            )
        for field_name in (
            "worker_concurrency",
            "broker_prefetch_count",
            "queue_max_depth",
            "stream_max_length",
            "stream_ttl_seconds",
            "max_tasks_per_child",
        ):
            _require_positive_int(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class TerminalAdmissionLimits:
    """Per-user and global active/queued admission caps."""

    per_user_active: int
    per_user_queued: int
    global_active: int
    global_queued: int

    def __post_init__(self) -> None:
        """Require coherent per-user and global bounds."""

        for field_name in (
            "per_user_active",
            "per_user_queued",
            "global_active",
            "global_queued",
        ):
            _require_positive_int(getattr(self, field_name), field_name)
        if self.per_user_active > self.global_active:
            raise TerminalRuntimeQueuePolicyError("per_user_active cannot exceed global_active")
        if self.per_user_queued > self.global_queued:
            raise TerminalRuntimeQueuePolicyError("per_user_queued cannot exceed global_queued")


@dataclass(frozen=True, slots=True)
class TerminalRunDeadlines:
    """Relative queue, execution, cancel, heartbeat, and orphan deadlines."""

    max_queue_wait_seconds: int
    soft_timeout_seconds: int
    hard_timeout_seconds: int
    cancel_grace_seconds: int
    heartbeat_interval_seconds: int
    orphan_after_seconds: int

    def __post_init__(self) -> None:
        """Require ordered safety windows and positive deadline durations."""

        for field_name in (
            "max_queue_wait_seconds",
            "soft_timeout_seconds",
            "hard_timeout_seconds",
            "cancel_grace_seconds",
            "heartbeat_interval_seconds",
            "orphan_after_seconds",
        ):
            _require_positive_int(getattr(self, field_name), field_name)
        if self.soft_timeout_seconds >= self.hard_timeout_seconds:
            raise TerminalRuntimeQueuePolicyError(
                "soft_timeout_seconds must be less than hard_timeout_seconds"
            )
        if self.cancel_grace_seconds > self.hard_timeout_seconds:
            raise TerminalRuntimeQueuePolicyError(
                "cancel_grace_seconds cannot exceed hard_timeout_seconds"
            )
        if self.heartbeat_interval_seconds >= self.orphan_after_seconds:
            raise TerminalRuntimeQueuePolicyError(
                "heartbeat_interval_seconds must be less than orphan_after_seconds"
            )

    def run_deadline_at(self, accepted_at: datetime) -> datetime:
        """Derive the absolute run cutoff from an aware acceptance clock."""

        _require_aware(accepted_at, "accepted_at")
        total_seconds = self.max_queue_wait_seconds + self.hard_timeout_seconds
        return accepted_at + timedelta(seconds=total_seconds)

    def cancel_deadline_at(self, cancel_requested_at: datetime) -> datetime:
        """Derive the cooperative-cancel cutoff from an aware request clock."""

        _require_aware(cancel_requested_at, "cancel_requested_at")
        return cancel_requested_at + timedelta(seconds=self.cancel_grace_seconds)

    def orphan_deadline_at(self, heartbeat_at: datetime) -> datetime:
        """Derive the stale-worker cutoff from the last aware heartbeat."""

        _require_aware(heartbeat_at, "heartbeat_at")
        return heartbeat_at + timedelta(seconds=self.orphan_after_seconds)


@dataclass(frozen=True, slots=True)
class TerminalRuntimeFeatureFlags:
    """Explicit migration flags with fail-closed legacy inline semantics.

    ``legacy_inline_fallback_enabled`` is represented by
    :class:`TerminalFallbackMode`; there is no implicit fallback from a
    failed queue to inline execution.  The inline safety cap and timeout are
    hard upper bounds for the migration path, not a production capacity claim.
    """

    queued_intake_enabled: bool
    queued_worker_enabled: bool
    legacy_inline_enabled: bool
    fallback_mode: TerminalFallbackMode
    emergency_stop: bool
    legacy_inline_concurrency: int
    legacy_inline_timeout_seconds: int

    def __post_init__(self) -> None:
        """Validate feature combinations and the non-bypassable inline guard."""

        for field_name in (
            "queued_intake_enabled",
            "queued_worker_enabled",
            "legacy_inline_enabled",
            "emergency_stop",
        ):
            _require_bool(getattr(self, field_name), field_name)
        if not isinstance(self.fallback_mode, TerminalFallbackMode):
            raise TerminalRuntimeQueuePolicyError("fallback_mode must be TerminalFallbackMode")
        if self.legacy_inline_concurrency != LEGACY_INLINE_CONCURRENCY_CAP:
            raise TerminalRuntimeQueuePolicyError(
                "legacy_inline_concurrency must remain capped at 1"
            )
        _require_positive_int(
            self.legacy_inline_timeout_seconds,
            "legacy_inline_timeout_seconds",
        )
        if self.legacy_inline_timeout_seconds > LEGACY_INLINE_TIMEOUT_CAP_SECONDS:
            raise TerminalRuntimeQueuePolicyError(
                "legacy_inline_timeout_seconds cannot exceed 60 seconds"
            )
        if self.queued_intake_enabled and not self.queued_worker_enabled:
            raise TerminalRuntimeQueuePolicyError(
                "queued intake cannot be enabled while queued worker is disabled"
            )
        if (
            self.fallback_mode is TerminalFallbackMode.RESTRICTED_INLINE
            and not self.legacy_inline_enabled
        ):
            raise TerminalRuntimeQueuePolicyError(
                "restricted inline fallback requires legacy inline to be enabled"
            )
        if self.emergency_stop and (self.queued_intake_enabled or self.legacy_inline_enabled):
            raise TerminalRuntimeQueuePolicyError(
                "emergency stop cannot leave a server submission mode enabled"
            )

    def resolve_mode(
        self,
        requested_mode: TerminalRuntimeMode,
        *,
        worker_ready: bool,
    ) -> tuple[TerminalRuntimeMode | None, TerminalAdmissionReason]:
        """Resolve a requested mode without silently bypassing safety flags.

        The return value is only a pure decision.  It does not create a run,
        dispatch a message, or invoke the legacy Agent service.
        """

        if not isinstance(requested_mode, TerminalRuntimeMode):
            raise TerminalRuntimeQueuePolicyError("requested_mode must be TerminalRuntimeMode")
        _require_bool(worker_ready, "worker_ready")

        if requested_mode is TerminalRuntimeMode.LOCAL_CLI:
            return requested_mode, TerminalAdmissionReason.ACCEPTED_LOCAL_CLI
        if self.emergency_stop:
            return None, TerminalAdmissionReason.SUBMISSIONS_PAUSED
        if requested_mode is TerminalRuntimeMode.LEGACY_INLINE:
            if self.legacy_inline_enabled:
                return requested_mode, TerminalAdmissionReason.ACCEPTED_RESTRICTED_INLINE
            return None, TerminalAdmissionReason.LEGACY_INLINE_DISABLED
        if self.queued_intake_enabled and self.queued_worker_enabled and worker_ready:
            return requested_mode, TerminalAdmissionReason.ACCEPTED_QUEUED
        if (
            self.fallback_mode is TerminalFallbackMode.RESTRICTED_INLINE
            and self.legacy_inline_enabled
        ):
            return (
                TerminalRuntimeMode.LEGACY_INLINE,
                TerminalAdmissionReason.ACCEPTED_RESTRICTED_INLINE,
            )
        return None, TerminalAdmissionReason.QUEUED_UNAVAILABLE


@dataclass(frozen=True, slots=True)
class TerminalRuntimeQueuePolicy:
    """Complete config-only policy for the future TAR-02/TAR-03 composition root."""

    worker_limits: TerminalWorkerQueueLimits
    admission_limits: TerminalAdmissionLimits
    deadlines: TerminalRunDeadlines
    feature_flags: TerminalRuntimeFeatureFlags

    def __post_init__(self) -> None:
        """Ensure queue and worker bounds can honor admission limits."""

        if self.worker_limits.queue_max_depth < self.admission_limits.global_queued:
            raise TerminalRuntimeQueuePolicyError("queue_max_depth cannot be below global_queued")
        if self.worker_limits.worker_concurrency < self.admission_limits.global_active:
            raise TerminalRuntimeQueuePolicyError(
                "worker_concurrency cannot be below global_active"
            )
