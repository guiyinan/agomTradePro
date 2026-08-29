"""Canonical OHLCV price bar persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.market_time import cn_market_date_start_utc
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import PriceBarModel


class PriceBarRepository:
    """ORM-backed repository for OHLCV price bars."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the fixed transaction identity used by this repository."""

        return "django:default"

    @staticmethod
    def _from_model(m: PriceBarModel) -> PriceBar:
        return PriceBar(
            asset_code=m.asset_code,
            bar_date=m.bar_date,
            freq=m.freq,
            adjustment=PriceAdjustment(m.adjustment),
            open=float(m.open),
            high=float(m.high),
            low=float(m.low),
            close=float(m.close),
            volume=float(m.volume) if m.volume is not None else None,
            amount=float(m.amount) if m.amount is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
            ingested_run_id=str(m.ingested_run_id) if m.ingested_run_id else "",
        )

    def get_bars(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
        fact_pks: Sequence[str] | None = None,
    ) -> list[PriceBar]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = PriceBarModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            if start:
                qs = qs.filter(bar_date__gte=start)
            if end:
                qs = qs.filter(bar_date__lte=end)
            rows = list(qs.order_by("-bar_date")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(
        self,
        asset_code: str,
        fact_pks: Sequence[str] | None = None,
    ) -> PriceBar | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = PriceBarModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            m = qs.order_by("-bar_date").first()
            if m is not None:
                return self._from_model(m)
        return None

    def list_asset_codes(self, as_of: date | None = None) -> list[str]:
        """Return assets with canonical price facts through ``as_of``."""

        queryset = PriceBarModel.objects.all()
        if as_of is not None:
            queryset = queryset.filter(bar_date__lte=as_of)
        return list(queryset.order_by("asset_code").values_list("asset_code", flat=True).distinct())

    def bulk_upsert(self, bars: list[PriceBar]) -> int:
        if not bars:
            return 0
        models = [
            PriceBarModel(
                asset_code=bar.asset_code,
                bar_date=bar.bar_date,
                freq=bar.freq,
                adjustment=bar.adjustment.value,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                amount=bar.amount,
                source=bar.source,
                ingested_run_id=bar.ingested_run_id or None,
            )
            for bar in bars
        ]
        PriceBarModel._default_manager.bulk_create(
            models,
            batch_size=1_000,
            update_conflicts=True,
            update_fields=[
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "ingested_run_id",
            ],
            unique_fields=["asset_code", "bar_date", "freq", "adjustment", "source"],
        )
        return len(models)

    def list_publication_candidates(
        self, bars: Sequence[PriceBar]
    ) -> list[PublicationFactReference]:
        """Resolve written bars to exact rows without washing out ``bar_date``."""

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        for bar in bars:
            row = (
                PriceBarModel._default_manager.filter(
                    asset_code=bar.asset_code,
                    bar_date=bar.bar_date,
                    freq=bar.freq,
                    adjustment=bar.adjustment.value,
                    source=bar.source,
                )
                .order_by("id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            natural_key = (
                f"{row.asset_code}:{row.bar_date.isoformat()}:{row.freq}:"
                f"{row.adjustment}:{row.source}"
            )
            observed_at = cn_market_date_start_utc(row.bar_date)
            references.append(
                PublicationFactReference(
                    natural_key=natural_key,
                    source=row.source,
                    source_record_id=row.source_record_id or natural_key,
                    fact_table="data_center_price_bar",
                    fact_pk=fact_pk,
                    observed_at=observed_at,
                    raw_payload_hash=row.raw_payload_hash or _price_bar_payload_hash(row),
                    quality_status=row.quality_status,
                    revision_number=row.revision_number,
                )
            )
        return references


def _price_bar_payload_hash(row: PriceBarModel) -> str:
    """Return deterministic evidence for one persisted price bar."""

    payload = {
        "asset_code": row.asset_code,
        "bar_date": row.bar_date.isoformat(),
        "freq": row.freq,
        "adjustment": row.adjustment,
        "open": str(row.open),
        "high": str(row.high),
        "low": str(row.low),
        "close": str(row.close),
        "volume": str(row.volume) if row.volume is not None else None,
        "amount": str(row.amount) if row.amount is not None else None,
        "source": row.source,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = ["PriceBarRepository"]
