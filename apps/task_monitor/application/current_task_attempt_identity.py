"""Resolve the verified Celery and Task Monitor identity for the active attempt."""

from __future__ import annotations

from dataclasses import dataclass

from celery import current_task

from apps.task_monitor.application.repository_provider import get_task_record_repository
from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskStatus
from core.exceptions import DataFetchError

_TASK_ID_MAX_LENGTH = 255
_ATTEMPT_ID_MAX_LENGTH = 160
_CANONICAL_TOKEN_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:/-"
)


class CurrentTaskAttemptIdentityUnavailable(DataFetchError):
    """Raised when the active Celery request is not bound to its monitor attempt."""

    default_message = "当前 Celery task attempt identity is unavailable"
    default_code = "CURRENT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE"


def _validate_identity_token(value: object, *, field_name: str, maximum: int) -> str:
    """Validate one bounded ASCII token used as an attempt identity."""

    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or not value.isascii()
        or any(character not in _CANONICAL_TOKEN_CHARACTERS for character in value)
    ):
        raise CurrentTaskAttemptIdentityUnavailable(
            f"{field_name} is missing or is not a bounded canonical token"
        )
    return value


@dataclass(frozen=True, slots=True)
class CurrentTaskAttemptIdentity:
    """Canonical identity pair for one active Celery and Task Monitor attempt."""

    task_id: str
    attempt_id: str

    def __post_init__(self) -> None:
        """Reject malformed task or monitor-attempt tokens at construction time."""

        _validate_identity_token(
            self.task_id,
            field_name="task_id",
            maximum=_TASK_ID_MAX_LENGTH,
        )
        _validate_identity_token(
            self.attempt_id,
            field_name="attempt_id",
            maximum=_ATTEMPT_ID_MAX_LENGTH,
        )


def get_current_task_attempt_identity() -> CurrentTaskAttemptIdentity:
    """Return the active task identity only when its monitor record is STARTED.

    The function never manufactures an identity. A missing Celery request, absent
    monitor marker, repository failure, or stale/retried/duplicate monitor record
    is reported with one stable error code so callers can fail closed.
    """

    try:
        request = getattr(current_task, "request", None)
        if request is None:
            raise CurrentTaskAttemptIdentityUnavailable("current Celery request is unavailable")
        identity = CurrentTaskAttemptIdentity(
            task_id=_validate_identity_token(
                getattr(request, "id", None),
                field_name="task_id",
                maximum=_TASK_ID_MAX_LENGTH,
            ),
            attempt_id=_validate_identity_token(
                getattr(request, "_task_monitor_attempt_id", None),
                field_name="attempt_id",
                maximum=_ATTEMPT_ID_MAX_LENGTH,
            ),
        )
        record = get_task_record_repository().get_by_task_id(identity.task_id)
    except CurrentTaskAttemptIdentityUnavailable:
        raise
    except Exception as error:
        raise CurrentTaskAttemptIdentityUnavailable(
            "Task Monitor could not verify the current task attempt"
        ) from error

    if (
        not isinstance(record, TaskExecutionRecord)
        or record.task_id != identity.task_id
        or record.status is not TaskStatus.STARTED
        or record.attempt_id != identity.attempt_id
    ):
        raise CurrentTaskAttemptIdentityUnavailable(
            "Celery request does not match the active Task Monitor attempt"
        )
    return identity


__all__ = [
    "CurrentTaskAttemptIdentity",
    "CurrentTaskAttemptIdentityUnavailable",
    "get_current_task_attempt_identity",
]
