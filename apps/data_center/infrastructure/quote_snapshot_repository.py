"""Canonical real-time quote snapshot persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from fractions import Fraction

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import QuoteChangePctEvidence, QuoteSnapshot
from apps.data_center.domain.market_time import cn_market_date_start_utc
from apps.data_center.domain.quote_change_pct import quote_change_pct_storage_value
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import QuoteSnapshotModel

from .publication_fact_evidence import publication_fact_reference_for_dataset
from .published_fact_versions import (
    latest_fact_revisions,
    latest_versioned_rows_for_assets,
    upsert_publication_safe_facts,
)

_NATURAL_KEY = ("asset_code", "snapshot_at", "source")


def _quote_transport_identity(extra: Mapping[str, object]) -> tuple[str, str]:
    """Return bounded persisted source identity fields from one typed extra map."""

    source_record_id = extra.get("source_record_id")
    if (
        not isinstance(source_record_id, str)
        or not source_record_id.strip()
        or len(source_record_id) > 200
    ):
        source_record_id = ""
    raw_payload_hash = extra.get("raw_payload_hash")
    if (
        not isinstance(raw_payload_hash, str)
        or len(raw_payload_hash) != 64
        or any(character not in "0123456789abcdef" for character in raw_payload_hash)
    ):
        raw_payload_hash = ""
    return source_record_id, raw_payload_hash


class QuoteSnapshotRepository:
    """ORM-backed repository for real-time quote snapshots."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the fixed transaction identity used by this repository."""

        return "django:default"

    @staticmethod
    def _from_model(m: QuoteSnapshotModel) -> QuoteSnapshot:
        extra = m.extra if isinstance(m.extra, Mapping) else {}
        persisted_extra = dict(extra)
        if m.source_record_id:
            persisted_extra["source_record_id"] = m.source_record_id
        if m.raw_payload_hash:
            persisted_extra["raw_payload_hash"] = m.raw_payload_hash
        metric_evidence_payload = extra.get("change_pct_source_contract")
        metric_evidence = (
            QuoteChangePctEvidence.from_payload(metric_evidence_payload)
            if m.change_pct is not None
            else None
        )
        if m.change_pct is None and metric_evidence_payload is not None:
            raise ValueError("Quote metric evidence exists without a canonical change_pct")
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
            change_pct=m.change_pct,
            change_pct_evidence=metric_evidence,
            contract_version=m.contract_version,
            schema_version=m.schema_version,
            source=m.source,
            extra=persisted_extra,
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

        for quote in quotes:
            if quote.change_pct is None:
                continue
            storage_value = quote_change_pct_storage_value(Fraction(quote.change_pct))
            if storage_value != quote.change_pct:
                raise ValueError(
                    "quote change_pct is not exactly representable by the canonical storage field"
                )

        rows: list[QuoteSnapshotModel] = []
        for quote in quotes:
            extra = dict(quote.extra)
            source_record_id, raw_payload_hash = _quote_transport_identity(extra)
            if quote.change_pct_evidence is None:
                extra.pop("change_pct_source_contract", None)
            else:
                extra["change_pct_source_contract"] = quote.change_pct_evidence.to_dict()
            row = QuoteSnapshotModel(
                asset_code=quote.asset_code,
                snapshot_at=quote.snapshot_at,
                source=quote.source,
                current_price=quote.current_price,
                fetched_at=quote.fetched_at,
                open=quote.open,
                high=quote.high,
                low=quote.low,
                prev_close=quote.prev_close,
                volume=quote.volume,
                amount=quote.amount,
                bid=quote.bid,
                ask=quote.ask,
                change_pct=quote.change_pct,
                source_record_id=source_record_id,
                raw_payload_hash=raw_payload_hash,
                extra=extra,
                ingested_run_id=quote.ingested_run_id or None,
            )
            if quote.contract_version is not None and quote.schema_version is not None:
                row.contract_version = quote.contract_version
                row.schema_version = quote.schema_version
            rows.append(row)
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
                "change_pct",
                "source_record_id",
                "raw_payload_hash",
                "extra",
                "contract_version",
                "schema_version",
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

    def list_asset_codes_with_observation_on_date(
        self,
        asset_codes: tuple[str, ...],
        observation_date: date,
    ) -> tuple[str, ...]:
        """Return requested assets with any persisted observation on one China-market date."""

        if not asset_codes:
            return ()
        observed_from = cn_market_date_start_utc(observation_date)
        observed_until = cn_market_date_start_utc(observation_date + timedelta(days=1))
        rows = QuoteSnapshotModel._default_manager.filter(
            asset_code__in=asset_codes,
            snapshot_at__gte=observed_from,
            snapshot_at__lt=observed_until,
        ).values_list("asset_code", flat=True)
        return tuple(sorted({str(asset_code) for asset_code in rows}))


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
