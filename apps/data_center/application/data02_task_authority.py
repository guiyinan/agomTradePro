"""Shared audit-authority checks for DATA-02 Celery tasks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from time import sleep

from core.integration import data_center_audit as audit_integration
from shared.domain.task_outcomes import TaskBusinessOutcome

_FINALIZATION_WINDOW = timedelta(seconds=300)
_TRANSIENT_AUTHORITY_REASONS = frozenset({"system_audit_authority_unavailable"})
_DEFAULT_PREFLIGHT_ATTEMPTS = 6
_DEFAULT_REVALIDATION_ATTEMPTS = 6
_DEFAULT_REVALIDATION_DELAY_SECONDS = 1.0
_MAX_REVALIDATION_DELAY_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class Data02AuthorityRevalidation:
    """Describe one bounded authority revalidation result."""

    current: bool
    reason_code: str
    attempts: int


@dataclass(slots=True)
class Data02AuthorityLatch:
    """Keep one long-running task closed after a failed authority revalidation."""

    authority: audit_integration.SystemAuditReaderContext
    current: bool = True
    reason_code: str = "authority_current"

    def allows_next_write(self, *, as_of: datetime) -> bool:
        """Revalidate one write boundary and latch the first failed result."""

        if self.current:
            result = revalidate_data02_task_authority(self.authority, as_of=as_of)
            self.current = result.current
            self.reason_code = result.reason_code
        return self.current


def data02_authority_failure(reason: str) -> dict[str, object]:
    """Return a stable zero-write authority denial for DATA-02 tasks."""

    return {
        "success": False,
        "outcome": TaskBusinessOutcome.BLOCKED.value,
        "stage": "authority",
        "blocked_reason": reason,
        "must_not_use_for_decision": True,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "published": 0,
        "checkpoint": {
            "offset": 0,
            "next_offset": 0,
            "total_assets": 0,
            "complete": False,
        },
    }


def preflight_data02_task_authority(
    *,
    as_of: datetime,
    minimum_window: timedelta,
    expected_actor: str = "",
    max_attempts: int = _DEFAULT_PREFLIGHT_ATTEMPTS,
    retry_delay_seconds: float = _DEFAULT_REVALIDATION_DELAY_SECONDS,
    sleeper: Callable[[float], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[audit_integration.SystemAuditReaderContext | None, dict[str, object] | None]:
    """Resolve current authority with bounded retries for transient read contention."""

    retry_sleeper = sleep if sleeper is None else sleeper
    _validate_retry_controls(
        as_of=as_of,
        minimum_window=minimum_window,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        sleeper=retry_sleeper,
        clock=clock,
        attempts_limit=_DEFAULT_PREFLIGHT_ATTEMPTS,
    )
    current_as_of = as_of
    for attempt in range(1, max_attempts + 1):
        context, failure = _read_data02_authority_once(
            as_of=current_as_of,
            minimum_window=minimum_window,
            expected_actor=expected_actor,
        )
        if failure is not None or context is None:
            reason_code = str(
                (failure or {}).get("blocked_reason") or "authority_changed_or_expired"
            )
            if reason_code in _TRANSIENT_AUTHORITY_REASONS and attempt < max_attempts:
                current_as_of = _wait_for_authority_retry(
                    attempt=attempt,
                    retry_delay_seconds=retry_delay_seconds,
                    sleeper=retry_sleeper,
                    clock=clock,
                )
                continue
            return None, failure or data02_authority_failure(reason_code)
        return context, None
    raise RuntimeError("authority preflight attempt accounting is invalid")


def same_data02_task_authority_is_current(
    authority: audit_integration.SystemAuditReaderContext,
    *,
    as_of: datetime,
    minimum_window: timedelta = _FINALIZATION_WINDOW,
) -> bool:
    """Allow an equivalent active successor while the starting grant remains valid."""

    return revalidate_data02_task_authority(
        authority,
        as_of=as_of,
        minimum_window=minimum_window,
    ).current


def revalidate_data02_task_authority(
    authority: audit_integration.SystemAuditReaderContext,
    *,
    as_of: datetime,
    minimum_window: timedelta = _FINALIZATION_WINDOW,
    max_attempts: int = _DEFAULT_REVALIDATION_ATTEMPTS,
    retry_delay_seconds: float = _DEFAULT_REVALIDATION_DELAY_SECONDS,
    sleeper: Callable[[float], None] = sleep,
    clock: Callable[[], datetime] | None = None,
) -> Data02AuthorityRevalidation:
    """Revalidate authority, retrying only bounded transient read unavailability."""

    _validate_retry_controls(
        as_of=as_of,
        minimum_window=minimum_window,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        sleeper=sleeper,
        clock=clock,
        attempts_limit=_DEFAULT_REVALIDATION_ATTEMPTS,
    )

    current_as_of = as_of
    for attempt in range(1, max_attempts + 1):
        current, failure = _read_data02_authority_once(
            as_of=current_as_of,
            minimum_window=minimum_window,
            expected_actor=authority.actor_id,
        )
        if failure is not None or current is None:
            reason_code = str(
                (failure or {}).get("blocked_reason") or "authority_changed_or_expired"
            )
            if reason_code in _TRANSIENT_AUTHORITY_REASONS and attempt < max_attempts:
                current_as_of = _wait_for_authority_retry(
                    attempt=attempt,
                    retry_delay_seconds=retry_delay_seconds,
                    sleeper=sleeper,
                    clock=clock,
                )
                continue
            return Data02AuthorityRevalidation(False, reason_code, attempt)
        if authority.authority_valid_until <= current_as_of + minimum_window:
            return Data02AuthorityRevalidation(False, "authority_window_too_short", attempt)
        identity_fields = (
            "authority_source_id",
            "actor_id",
            "user_id",
            "tenant_id",
            "owner_id",
            "is_authenticated",
            "is_staff",
            "role",
        )
        if not all(
            getattr(current, field) == getattr(authority, field) for field in identity_fields
        ):
            return Data02AuthorityRevalidation(False, "authority_identity_changed", attempt)
        return Data02AuthorityRevalidation(True, "authority_current", attempt)
    raise RuntimeError("authority revalidation attempt accounting is invalid")


def _read_data02_authority_once(
    *,
    as_of: datetime,
    minimum_window: timedelta,
    expected_actor: str,
) -> tuple[audit_integration.SystemAuditReaderContext | None, dict[str, object] | None]:
    """Read one authority snapshot and apply non-retriable identity and expiry gates."""

    try:
        context = audit_integration.preflight_data_reliability_audit_runtime(
            environment="production",
            using="default",
            as_of=as_of,
        )
    except audit_integration.SystemAuditCompositionUnavailable as exc:
        return None, data02_authority_failure(f"system_audit_{exc.reason_code}")
    if expected_actor and expected_actor != context.actor_id:
        return None, data02_authority_failure("operator_actor_mismatch")
    if context.authority_valid_until <= as_of + minimum_window:
        return None, data02_authority_failure("authority_window_too_short")
    return context, None


def _validate_retry_controls(
    *,
    as_of: datetime,
    minimum_window: timedelta,
    max_attempts: int,
    retry_delay_seconds: float,
    sleeper: Callable[[float], None],
    clock: Callable[[], datetime] | None,
    attempts_limit: int,
) -> None:
    """Validate one bounded authority retry policy before its first read."""

    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= attempts_limit
    ):
        raise ValueError(f"max_attempts must be between 1 and {attempts_limit}")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if type(minimum_window) is not timedelta or minimum_window <= timedelta(0):
        raise ValueError("minimum_window must be a positive timedelta")
    if (
        isinstance(retry_delay_seconds, bool)
        or not isinstance(retry_delay_seconds, (int, float))
        or not isfinite(float(retry_delay_seconds))
        or retry_delay_seconds < 0
    ):
        raise ValueError("retry_delay_seconds must be a non-negative number")
    if not callable(sleeper):
        raise TypeError("sleeper must be callable")
    if clock is not None and not callable(clock):
        raise TypeError("clock must be callable")


def _wait_for_authority_retry(
    *,
    attempt: int,
    retry_delay_seconds: float,
    sleeper: Callable[[float], None],
    clock: Callable[[], datetime] | None,
) -> datetime:
    """Wait within the governed bound and return a fresh aware UTC cutoff."""

    delay_seconds = min(
        float(retry_delay_seconds) * attempt,
        _MAX_REVALIDATION_DELAY_SECONDS,
    )
    sleeper(delay_seconds)
    current_as_of = clock() if clock is not None else datetime.now(UTC)
    if current_as_of.tzinfo is None or current_as_of.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return current_as_of
