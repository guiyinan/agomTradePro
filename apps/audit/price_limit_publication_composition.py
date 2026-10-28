"""Alias-bound composition for price-limit publication Audit transactions."""

from __future__ import annotations

from typing import Protocol

from apps.audit.application.price_limit_publication_audit import (
    PriceLimitPublicationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from core.exceptions import InvalidInputError


class PriceLimitPublicationAuditCoordinator(PriceLimitPublicationAuditWriter, Protocol):
    """One same-alias adapter for the closed price-limit Audit family."""

    pass


def build_price_limit_publication_audit_coordinator(
    *,
    using: str,
) -> PriceLimitPublicationAuditCoordinator:
    """Build the canonical coordinator for one explicit database alias."""

    if type(using) is not str or not using or using.strip() != using:
        raise InvalidInputError(
            "price-limit Audit composition requires an explicit database alias",
            code="PRICE_LIMIT_PUBLICATION_AUDIT_ALIAS_INVALID",
        )
    coordinator = DjangoSystemAuditEventOutboxCoordinator(using=using)
    if coordinator.database_alias != using:
        raise InvalidInputError(
            "price-limit Audit coordinator was composed on another database alias",
            code="PRICE_LIMIT_PUBLICATION_AUDIT_ALIAS_MISMATCH",
        )
    return coordinator


__all__ = [
    "PriceLimitPublicationAuditCoordinator",
    "build_price_limit_publication_audit_coordinator",
]
