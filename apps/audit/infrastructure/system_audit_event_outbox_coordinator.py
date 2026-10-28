"""Same-alias infrastructure coordinator for system audit double writes."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from django.db import connections, transaction

from apps.audit.application.calendar_publication_audit import CalendarAuditPublisherPrincipal
from apps.audit.application.price_limit_publication_audit import PriceLimitAuditPublisherPrincipal
from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
    SystemAuditEventOutboxCorruption,
)
from apps.audit.domain.calendar_publication_audit import (
    CALENDAR_PUBLISH_PERMISSION,
    calendar_publication_event_selector,
    validate_calendar_publication_event,
)
from apps.audit.domain.price_limit_publication_audit import (
    PRICE_LIMIT_PUBLICATION_DATASET,
    PRICE_LIMIT_PUBLISH_PERMISSION,
    PriceLimitPublicationAuditContractError,
    PriceLimitPublicationPublishedDetail,
    PriceLimitPublicationRollbackDetail,
    PriceLimitPublicationTransitionEvidence,
    price_limit_publication_stream_id,
    validate_price_limit_publication_event,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent
from core.exceptions import AuthenticationError, AuthorizationError

from .system_audit_outbox_repository import DjangoSystemAuditOutboxRepository
from .system_audit_repository import DjangoSystemAuditEventRepository

_AUTHORITY_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class DjangoSystemAuditEventOutboxCoordinator:
    """Coordinate event append and outbox enqueue under one database alias.

    The two repositories keep their own private UOW guards.  They are nested
    inside one coordinator transaction on the same alias, so an event or an
    outbox failure rolls back both writes together.
    """

    __slots__ = ("_event_repository", "_outbox_repository", "_using", "_active")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._event_repository = DjangoSystemAuditEventRepository(using=using)
        self._outbox_repository = DjangoSystemAuditOutboxRepository(using=using)
        self._active = False

    @property
    def database_alias(self) -> str:
        """Return the alias shared by the event and outbox repositories."""

        return self._using

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nested transaction shared by both repositories."""

        if self._active:
            raise SystemAuditEventOutboxConflict("event/outbox UOW cannot be nested")
        self._active = True
        try:
            with transaction.atomic(using=self._using):
                with self._event_repository.atomic():
                    with self._outbox_repository.atomic():
                        yield
        finally:
            self._active = False

    @contextmanager
    def caller_owned_atomic(self) -> Iterator[None]:
        """Bind both append capabilities to an existing outer transaction."""

        if self._active:
            raise SystemAuditEventOutboxConflict("event/outbox UOW cannot be nested")
        connection = connections[self._using]
        if not connection.in_atomic_block or connection.get_autocommit():
            raise SystemAuditEventOutboxConflict(
                "caller-owned event/outbox UOW requires an active transaction"
            )
        atomic_blocks = getattr(connection, "atomic_blocks", None)
        if not isinstance(atomic_blocks, list) or len(atomic_blocks) != 1:
            raise SystemAuditEventOutboxConflict(
                "caller-owned event/outbox UOW requires the outermost transaction"
            )
        self._active = True
        try:
            with self._event_repository.caller_owned_atomic():
                with self._outbox_repository.caller_owned_atomic():
                    yield
        finally:
            self._active = False

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        """Append/replay an event and enqueue its exact canonical payload."""

        persisted_event = self._event_repository.append(
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
        )
        outbox_record = self._outbox_repository.enqueue(
            persisted_event,
            created_at=recorded_at,
            available_at=recorded_at,
        )
        if outbox_record.event != persisted_event:
            raise SystemAuditEventOutboxConflict("outbox payload does not match event winner")
        return SystemAuditEventOutboxCommit(
            event=persisted_event,
            outbox_id=outbox_record.outbox_id,
            event_id=persisted_event.event_id,
            idempotency_key=persisted_event.idempotency_key,
        )

    def append_and_enqueue_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        scope: AuditScopeRef | None = None,
        identity_winner: SystemAuditEvent | None = None,
        stream_head: SystemAuditEvent | None = None,
    ) -> SystemAuditEventOutboxCommit:
        """Append and enqueue through bounded activation selectors."""

        persisted_event = self._event_repository.append_targeted(
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
            scope=scope,
            identity_winner=identity_winner,
            stream_head=stream_head,
        )
        outbox_record = self._outbox_repository.enqueue_targeted(
            persisted_event,
            created_at=recorded_at,
            available_at=recorded_at,
        )
        if outbox_record.event != persisted_event:
            raise SystemAuditEventOutboxConflict("outbox payload does not match event winner")
        return SystemAuditEventOutboxCommit(
            event=persisted_event,
            outbox_id=outbox_record.outbox_id,
            event_id=persisted_event.event_id,
            idempotency_key=persisted_event.idempotency_key,
        )

    def append_and_enqueue_calendar_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        principal: CalendarAuditPublisherPrincipal,
    ) -> SystemAuditEventOutboxCommit:
        """Atomically append one authorized calendar event and its exact outbox.

        This calendar-only path is the sole no-scope append capability. It
        validates the closed event contract, rechecks the live publisher lease
        on this alias, and refuses to repair an event/outbox half-pair during
        replay.
        """

        if not self._active:
            raise SystemAuditEventOutboxConflict(
                "calendar Audit append requires the caller-owned event/outbox UOW"
            )
        try:
            validate_calendar_publication_event(event)
        except (AttributeError, TypeError, ValueError) as error:
            raise SystemAuditEventOutboxConflict(
                "calendar Audit candidate is outside its exact registered contract"
            ) from error
        if event.recorded_at != recorded_at:
            raise SystemAuditEventOutboxConflict(
                "calendar Audit event recorded_at differs from the write"
            )
        try:
            principal.assert_live()
        except (AuthenticationError, AuthorizationError) as error:
            raise SystemAuditEventOutboxConflict(
                "calendar publisher authorization lease is no longer live"
            ) from error
        # Read attribution only after the lease has been revalidated.
        user_id = getattr(principal, "user_id", None)
        actor_type = getattr(principal, "actor_type", None)
        actor_id = getattr(principal, "actor_id", None)
        permission_codename = getattr(principal, "permission_codename", None)
        database_alias = getattr(principal, "database_alias", None)
        verified_at = getattr(principal, "verified_at", None)
        recorded_offset = recorded_at.utcoffset() if type(recorded_at) is datetime else None
        verified_offset = verified_at.utcoffset() if type(verified_at) is datetime else None
        if (
            type(recorded_at) is not datetime
            or recorded_at.tzinfo is None
            or recorded_offset is None
            or recorded_offset.total_seconds() != 0
            or type(user_id) is not int
            or user_id <= 0
            or actor_type != "django_user"
            or actor_id != f"django-user:{user_id}"
            or permission_codename != CALENDAR_PUBLISH_PERMISSION
            or database_alias != self._using
            or event.actor.actor_type != actor_type
            or event.actor.actor_id != actor_id
            or type(verified_at) is not datetime
            or verified_at.tzinfo is None
            or verified_offset is None
            or verified_offset.total_seconds() != 0
        ):
            raise SystemAuditEventOutboxConflict(
                "calendar Audit actor or permission differs from the locked principal"
            )

        self.lock_stream(event.stream_id)
        now = self._event_repository.now()
        dataset_key, exchange = calendar_publication_event_selector(event)
        winner = self._event_repository.get_calendar_publication_winner_targeted(
            event_id=event.event_id,
            event_version=event.event_version,
            dataset_key=dataset_key,
            exchange=exchange,
            as_of=now,
            lock=True,
        )
        if winner is not None:
            if winner != event:
                raise SystemAuditEventOutboxConflict(
                    "calendar Audit identity already has another event winner"
                )
            outbox_winner = self.get_exact_outbox_winner_targeted(winner)
            if outbox_winner is None:
                raise SystemAuditEventOutboxCorruption(
                    "calendar Audit event winner has no exact outbox row"
                )
            if outbox_winner.event != event:
                raise SystemAuditEventOutboxCorruption(
                    "calendar Audit event and outbox winners differ"
                )
            return SystemAuditEventOutboxCommit(
                event=event,
                outbox_id=outbox_winner.outbox_id,
                event_id=event.event_id,
                idempotency_key=event.idempotency_key,
            )

        orphan = self.get_exact_outbox_winner_targeted(event)
        if orphan is not None:
            raise SystemAuditEventOutboxCorruption(
                "calendar Audit outbox identity exists without its event winner"
            )
        head = self._event_repository.get_calendar_publication_head_targeted(
            dataset_key=dataset_key,
            exchange=exchange,
            as_of=now,
            lock=True,
        )
        persisted_event = self._event_repository.append_calendar_targeted(
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
            identity_winner=None,
            stream_head=head,
        )
        outbox_record = self._outbox_repository.enqueue_targeted(
            persisted_event,
            created_at=recorded_at,
            available_at=recorded_at,
        )
        if outbox_record.event != persisted_event:
            raise SystemAuditEventOutboxConflict(
                "calendar Audit outbox payload does not match the event winner"
            )
        return SystemAuditEventOutboxCommit(
            event=persisted_event,
            outbox_id=outbox_record.outbox_id,
            event_id=persisted_event.event_id,
            idempotency_key=persisted_event.idempotency_key,
        )

    def append_and_enqueue_price_limit_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        principal: PriceLimitAuditPublisherPrincipal,
    ) -> SystemAuditEventOutboxCommit:
        """Atomically append one authorized unscoped price-limit event and outbox."""

        if not self._active:
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit append requires the caller-owned event/outbox UOW"
            )
        try:
            validate_price_limit_publication_event(event)
        except (
            AttributeError,
            TypeError,
            ValueError,
            PriceLimitPublicationAuditContractError,
        ) as error:
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit candidate is outside its exact registered contract"
            ) from error
        if event.recorded_at != recorded_at or event.observed_at != recorded_at:
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit observed and recorded clocks differ from the write"
            )
        try:
            principal.assert_live()
        except (AuthenticationError, AuthorizationError) as error:
            raise SystemAuditEventOutboxConflict(
                "price-limit publisher authorization lease is no longer live"
            ) from error
        user_id = getattr(principal, "user_id", None)
        actor_type = getattr(principal, "actor_type", None)
        actor_id = getattr(principal, "actor_id", None)
        permission_codename = getattr(principal, "permission_codename", None)
        permission_id = getattr(principal, "permission_id", None)
        database_alias = getattr(principal, "database_alias", None)
        verified_at = getattr(principal, "verified_at", None)
        authority_hash = getattr(principal, "authority_content_hash", None)
        recorded_offset = recorded_at.utcoffset() if type(recorded_at) is datetime else None
        verified_offset = verified_at.utcoffset() if type(verified_at) is datetime else None
        if (
            type(recorded_at) is not datetime
            or recorded_at.tzinfo is None
            or recorded_offset is None
            or recorded_offset.total_seconds() != 0
            or type(user_id) is not int
            or user_id <= 0
            or actor_type != "django_user"
            or actor_id != f"django-user:{user_id}"
            or permission_codename != PRICE_LIMIT_PUBLISH_PERMISSION
            or type(permission_id) is not int
            or permission_id <= 0
            or database_alias != self._using
            or event.actor.actor_type != actor_type
            or event.actor.actor_id != actor_id
            or type(authority_hash) is not str
            or _AUTHORITY_HASH_RE.fullmatch(authority_hash) is None
            or type(verified_at) is not datetime
            or verified_at.tzinfo is None
            or verified_offset is None
            or verified_offset.total_seconds() != 0
            or verified_at > recorded_at
        ):
            raise SystemAuditEventOutboxConflict(
                "price-limit publisher, permission, or database differs from the locked lease"
            )

        self.lock_stream(event.stream_id)
        now = self._event_repository.now()
        if recorded_at > now:
            raise SystemAuditEventOutboxConflict("future price-limit Audit clock is forbidden")
        transition = _price_limit_transition_from_event(event)
        if (
            transition.dataset_key != PRICE_LIMIT_PUBLICATION_DATASET
            or event.stream_id
            != price_limit_publication_stream_id(transition.dataset_key, transition.publication_key)
        ):
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit event is outside its deterministic stream"
            )
        winner = self._event_repository.get_winner_targeted(
            event_id=event.event_id,
            event_version=event.event_version,
            as_of=now,
            lock=True,
        )
        if winner is not None:
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit event identity already has a winner"
            )
        orphan = self.get_exact_outbox_winner_targeted(event)
        if orphan is not None:
            raise SystemAuditEventOutboxCorruption(
                "price-limit Audit outbox identity exists without its event winner"
            )
        head = self._event_repository.get_current_head_targeted(
            stream_id=event.stream_id,
            as_of=now,
            scope=None,
            lock=True,
        )
        if head is not None:
            try:
                validate_price_limit_publication_event(head)
            except (
                AttributeError,
                TypeError,
                ValueError,
                PriceLimitPublicationAuditContractError,
            ) as error:
                raise SystemAuditEventOutboxCorruption(
                    "price-limit Audit stream head violates its registered contract"
                ) from error
        persisted_event = self._event_repository.append_price_limit_targeted(
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
            identity_winner=None,
            stream_head=head,
        )
        outbox_record = self._outbox_repository.enqueue_targeted(
            persisted_event,
            created_at=recorded_at,
            available_at=recorded_at,
        )
        if outbox_record.event != persisted_event:
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit outbox payload does not match the event winner"
            )
        return SystemAuditEventOutboxCommit(
            event=persisted_event,
            outbox_id=outbox_record.outbox_id,
            event_id=persisted_event.event_id,
            idempotency_key=persisted_event.idempotency_key,
        )

    def lock_stream(self, stream_id: str) -> None:
        """Serialize the exact audit stream before reading its head."""

        self._event_repository.lock_stream(stream_id)

    def lock_streams(self, stream_ids: tuple[str, ...]) -> None:
        """Serialize an exact activation stream group in stable order."""

        self._event_repository.lock_streams(stream_ids)

    def get_activation_group_state_targeted(
        self,
        *,
        identities: tuple[tuple[str, str], ...],
        stream_ids: tuple[str, ...],
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> tuple[
        dict[tuple[str, str], SystemAuditEvent],
        dict[str, SystemAuditEvent],
    ]:
        """Lock grouped event winners and stream heads with one bounded read."""

        return self._event_repository.get_activation_group_state_targeted(
            identities=identities,
            stream_ids=stream_ids,
            as_of=as_of,
            scope=scope,
        )

    def append_and_enqueue_group_targeted(
        self,
        events: tuple[SystemAuditEvent, ...],
        *,
        identity_winners: dict[tuple[str, str], SystemAuditEvent],
        stream_heads: dict[str, SystemAuditEvent],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Append a serialized event group and enqueue it after one outbox lookup."""

        persisted_events = self._event_repository.append_group_targeted(
            events,
            identity_winners=identity_winners,
            stream_heads=stream_heads,
        )
        replay_events = tuple(
            event
            for event in persisted_events
            if (event.event_id, event.event_version) in identity_winners
        )
        outbox_winners = (
            self._outbox_repository.get_identity_winners_targeted(replay_events)
            if replay_events
            else {}
        )
        outbox_records = self._outbox_repository.enqueue_group_targeted_prefetched(
            persisted_events,
            existing=outbox_winners,
        )
        commits: list[SystemAuditEventOutboxCommit] = []
        for event, outbox_record in zip(persisted_events, outbox_records, strict=True):
            if outbox_record.event != event:
                raise SystemAuditEventOutboxConflict("outbox payload does not match event winner")
            commits.append(
                SystemAuditEventOutboxCommit(
                    event=event,
                    outbox_id=outbox_record.outbox_id,
                    event_id=event.event_id,
                    idempotency_key=event.idempotency_key,
                )
            )
        return tuple(commits)

    def get_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
        lock: bool = False,
    ) -> SystemAuditEvent | None:
        """Read one event identity through the bounded activation selector."""

        return self._event_repository.get_winner_targeted(
            event_id=event_id,
            event_version=event_version,
            as_of=as_of,
            lock=lock,
        )

    def get_calendar_publication_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Read one event identity after exact calendar contract validation."""

        return self._event_repository.get_calendar_publication_winner_targeted(
            event_id=event_id,
            event_version=event_version,
            dataset_key=dataset_key,
            exchange=exchange,
            as_of=as_of,
            lock=True,
        )

    def get_price_limit_publication_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        dataset_key: str,
        publication_key: str | None,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Select one exact closed PriceLimit event by its stable family identity."""

        if not self._active:
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit winner reads require the caller-owned event/outbox UOW"
            )
        if dataset_key != PRICE_LIMIT_PUBLICATION_DATASET:
            raise SystemAuditEventOutboxConflict("price-limit Audit selector dataset is invalid")
        event = self._event_repository.get_winner_targeted(
            event_id=event_id,
            event_version=event_version,
            as_of=as_of,
            lock=True,
        )
        if event is None:
            return None
        try:
            validate_price_limit_publication_event(event)
        except (
            AttributeError,
            TypeError,
            ValueError,
            PriceLimitPublicationAuditContractError,
        ) as error:
            raise SystemAuditEventOutboxCorruption(
                "price-limit Audit winner violates its registered contract"
            ) from error
        transition = _price_limit_transition_from_event(event)
        if transition.dataset_key != dataset_key or (
            publication_key is not None and transition.publication_key != publication_key
        ):
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit winner differs from the exact selector"
            )
        return event

    def get_price_limit_publication_head_targeted(
        self,
        *,
        dataset_key: str,
        publication_key: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Read the locked latest event of exactly one price-limit pointer stream."""

        if not self._active:
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit head reads require the caller-owned event/outbox UOW"
            )
        stream_id = price_limit_publication_stream_id(dataset_key, publication_key)
        event = self._event_repository.get_current_head_targeted(
            stream_id=stream_id,
            as_of=as_of,
            scope=None,
            lock=True,
        )
        if event is None:
            return None
        try:
            validate_price_limit_publication_event(event)
        except (
            AttributeError,
            TypeError,
            ValueError,
            PriceLimitPublicationAuditContractError,
        ) as error:
            raise SystemAuditEventOutboxCorruption(
                "price-limit Audit head violates its registered contract"
            ) from error
        transition = _price_limit_transition_from_event(event)
        if transition.publication_key != publication_key or transition.dataset_key != dataset_key:
            raise SystemAuditEventOutboxConflict(
                "price-limit Audit head differs from its exact pointer selector"
            )
        return event

    def get_calendar_publication_head_targeted(
        self,
        *,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Read the exact calendar stream head after the caller locks its stream."""

        return self._event_repository.get_calendar_publication_head_targeted(
            dataset_key=dataset_key,
            exchange=exchange,
            as_of=as_of,
            lock=True,
        )

    def list_calendar_publication_events(
        self,
        *,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> tuple[SystemAuditEvent, ...]:
        """Return only registered events from one exact dataset/exchange stream."""

        return self._event_repository.list_calendar_publication_events(
            dataset_key=dataset_key,
            exchange=exchange,
            as_of=as_of,
        )

    def get_current_head_targeted(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef | None = None,
        lock: bool = False,
    ) -> SystemAuditEvent | None:
        """Read one stream head through a bounded selector."""

        return self._event_repository.get_current_head_targeted(
            stream_id=stream_id,
            as_of=as_of,
            scope=scope,
            lock=lock,
        )

    def get_exact_outbox_winner_targeted(
        self,
        event: SystemAuditEvent,
    ) -> ExactSystemAuditOutboxWinner | None:
        """Read an exact matching outbox row through the existing identity selector."""

        if type(event) is not SystemAuditEvent:
            raise SystemAuditEventOutboxConflict("exact outbox reads require a typed event")
        try:
            event.validate_hashes()
        except (TypeError, ValueError) as error:
            raise SystemAuditEventOutboxConflict(
                "exact outbox reads require a hash-valid event"
            ) from error
        if not self._active:
            raise SystemAuditEventOutboxConflict(
                "exact outbox winner reads require the caller-owned event/outbox UOW"
            )
        winners = self._outbox_repository.get_identity_winners_targeted((event,))
        record = winners.get(event.event_id)
        if record is None:
            return None
        return ExactSystemAuditOutboxWinner(
            outbox_id=record.outbox_id,
            event=record.event,
            event_id=record.event.event_id,
            idempotency_key=record.event.idempotency_key,
            payload_hash=record.event.content_hash,
        )

    def get_winner(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Return an existing event identity through the coordinator alias."""

        return self._event_repository.get_winner(
            event_id=event_id,
            event_version=event_version,
            as_of=as_of,
        )

    def get_current_head(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> SystemAuditEvent | None:
        """Return the scoped current head through the coordinator alias."""

        return self._event_repository.get_current_head(
            stream_id=stream_id,
            as_of=as_of,
            scope=scope,
        )


def _price_limit_transition_from_event(
    event: SystemAuditEvent,
) -> PriceLimitPublicationTransitionEvidence:
    """Return one typed transition after the caller validates the closed event."""

    if event.event_type == "data.price_limit.publication.published":
        return PriceLimitPublicationPublishedDetail.from_payload(event.detail).transition
    if event.event_type == "data.price_limit.publication.rolled_back":
        return PriceLimitPublicationRollbackDetail.from_payload(event.detail).transition
    raise SystemAuditEventOutboxCorruption("event is outside the PriceLimit family")


__all__ = ["DjangoSystemAuditEventOutboxCoordinator"]


__all__ = ["DjangoSystemAuditEventOutboxCoordinator"]
