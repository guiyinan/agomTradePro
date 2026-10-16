"""Read-only integrity verification for an exact published calendar Audit pair.

This use case is an internal integrity primitive for an already authorized
Data Center calendar read. It is not an Audit browsing API and grants no read
or publication authority.
"""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from apps.audit.application.calendar_publication_audit import (
    CalendarPublicationAuditCorruption,
    CalendarPublicationAuditUnavailable,
    CalendarPublicationAuditValidationError,
    CalendarPublicationPublishedObservation,
)
from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxConflict,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.calendar_publication_audit import (
    CALENDAR_PUBLICATION_PUBLISHED_EVENT,
    CalendarPublicationAuditContractError,
    CalendarPublicationPublishedDetail,
    calendar_publication_event_identity,
    calendar_publication_stream_id,
    validate_calendar_publication_event,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTOR_RE = re.compile(r"^django-user:([1-9][0-9]{0,18})$")


@dataclass(frozen=True, slots=True)
class CalendarPublicationAuditIntegrityReceipt:
    """Minimal verified identity for a stored calendar event/outbox pair."""

    database_alias: str
    dataset_key: str
    exchange: str
    publication_id: str
    publication_hash: str
    event_id: str
    event_content_hash: str
    actor_user_id: int
    outbox_id: UUID
    idempotency_key: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Reject partial or malformed pair identities before crossing apps."""

        for field_name in (
            "database_alias",
            "dataset_key",
            "exchange",
            "event_id",
            "idempotency_key",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value or value.strip() != value:
                raise CalendarPublicationAuditCorruption(
                    f"calendar integrity receipt {field_name} is invalid"
                )
        for field_name in ("publication_id",):
            value = getattr(self, field_name)
            try:
                parsed = UUID(value) if type(value) is str else None
            except (TypeError, ValueError) as error:
                raise CalendarPublicationAuditCorruption(
                    f"calendar integrity receipt {field_name} is invalid"
                ) from error
            if parsed is None or str(parsed) != value:
                raise CalendarPublicationAuditCorruption(
                    f"calendar integrity receipt {field_name} is invalid"
                )
        for field_name in ("publication_hash", "event_content_hash"):
            value = getattr(self, field_name)
            if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
                raise CalendarPublicationAuditCorruption(
                    f"calendar integrity receipt {field_name} is invalid"
                )
        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise CalendarPublicationAuditCorruption(
                "calendar integrity receipt actor_user_id is invalid"
            )
        if type(self.outbox_id) is not UUID:
            raise CalendarPublicationAuditCorruption(
                "calendar integrity receipt outbox_id is invalid"
            )
        if self.idempotency_key != self.event_id:
            raise CalendarPublicationAuditCorruption(
                "calendar integrity receipt event/outbox identity differs"
            )
        if (
            not isinstance(self.recorded_at, datetime)
            or self.recorded_at.tzinfo is None
            or self.recorded_at.utcoffset() != timedelta(0)
        ):
            raise CalendarPublicationAuditCorruption(
                "calendar integrity receipt recorded_at must be UTC"
            )


class CalendarPublicationAuditIntegrityReader(Protocol):
    """Exact selector for one calendar publication event and its exact outbox."""

    @property
    def database_alias(self) -> str:
        """Return the alias used by the caller-owned publication transaction."""

    def caller_owned_atomic(self) -> AbstractContextManager[None]:
        """Join, but never create or commit, the caller's single outer transaction."""

    def lock_stream(self, stream_id: str) -> None:
        """Lock the one deterministic publication stream during exact verification."""

    def get_calendar_publication_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Read the one event identity if it was recorded by the cutoff."""

    def get_exact_outbox_winner_targeted(
        self,
        event: SystemAuditEvent,
    ) -> ExactSystemAuditOutboxWinner | None:
        """Read only the outbox row paired with the exact supplied event."""


class VerifyPublishedCalendarPublicationIntegrityUseCase:
    """Verify one stored publication pair without issuing an Audit permission."""

    __slots__ = ("_reader",)

    def __init__(self, reader: CalendarPublicationAuditIntegrityReader) -> None:
        """Bind the verifier to an exact event/outbox reader port."""

        self._reader = reader

    def execute(
        self,
        observation: CalendarPublicationPublishedObservation,
        *,
        as_of: datetime,
    ) -> CalendarPublicationAuditIntegrityReceipt:
        """Return a minimal receipt after exact no-write event/outbox verification."""

        observation = _validate_observation(observation)
        _require_utc(as_of, "as_of")
        if observation.recorded_at > as_of:
            raise CalendarPublicationAuditValidationError(
                "integrity cutoff precedes the publication event time",
                code="CALENDAR_AUDIT_INTEGRITY_CUTOFF_INVALID",
            )
        alias = self._reader.database_alias
        if type(alias) is not str or not alias or alias.strip() != alias:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication integrity reader has no exact database alias"
            )
        detail = observation.detail
        try:
            event_id, _ = calendar_publication_event_identity(
                event_kind="published",
                dataset_key=detail.dataset_key,
                exchange=detail.exchange,
                request_identity=detail.publication_id,
            )
            stream_id = calendar_publication_stream_id(detail.dataset_key, detail.exchange)
            with self._reader.caller_owned_atomic():
                self._reader.lock_stream(stream_id)
                event = self._reader.get_calendar_publication_winner_targeted(
                    event_id=event_id,
                    event_version="1",
                    dataset_key=detail.dataset_key,
                    exchange=detail.exchange,
                    as_of=as_of,
                )
                if event is None:
                    raise CalendarPublicationAuditCorruption(
                        "published calendar integrity check found no exact event"
                    )
                _validate_event(event, observation=observation, event_id=event_id, as_of=as_of)
                outbox = self._reader.get_exact_outbox_winner_targeted(event)
                outbox = _validate_outbox(outbox, event)
                actor_match = _ACTOR_RE.fullmatch(event.actor.actor_id)
                if actor_match is None:
                    raise CalendarPublicationAuditCorruption(
                        "published calendar event has no authenticated user actor"
                    )
                return CalendarPublicationAuditIntegrityReceipt(
                    database_alias=alias,
                    dataset_key=detail.dataset_key,
                    exchange=detail.exchange,
                    publication_id=detail.publication_id,
                    publication_hash=detail.publication_hash,
                    event_id=event.event_id,
                    event_content_hash=event.content_hash,
                    actor_user_id=int(actor_match.group(1)),
                    outbox_id=outbox.outbox_id,
                    idempotency_key=outbox.idempotency_key,
                    recorded_at=event.recorded_at,
                )
        except (
            CalendarPublicationAuditCorruption,
            CalendarPublicationAuditValidationError,
        ):
            raise
        except SystemAuditEventOutboxConflict as error:
            raise CalendarPublicationAuditCorruption(
                "calendar publication integrity selector conflicted"
            ) from error
        except SystemAuditEventOutboxCorruption as error:
            raise CalendarPublicationAuditCorruption(
                "calendar publication integrity evidence is corrupt"
            ) from error
        except SystemAuditEventOutboxUnavailable as error:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication integrity reader is unavailable"
            ) from error
        except Exception as error:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication integrity reader is unavailable"
            ) from error


def _validate_observation(
    value: object,
) -> CalendarPublicationPublishedObservation:
    """Revalidate the caller's exact typed publication expectation."""

    if type(value) is not CalendarPublicationPublishedObservation:
        raise CalendarPublicationAuditValidationError("published integrity observation is invalid")
    try:
        CalendarPublicationPublishedObservation.__post_init__(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise CalendarPublicationAuditValidationError(
            "published integrity observation violates its typed contract"
        ) from error
    return value


def _validate_event(
    event: SystemAuditEvent,
    *,
    observation: CalendarPublicationPublishedObservation,
    event_id: str,
    as_of: datetime,
) -> None:
    """Require exact family, selector, recorded time, and source detail."""

    if type(event) is not SystemAuditEvent:
        raise CalendarPublicationAuditCorruption(
            "calendar publication selector returned an invalid event"
        )
    try:
        validate_calendar_publication_event(event)
        parsed_detail = CalendarPublicationPublishedDetail.from_payload(event.detail)
    except (AttributeError, TypeError, ValueError, CalendarPublicationAuditContractError) as error:
        raise CalendarPublicationAuditCorruption(
            "calendar publication event violates its closed contract"
        ) from error
    if (
        event.event_type != CALENDAR_PUBLICATION_PUBLISHED_EVENT
        or event.event_id != event_id
        or event.idempotency_key != event_id
        or event.dataset_key != observation.detail.dataset_key
        or event.stream_id
        != calendar_publication_stream_id(
            observation.detail.dataset_key, observation.detail.exchange
        )
        or event.scope is not None
        or event.recorded_at != observation.recorded_at
        or event.recorded_at > as_of
        or event.actor.actor_type != "django_user"
        or parsed_detail != observation.detail
    ):
        raise CalendarPublicationAuditCorruption(
            "calendar publication event differs from the exact current record"
        )


def _validate_outbox(
    outbox: ExactSystemAuditOutboxWinner | None,
    event: SystemAuditEvent,
) -> ExactSystemAuditOutboxWinner:
    """Revalidate the exact event/outbox payload and identity pair."""

    if type(outbox) is not ExactSystemAuditOutboxWinner:
        raise CalendarPublicationAuditCorruption(
            "calendar publication event has no exact outbox row"
        )
    try:
        ExactSystemAuditOutboxWinner.__post_init__(outbox)
    except (AttributeError, TypeError, ValueError) as error:
        raise CalendarPublicationAuditCorruption(
            "calendar publication outbox row is malformed"
        ) from error
    if (
        outbox.event != event
        or outbox.event_id != event.event_id
        or outbox.idempotency_key != event.idempotency_key
        or outbox.payload_hash != event.content_hash
    ):
        raise CalendarPublicationAuditCorruption(
            "calendar publication outbox row does not pair with its event"
        )
    return outbox


def _require_utc(value: object, field_name: str) -> None:
    """Require an aware zero-offset instant without normalizing caller input."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise CalendarPublicationAuditValidationError(f"{field_name} must be an aware UTC instant")


__all__ = [
    "CalendarPublicationAuditIntegrityReader",
    "CalendarPublicationAuditIntegrityReceipt",
    "VerifyPublishedCalendarPublicationIntegrityUseCase",
]
