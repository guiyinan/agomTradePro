"""Bind every current-window member to its Data Center record and retained original."""

from __future__ import annotations

from pathlib import Path

from django.db import DatabaseError

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventReadScope,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.data_center.security_disclosure_body_composition import (
    verify_security_disclosure_original_body,
)
from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
)
from apps.portfolio.domain.transition_plan_event_review import TransitionPlanEventRevision
from core.exceptions import AgomTradeProException


class DataCenterCorporateActionOriginalBodyVerifier:
    """Read exact source records through public Data Center services only."""

    def __init__(self, *, using: str = "default") -> None:
        """Bind the current-window member checks to one explicit database alias."""
        if type(using) is not str or not using.strip():
            raise ValueError("original-body database alias must be explicit")
        self._reader = make_security_disclosure_event_reader(using=using)

    def verify_original_body(
        self,
        *,
        event: TransitionPlanEventRevision,
        body_store_root: Path,
    ) -> bool:
        """Verify the exact immutable record, clocks, manifest and original PDF bytes."""
        if type(event) is not TransitionPlanEventRevision:
            return False
        try:
            event.__post_init__()
            if event.source_id != "szse_official" or event.security_id != event.asset_code:
                return False
            records = self._reader.execute(
                SecurityDisclosureEventReadScope(
                    as_of=event.known_at,
                    exchange=SecurityDisclosureExchange.SZSE,
                    asset_code=event.asset_code,
                )
            )
            selected = tuple(
                record
                for record in records
                if record.event.source_event_id == event.source_event_id
                and record.event.source_revision_id == event.source_revision_id
            )
            if len(selected) != 1:
                return False
            record = selected[0]
            original = record.event
            if (
                original.source is not SecurityDisclosureSource.SZSE_OFFICIAL
                or original.exchange is not SecurityDisclosureExchange.SZSE
                or original.asset_code != event.asset_code
                or original.source_security_code != event.asset_code[:6]
                or record.recorded_at != event.known_at
                or original.first_seen_at != event.available_at
                or original.announced_at != event.announced_at
                or original.effective_at != event.effective_at
                or original.source_body_sha256 != event.body_sha256
                or original.content_hash != event.manifest_sha256
                or original.event_type.value != event.event_type
            ):
                return False
            return verify_security_disclosure_original_body(
                original,
                body_store_root=body_store_root,
            )
        except (AgomTradeProException, DatabaseError, OSError, TypeError, ValueError):
            return False
