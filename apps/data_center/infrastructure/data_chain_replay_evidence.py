"""Whitelisted ORM resolver for canonical publication fact replay evidence."""

from __future__ import annotations

from uuid import UUID

from apps.data_center.application.data_chain_replay import (
    ReplayMemberPersistenceEvidence,
)
from apps.data_center.domain.control_plane import PublicationMember

from .models import MacroFactModel, PriceBarModel, QuoteSnapshotModel


def _positive_pk(value: str) -> int | None:
    """Parse one positive ASCII integer primary key without coercion."""

    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _ingested_run_id(member: PublicationMember) -> UUID | None:
    """Return a whitelisted fact's exact ingestion run or ``None``."""

    fact_pk = _positive_pk(member.fact_pk)
    if fact_pk is None:
        return None
    if member.fact_table == "data_center_macro_fact":
        return (
            MacroFactModel._default_manager.filter(pk=fact_pk)
            .values_list("ingested_run_id", flat=True)
            .first()
        )
    if member.fact_table == "data_center_price_bar":
        return (
            PriceBarModel._default_manager.filter(pk=fact_pk)
            .values_list("ingested_run_id", flat=True)
            .first()
        )
    if member.fact_table == "data_center_quote_snapshot":
        return (
            QuoteSnapshotModel._default_manager.filter(pk=fact_pk)
            .values_list("ingested_run_id", flat=True)
            .first()
        )
    return None


class DjangoReplayFactEvidenceReader:
    """Resolve only AUD-02's three canonical fact-table identities."""

    def list_member_evidence(
        self, members: tuple[PublicationMember, ...]
    ) -> tuple[ReplayMemberPersistenceEvidence, ...]:
        """Return exact, input-ordered evidence without fabricating missing rows."""

        evidence: list[ReplayMemberPersistenceEvidence] = []
        for member in members:
            ingested_run_id = _ingested_run_id(member)
            if ingested_run_id is None:
                continue
            evidence.append(
                ReplayMemberPersistenceEvidence(
                    fact_table=member.fact_table,
                    fact_pk=member.fact_pk,
                    ingested_run_id=str(ingested_run_id),
                )
            )
        return tuple(evidence)


__all__ = ["DjangoReplayFactEvidenceReader"]
