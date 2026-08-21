"""Pure contracts for the future queued Terminal Agent runtime.

The module is intentionally independent of Django, Celery, the Agents SDK,
and network clients. It freezes the TAR-01 boundary only: identity and
ownership are explicit, dispatch transitions are finite, and broker payloads
carry identifiers rather than prompts, credentials, or tool arguments.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final


class TerminalRunContractError(ValueError):
    """Raised when a queued Terminal Agent contract is malformed."""


class TerminalSensitiveDataError(TerminalRunContractError):
    """Raised when a runtime or broker payload contains restricted data."""


class TerminalOwnershipError(TerminalRunContractError):
    """Raised when a run is accessed by a different actor."""


class InvalidTerminalRunTransition(TerminalRunContractError):
    """Raised when a dispatch state transition is not in the frozen graph."""

    def __init__(
        self,
        current: TerminalRunStatus,
        requested: TerminalRunStatus,
        allowed: tuple[TerminalRunStatus, ...],
    ) -> None:
        self.current = current
        self.requested = requested
        self.allowed = allowed
        allowed_text = ", ".join(item.value for item in allowed) or "none"
        super().__init__(
            f"invalid Terminal Agent run transition from {current.value} "
            f"to {requested.value}; allowed targets: {allowed_text}"
        )


# Compatibility name for callers that used the earlier draft terminology.
TerminalRunTransitionError = InvalidTerminalRunTransition


class TerminalRuntimeMode(StrEnum):
    """Execution location selected by the eventual application boundary."""

    WEB_QUEUED = "web_queued"
    LOCAL_CLI = "local_cli"
    LEGACY_INLINE = "legacy_inline"


class TerminalRunStatus(StrEnum):
    """Durable dispatch states for a Terminal Agent run."""

    ACCEPTED = "accepted"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ORPHANED = "orphaned"


_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^run-[A-Za-z0-9][A-Za-z0-9_-]{3,127}$")
_CLIENT_REQUEST_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^request-[A-Za-z0-9][A-Za-z0-9_-]{2,127}$"
)
_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


def validate_terminal_run_id(run_id: str) -> str:
    """Validate and return the canonical public run identifier."""

    return _require_identifier(run_id, "run_id", _RUN_ID_RE)


def _require_positive_int(value: object, field_name: str) -> int:
    """Require a positive integer while rejecting bool-as-int values."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TerminalRunContractError(f"{field_name} must be a positive integer")
    return value


def _require_identifier(
    value: object,
    field_name: str,
    pattern: re.Pattern[str] | None = None,
) -> str:
    """Require a non-empty canonical identifier."""

    if not isinstance(value, str) or not value or value.strip() != value:
        raise TerminalRunContractError(f"{field_name} must be a canonical string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise TerminalRunContractError(f"{field_name} has an invalid format")
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware datetime."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise TerminalRunContractError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class TerminalRunSelector:
    """Stable owner-scoped selectors supplied by an authenticated caller."""

    run_id: str
    task_id: int
    actor_user_id: int
    client_request_id: str

    def __post_init__(self) -> None:
        """Validate all identity and ownership selectors."""

        _require_identifier(self.run_id, "run_id", _RUN_ID_RE)
        _require_positive_int(self.task_id, "task_id")
        _require_positive_int(self.actor_user_id, "actor_user_id")
        _require_identifier(
            self.client_request_id,
            "client_request_id",
            _CLIENT_REQUEST_ID_RE,
        )


@dataclass(frozen=True, slots=True)
class TerminalRunSubmission:
    """Immutable request accepted before durable admission exists."""

    selector: TerminalRunSelector
    runtime_mode: TerminalRuntimeMode
    request_digest: str
    accepted_at: datetime
    deadline_at: datetime

    def __post_init__(self) -> None:
        """Validate digest, mode, and monotonic aware clocks."""

        if not isinstance(self.runtime_mode, TerminalRuntimeMode):
            raise TerminalRunContractError("runtime_mode must be TerminalRuntimeMode")
        if (
            not isinstance(self.request_digest, str)
            or _DIGEST_RE.fullmatch(self.request_digest) is None
        ):
            raise TerminalRunContractError("request_digest must be lowercase SHA-256")
        accepted_at = _require_aware(self.accepted_at, "accepted_at")
        deadline_at = _require_aware(self.deadline_at, "deadline_at")
        if deadline_at <= accepted_at:
            raise TerminalRunContractError("deadline_at must be after accepted_at")


@dataclass(frozen=True, slots=True)
class TerminalAgentBrokerEnvelope:
    """The only payload shape allowed to cross a future broker boundary."""

    run_id: str
    task_id: int

    def __post_init__(self) -> None:
        """Validate broker identifiers."""

        _require_identifier(self.run_id, "run_id", _RUN_ID_RE)
        _require_positive_int(self.task_id, "task_id")

    def to_payload(self) -> dict[str, int | str]:
        """Return an ID-only mapping; prompts and credentials are impossible."""

        payload: dict[str, int | str] = {
            "run_id": self.run_id,
            "task_id": self.task_id,
        }
        assert_no_sensitive_runtime_data(payload)
        return payload


def _is_sensitive_key(key: object) -> bool:
    """Return whether a mapping key names restricted user or secret content."""

    if not isinstance(key, str):
        return False
    normalized = key.casefold().replace("-", "_").replace(".", "_")
    sensitive_parts = (
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "private_key",
        "prompt",
        "secret",
        "token",
    )
    return any(part in normalized for part in sensitive_parts)


def _assert_safe_value(value: object, path: str) -> None:
    """Recursively reject restricted fields in JSON-like payloads."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if isinstance(key, str) else f"{path}.<key>"
            if _is_sensitive_key(key):
                raise TerminalSensitiveDataError(f"sensitive field is not allowed at {child_path}")
            _assert_safe_value(child, child_path)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _assert_safe_value(child, f"{path}[{index}]")


def assert_no_sensitive_runtime_data(payload: Mapping[str, object]) -> None:
    """Reject prompt, credential, and token fields before transport."""

    _assert_safe_value(payload, "$")


def validate_broker_payload(
    payload: Mapping[str, object],
) -> TerminalAgentBrokerEnvelope:
    """Decode and strictly validate an ID-only broker payload."""

    assert_no_sensitive_runtime_data(payload)
    if set(payload) != {"run_id", "task_id"}:
        raise TerminalRunContractError("broker payload must contain exactly run_id and task_id")
    run_id = payload["run_id"]
    task_id = payload["task_id"]
    if not isinstance(run_id, str):
        raise TerminalRunContractError("broker payload run_id must be a string")
    task_id = _require_positive_int(task_id, "broker payload task_id")
    return TerminalAgentBrokerEnvelope(run_id=run_id, task_id=task_id)


_ALLOWED_TRANSITIONS: Final[dict[TerminalRunStatus, tuple[TerminalRunStatus, ...]]] = {
    TerminalRunStatus.ACCEPTED: (TerminalRunStatus.QUEUED,),
    TerminalRunStatus.QUEUED: (
        TerminalRunStatus.CLAIMED,
        TerminalRunStatus.CANCEL_REQUESTED,
    ),
    TerminalRunStatus.CLAIMED: (
        TerminalRunStatus.RUNNING,
        TerminalRunStatus.CANCEL_REQUESTED,
        TerminalRunStatus.COMPLETED,
        TerminalRunStatus.FAILED,
        TerminalRunStatus.TIMED_OUT,
        TerminalRunStatus.ORPHANED,
    ),
    TerminalRunStatus.RUNNING: (
        TerminalRunStatus.WAITING_APPROVAL,
        TerminalRunStatus.CANCEL_REQUESTED,
        TerminalRunStatus.COMPLETED,
        TerminalRunStatus.FAILED,
        TerminalRunStatus.TIMED_OUT,
        TerminalRunStatus.ORPHANED,
    ),
    TerminalRunStatus.WAITING_APPROVAL: (
        TerminalRunStatus.QUEUED,
        TerminalRunStatus.CANCEL_REQUESTED,
    ),
    TerminalRunStatus.CANCEL_REQUESTED: (TerminalRunStatus.CANCELLED,),
    TerminalRunStatus.ORPHANED: (
        TerminalRunStatus.QUEUED,
        TerminalRunStatus.FAILED,
    ),
}


def _coerce_status(value: TerminalRunStatus | str) -> TerminalRunStatus:
    """Normalize a status value or fail closed."""

    if isinstance(value, TerminalRunStatus):
        return value
    try:
        return TerminalRunStatus(value)
    except ValueError as exc:
        raise TerminalRunContractError(f"unknown Terminal Agent status: {value!r}") from exc


def transition_terminal_run(
    current: TerminalRunStatus | str,
    requested: TerminalRunStatus | str,
) -> TerminalRunStatus:
    """Validate and return a requested state transition.

    Re-delivery of an already applied state is idempotent. No other skipped
    edge or transition out of a terminal state is accepted.
    """

    current_status = _coerce_status(current)
    requested_status = _coerce_status(requested)
    if current_status is requested_status:
        return requested_status
    allowed = _ALLOWED_TRANSITIONS.get(current_status, ())
    if requested_status not in allowed:
        raise InvalidTerminalRunTransition(current_status, requested_status, allowed)
    return requested_status


def is_terminal_run_status(status: TerminalRunStatus | str) -> bool:
    """Return whether a run status is final and cannot be transitioned."""

    return _coerce_status(status) in {
        TerminalRunStatus.CANCELLED,
        TerminalRunStatus.COMPLETED,
        TerminalRunStatus.FAILED,
        TerminalRunStatus.TIMED_OUT,
    }


# Compatibility spelling from the first draft; keep it pure and deprecated.
is_terminal_terminal_run_status = is_terminal_run_status


@dataclass(frozen=True, slots=True)
class TerminalAgentRunContract:
    """Owner-scoped run identity used by a future application port."""

    submission: TerminalRunSubmission
    dispatch_status: TerminalRunStatus = TerminalRunStatus.ACCEPTED
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    cancel_requested_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate lifecycle timestamps returned by a durable adapter."""

        if not isinstance(self.dispatch_status, TerminalRunStatus):
            raise TerminalRunContractError("dispatch_status must be TerminalRunStatus")
        for field_name in ("claimed_at", "heartbeat_at", "cancel_requested_at"):
            value = getattr(self, field_name)
            if value is not None:
                _require_aware(value, field_name)

    def is_owned_by(self, actor_user_id: int) -> bool:
        """Return whether the supplied actor owns this run."""

        return actor_user_id == self.submission.selector.actor_user_id

    def require_owner(self, actor_user_id: int) -> None:
        """Fail closed when a caller is not the run owner."""

        if not self.is_owned_by(actor_user_id):
            raise TerminalOwnershipError("Terminal Agent run is not owned by this actor")

    def is_expired(self, now: datetime) -> bool:
        """Return whether the run deadline has passed."""

        _require_aware(now, "now")
        return now >= self.submission.deadline_at

    def broker_payload(self) -> dict[str, int | str]:
        """Return the ID-only broker envelope for this run."""

        selector = self.submission.selector
        return TerminalAgentBrokerEnvelope(selector.run_id, selector.task_id).to_payload()

    def transition(self, target: TerminalRunStatus) -> TerminalAgentRunContract:
        """Return a new run contract after validating the state edge."""

        transition_terminal_run(self.dispatch_status, target)
        return replace(self, dispatch_status=target)
