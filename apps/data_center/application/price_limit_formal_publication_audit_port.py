"""Data Center-owned port for exact price-limit publication Audit pairs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from apps.data_center.application.price_limit_publication_authority import (
    LockedPriceLimitPublisherPrincipal,
)
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitPublicationTimelineEvent,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationAuditPair:
    """Receipt binding one business pointer transition to its exact Audit/outbox pair.

    ``transition_event_id`` is the PriceLimit Domain activation or rollback ID.
    ``audit_event_id`` is the separately derived stable SystemAudit identity.
    """

    database_alias: str
    dataset_key: str
    publication_key: str
    publication_id: str
    publication_hash: str
    transition_event_id: str
    timeline_event: PriceLimitPublicationTimelineEvent
    audit_event_id: str
    audit_event_content_hash: str
    actor_user_id: int
    outbox_id: UUID
    idempotency_key: str
    recorded_at: datetime
    observed_server_at: datetime

    def __post_init__(self) -> None:
        """Reject partial receipts and any ID, scope, or clock substitution."""

        for field_name in (
            "database_alias",
            "dataset_key",
            "publication_key",
            "publication_id",
            "transition_event_id",
            "audit_event_id",
            "idempotency_key",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value or value.strip() != value:
                raise ValueError(f"PriceLimit Audit pair {field_name} is invalid")
        if type(self.timeline_event) is not PriceLimitPublicationTimelineEvent:
            raise ValueError("PriceLimit Audit pair transition must be typed")
        self.timeline_event.validate()
        if (
            self.dataset_key != self.timeline_event.dataset_key
            or self.publication_key != self.timeline_event.publication_key
            or self.publication_id != self.timeline_event.target_publication_id
            or self.publication_hash != self.timeline_event.target_publication_hash
            or self.transition_event_id != self.timeline_event.event_id
        ):
            raise ValueError("PriceLimit Audit pair differs from the exact business transition")
        for field_name in ("publication_hash", "audit_event_content_hash"):
            value = getattr(self, field_name)
            if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
                raise ValueError(f"PriceLimit Audit pair {field_name} is invalid")
        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("PriceLimit Audit pair actor_user_id is invalid")
        if type(self.outbox_id) is not UUID:
            raise ValueError("PriceLimit Audit pair outbox_id must be a UUID")
        if self.idempotency_key != self.audit_event_id:
            raise ValueError("SystemAudit event/outbox identities differ")
        for field_name in ("recorded_at", "observed_server_at"):
            value = getattr(self, field_name)
            if (
                type(value) is not datetime
                or value.tzinfo is None
                or value.utcoffset() != timedelta(0)
            ):
                raise ValueError(f"PriceLimit Audit pair {field_name} must be UTC")
        if self.recorded_at != self.observed_server_at:
            raise ValueError("PriceLimit Audit pair recorded and observed clocks differ")


class PriceLimitFormalPublicationAuditPort(Protocol):
    """Append or verify one exact price-limit transition under a live lease."""

    @property
    def database_alias(self) -> str:
        """Return the alias shared with the caller-owned publication transaction."""

    def record_transition(
        self,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Append one typed publish or rollback transition and exact outbox pair."""

    def get_first_transition(
        self,
        *,
        publication_id: str,
        publication_hash: str,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Read the exact first event/outbox for a persisted publication identity."""

    def verify_transition(
        self,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Verify an exact stored transition without writing or browsing Audit."""


class PriceLimitFormalPublicationReferenceAuditPort(Protocol):
    """Read exact published price-limit evidence without a publisher lease.

    Unavailable or corrupt Audit evidence raises ``DataFetchError`` with the
    original stable Audit code; readers never synthesize missing evidence.
    """

    @property
    def database_alias(self) -> str:
        """Return the alias shared with the reference-read transaction."""

    def get_first_transition_for_reference(
        self,
        *,
        publication_id: str,
        publication_hash: str,
        publication_key: str,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Read one exact publication identity only within its market scope and cutoff."""

    def verify_transition_for_reference(
        self,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
        *,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Verify one typed transition and exact event/outbox pair without browsing."""


__all__ = [
    "PriceLimitFormalPublicationAuditPort",
    "PriceLimitFormalPublicationReferenceAuditPort",
    "PriceLimitPublicationAuditPair",
]
