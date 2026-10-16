"""Read-only verification of an existing calendar publication Audit pair.

This application contract verifies a current publication retry under the
caller's live publication permission. It neither publishes nor repairs Audit
rows, and it deliberately does not import Data Center persistence contracts.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Protocol

from apps.audit.application.calendar_publication_audit import (
    CalendarAuditPublisherPrincipal,
    CalendarPublicationAuditConflict,
    CalendarPublicationAuditCorruption,
    CalendarPublicationAuditDenied,
    CalendarPublicationAuditUnavailable,
    CalendarPublicationAuditValidationError,
    CalendarPublicationPublishedObservation,
)
from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.calendar_publication_audit import (
    CALENDAR_PUBLICATION_PUBLISHED_EVENT,
    CALENDAR_PUBLISH_PERMISSION,
    CalendarPublicationAuditContractError,
    CalendarPublicationPublishedDetail,
    calendar_publication_event_identity,
    calendar_publication_stream_id,
    validate_calendar_publication_event,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from core.exceptions import AuthenticationError, AuthorizationError


class CalendarPublicationAuditReplayReader(Protocol):
    """Narrow read-only event/outbox port for a current calendar replay.

    Implementations must join an already-open, same-alias outer transaction;
    ``caller_owned_atomic`` must reject missing or nested transactions and must
    not open, commit, or roll back a transaction itself. The targeted event
    selector must lock only the deterministic identity winner, and the outbox
    selector must read only the exact row paired with the supplied event.
    """

    @property
    def database_alias(self) -> str:
        """Return the database alias holding the caller's outer transaction."""

        ...

    def caller_owned_atomic(self) -> AbstractContextManager[None]:
        """Join the caller's single outer transaction without owning its commit."""

        ...

    def lock_stream(self, stream_id: str) -> None:
        """Serialize the exact publication stream before the targeted read."""

        ...

    def get_calendar_publication_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Read one validated calendar event identity at the supplied cutoff."""

        ...

    def get_exact_outbox_winner_targeted(
        self,
        event: SystemAuditEvent,
    ) -> ExactSystemAuditOutboxWinner | None:
        """Read the complete outbox row paired with the exact supplied event."""

        ...


class VerifyCurrentCalendarPublicationAuditReplayUseCase:
    """Verify, without writing, a persisted published event and outbox pair.

    A replay is authorized by a live current ``publish_exchange_calendar``
    principal, but this first version allows only the original event actor to
    replay it. The historical event may precede the principal's current
    ``verified_at``; that timestamp is the read knowledge cutoff, not a
    replacement event time.
    """

    __slots__ = ("_reader",)

    def __init__(self, reader: CalendarPublicationAuditReplayReader) -> None:
        """Bind the verifier to an exact read-only event/outbox repository port."""

        self._reader = reader

    def execute(
        self,
        observation: CalendarPublicationPublishedObservation,
        *,
        principal: CalendarAuditPublisherPrincipal,
    ) -> SystemAuditEventOutboxCommit:
        """Return the unchanged persisted pair only after exact verification."""

        observation = _validated_observation(observation)
        try:
            principal.assert_live()
            actor_id, verified_at = _validate_principal(
                principal=principal,
                database_alias=self._reader.database_alias,
            )
            detail = observation.detail
            event_id, idempotency_key = calendar_publication_event_identity(
                event_kind="published",
                dataset_key=detail.dataset_key,
                exchange=detail.exchange,
                request_identity=detail.publication_id,
            )
            stream_id = calendar_publication_stream_id(detail.dataset_key, detail.exchange)

            with self._reader.caller_owned_atomic():
                principal.assert_live()
                self._reader.lock_stream(stream_id)
                winner = self._reader.get_calendar_publication_winner_targeted(
                    event_id=event_id,
                    event_version="1",
                    dataset_key=detail.dataset_key,
                    exchange=detail.exchange,
                    as_of=verified_at,
                )
                if winner is None:
                    raise CalendarPublicationAuditCorruption(
                        "current calendar publication has no persisted Audit event"
                    )
                _validate_event_winner(
                    winner=winner,
                    observation=observation,
                    actor_id=actor_id,
                    verified_at=verified_at,
                    event_id=event_id,
                    idempotency_key=idempotency_key,
                    stream_id=stream_id,
                )
                outbox = self._reader.get_exact_outbox_winner_targeted(winner)
                outbox = _validate_outbox_winner(outbox=outbox, event=winner)
                principal.assert_live()
                commit = SystemAuditEventOutboxCommit(
                    event=winner,
                    outbox_id=outbox.outbox_id,
                    event_id=winner.event_id,
                    idempotency_key=winner.idempotency_key,
                )
            principal.assert_live()
            return commit
        except (
            CalendarPublicationAuditConflict,
            CalendarPublicationAuditCorruption,
            CalendarPublicationAuditDenied,
            CalendarPublicationAuditUnavailable,
            CalendarPublicationAuditValidationError,
        ):
            raise
        except (AuthenticationError, AuthorizationError) as error:
            raise CalendarPublicationAuditDenied() from error
        except SystemAuditEventOutboxConflict as error:
            raise CalendarPublicationAuditConflict() from error
        except SystemAuditEventOutboxCorruption as error:
            raise CalendarPublicationAuditCorruption() from error
        except SystemAuditEventOutboxUnavailable as error:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication replay reader is unavailable"
            ) from error
        except Exception as error:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication replay verification failed"
            ) from error


def _validated_observation(
    value: object,
) -> CalendarPublicationPublishedObservation:
    """Revalidate the exact persisted-publication expectation at the boundary."""

    if type(value) is not CalendarPublicationPublishedObservation:
        raise CalendarPublicationAuditValidationError("published replay expectation is invalid")
    try:
        CalendarPublicationPublishedObservation.__post_init__(value)
    except CalendarPublicationAuditContractError as error:
        raise CalendarPublicationAuditValidationError(str(error), code=error.code) from error
    except (TypeError, ValueError) as error:
        raise CalendarPublicationAuditValidationError(
            "published replay expectation violates its typed contract"
        ) from error
    return value


def _validate_principal(
    *,
    principal: CalendarAuditPublisherPrincipal,
    database_alias: str,
) -> tuple[str, datetime]:
    """Require a live same-alias PUBLISH principal and return its read cutoff."""

    if type(database_alias) is not str or not database_alias:
        raise CalendarPublicationAuditDenied("calendar Audit database alias is missing")
    user_id = principal.user_id
    actor_type = principal.actor_type
    actor_id = principal.actor_id
    permission_codename = principal.permission_codename
    verified_at = principal.verified_at
    principal_alias = principal.database_alias
    if (
        type(user_id) is not int
        or user_id <= 0
        or actor_type != "django_user"
        or actor_id != f"django-user:{user_id}"
        or permission_codename != CALENDAR_PUBLISH_PERMISSION
        or principal_alias != database_alias
        or type(verified_at) is not datetime
        or not _is_utc(verified_at)
    ):
        raise CalendarPublicationAuditDenied(
            "calendar replay requires the original user's live publication permission"
        )
    return actor_id, verified_at


def _validate_event_winner(
    *,
    winner: SystemAuditEvent,
    observation: CalendarPublicationPublishedObservation,
    actor_id: str,
    verified_at: datetime,
    event_id: str,
    idempotency_key: str,
    stream_id: str,
) -> None:
    """Require the persisted event to match the current binding and actor."""

    if type(winner) is not SystemAuditEvent:
        raise CalendarPublicationAuditCorruption(
            "calendar publication event selector returned an invalid event"
        )
    try:
        validate_calendar_publication_event(winner)
        parsed_detail = CalendarPublicationPublishedDetail.from_payload(winner.detail)
    except (AttributeError, TypeError, ValueError) as error:
        raise CalendarPublicationAuditCorruption(
            "persisted calendar publication event is malformed"
        ) from error
    if winner.actor.actor_id != actor_id:
        raise CalendarPublicationAuditDenied(
            "only the original calendar publication actor may replay this event"
        )
    if (
        winner.event_type != CALENDAR_PUBLICATION_PUBLISHED_EVENT
        or winner.event_id != event_id
        or winner.idempotency_key != idempotency_key
        or winner.stream_id != stream_id
        or winner.dataset_key != observation.detail.dataset_key
        or winner.recorded_at != observation.recorded_at
        or winner.recorded_at > verified_at
        or parsed_detail != observation.detail
    ):
        raise CalendarPublicationAuditCorruption(
            "persisted calendar publication event does not match the current binding"
        )


def _validate_outbox_winner(
    *,
    outbox: ExactSystemAuditOutboxWinner | None,
    event: SystemAuditEvent,
) -> ExactSystemAuditOutboxWinner:
    """Revalidate that the exact outbox winner carries this complete event."""

    if type(outbox) is not ExactSystemAuditOutboxWinner:
        raise CalendarPublicationAuditCorruption(
            "calendar publication event has no exact outbox winner"
        )
    try:
        ExactSystemAuditOutboxWinner.__post_init__(outbox)
    except (AttributeError, TypeError, ValueError) as error:
        raise CalendarPublicationAuditCorruption(
            "calendar publication outbox winner is malformed"
        ) from error
    if (
        outbox.event != event
        or outbox.event_id != event.event_id
        or outbox.idempotency_key != event.idempotency_key
        or outbox.payload_hash != event.content_hash
    ):
        raise CalendarPublicationAuditCorruption(
            "calendar publication outbox is not the exact event pair"
        )
    return outbox


def _is_utc(value: datetime) -> bool:
    """Return whether a datetime is aware with zero UTC offset."""

    if value.tzinfo is None:
        return False
    offset = value.utcoffset()
    return offset is not None and offset == timedelta(0)


__all__ = [
    "CalendarPublicationAuditReplayReader",
    "VerifyCurrentCalendarPublicationAuditReplayUseCase",
]
