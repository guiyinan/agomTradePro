"""Canonical real-time quote snapshot persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import QuoteSnapshotModel


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
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = QuoteSnapshotModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            m = qs.order_by("-snapshot_at").first()
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
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = QuoteSnapshotModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            if snapshot_date is not None:
                qs = qs.filter(snapshot_at__date=snapshot_date)
            rows = list(qs.order_by("-snapshot_at")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def bulk_upsert(self, quotes: list[QuoteSnapshot]) -> int:
        count = 0
        for q in quotes:
            QuoteSnapshotModel.objects.update_or_create(
                asset_code=q.asset_code,
                snapshot_at=q.snapshot_at,
                source=q.source,
                defaults={
                    "current_price": q.current_price,
                    "fetched_at": q.fetched_at,
                    "open": q.open,
                    "high": q.high,
                    "low": q.low,
                    "prev_close": q.prev_close,
                    "volume": q.volume,
                    "amount": q.amount,
                    "bid": q.bid,
                    "ask": q.ask,
                    "extra": q.extra,
                    "ingested_run_id": q.ingested_run_id or None,
                },
            )
            count += 1
        return count

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
                .order_by("id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            natural_key = f"{row.asset_code}:{row.snapshot_at.isoformat()}:{row.source}"
            references.append(
                PublicationFactReference(
                    natural_key=natural_key,
                    source=row.source,
                    source_record_id=row.source_record_id or natural_key,
                    fact_table="data_center_quote_snapshot",
                    fact_pk=fact_pk,
                    observed_at=row.snapshot_at,
                    raw_payload_hash=row.raw_payload_hash or _quote_payload_hash(row),
                    quality_status=row.quality_status,
                    revision_number=row.revision_number,
                )
            )
        return references


def _quote_payload_hash(row: QuoteSnapshotModel) -> str:
    """Return deterministic evidence for one persisted quote snapshot."""

    payload = {
        "asset_code": row.asset_code,
        "snapshot_at": row.snapshot_at.isoformat(),
        "current_price": str(row.current_price),
        "open": str(row.open) if row.open is not None else None,
        "high": str(row.high) if row.high is not None else None,
        "low": str(row.low) if row.low is not None else None,
        "prev_close": str(row.prev_close) if row.prev_close is not None else None,
        "volume": str(row.volume) if row.volume is not None else None,
        "amount": str(row.amount) if row.amount is not None else None,
        "bid": str(row.bid) if row.bid is not None else None,
        "ask": str(row.ask) if row.ask is not None else None,
        "source": row.source,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = ["QuoteSnapshotRepository"]
