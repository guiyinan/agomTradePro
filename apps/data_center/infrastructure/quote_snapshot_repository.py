"""Canonical real-time quote snapshot persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import QuoteSnapshotModel

from .publication_fact_evidence import publication_fact_reference_for_dataset
from .published_fact_versions import (
    latest_fact_revisions,
    latest_versioned_rows_for_assets,
    upsert_publication_safe_facts,
)

_NATURAL_KEY = ("asset_code", "snapshot_at", "source")


class QuoteSnapshotRepository:
    """ORM-backed repository for real-time quote snapshots."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the fixed transaction identity used by this repository."""

        return "django:default"

    @staticmethod
    def _from_model(m: QuoteSnapshotModel) -> QuoteSnapshot:
        return QuoteSnapshot(
            asset_code=m.asset_code,
            snapshot_at=m.snapshot_at,
            fetched_at=m.fetched_at,
            current_price=float(m.current_price),
            open=float(m.open) if m.open is not None else None,
            high=float(m.high) if m.high is not None else None,
            low=float(m.low) if m.low is not None else None,
            prev_close=float(m.prev_close) if m.prev_close is not None else None,
            volume=float(m.volume) if m.volume is not None else None,
            amount=float(m.amount) if m.amount is not None else None,
            bid=float(m.bid) if m.bid is not None else None,
            ask=float(m.ask) if m.ask is not None else None,
            source=m.source,
            extra=m.extra or {},
            ingested_run_id=str(m.ingested_run_id) if m.ingested_run_id else "",
        )

    def get_latest(
        self,
        asset_code: str,
        fact_pks: Sequence[str] | None = None,
    ) -> QuoteSnapshot | None:
        """Return the newest observation, respecting any frozen publication scope."""
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = QuoteSnapshotModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            m = qs.order_by("-snapshot_at", "-revision_number", "-pk").first()
            if m is not None:
                return self._from_model(m)
        return None

    def get_series(
        self,
        asset_code: str,
        snapshot_date: date | None = None,
        limit: int = 500,
        fact_pks: Sequence[str] | None = None,
    ) -> list[QuoteSnapshot]:
        """Return latest revisions or the exact rows pinned by a publication."""
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = QuoteSnapshotModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            else:
                qs = latest_fact_revisions(QuoteSnapshotModel, _NATURAL_KEY).filter(
                    asset_code=candidate
                )
            if snapshot_date is not None:
                qs = qs.filter(snapshot_at__date=snapshot_date)
            rows = list(qs.order_by("-snapshot_at")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def bulk_upsert(self, quotes: list[QuoteSnapshot]) -> int:
        """Persist new observations without mutating any publication-referenced row."""
        rows = [
            QuoteSnapshotModel(
                asset_code=q.asset_code,
                snapshot_at=q.snapshot_at,
                source=q.source,
                current_price=q.current_price,
                fetched_at=q.fetched_at,
                open=q.open,
                high=q.high,
                low=q.low,
                prev_close=q.prev_close,
                volume=q.volume,
                amount=q.amount,
                bid=q.bid,
                ask=q.ask,
                extra=q.extra,
                ingested_run_id=q.ingested_run_id or None,
            )
            for q in quotes
        ]
        return upsert_publication_safe_facts(
            QuoteSnapshotModel,
            rows,
            natural_key=_NATURAL_KEY,
            update_fields=(
                "current_price",
                "fetched_at",
                "open",
                "high",
                "low",
                "prev_close",
                "volume",
                "amount",
                "bid",
                "ask",
                "extra",
                "ingested_run_id",
            ),
        )

    def list_publication_candidates(
        self, quotes: Sequence[QuoteSnapshot]
    ) -> list[PublicationFactReference]:
        """Resolve persisted quotes to exact fact references.

        The source ``snapshot_at`` is preserved as ``observed_at``.  The
        ingestion ``fetched_at`` field is evidence of retrieval only and never
        becomes the realtime observation boundary.
        """

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        for quote in quotes:
            row = (
                QuoteSnapshotModel._default_manager.filter(
                    asset_code=quote.asset_code,
                    snapshot_at=quote.snapshot_at,
                    source=quote.source,
                )
                .order_by("-revision_number", "-id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            references.append(_quote_snapshot_publication_reference(row))
        return references

    def list_latest_for_asset_codes(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[QuoteSnapshot]:
        """Return one deterministic latest source snapshot per requested asset."""

        return [self._from_model(row) for row in _latest_quote_rows(asset_codes)]

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[PublicationFactReference]:
        """Select the latest immutable quote fact for every requested asset."""

        return [
            _quote_snapshot_publication_reference(row) for row in _latest_quote_rows(asset_codes)
        ]


def _latest_quote_rows(asset_codes: tuple[str, ...]) -> list[QuoteSnapshotModel]:
    """Return one exact latest-revision row per requested asset in a single query."""

    return latest_versioned_rows_for_assets(
        QuoteSnapshotModel,
        natural_key=_NATURAL_KEY,
        asset_codes=asset_codes,
        observation_field="snapshot_at",
        asset_order=("-snapshot_at", "-fetched_at", "-revision_number", "-id"),
    )


def _quote_snapshot_publication_reference(
    row: QuoteSnapshotModel,
) -> PublicationFactReference:
    """Create the exact persisted evidence reference for one quote row."""

    return publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.quote.snapshot",
    )


__all__ = ["QuoteSnapshotRepository"]
