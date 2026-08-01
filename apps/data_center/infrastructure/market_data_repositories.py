"""OHLCV price bar and real-time quote snapshot persistence."""

from __future__ import annotations

from datetime import date

from apps.data_center.domain.entities import PriceBar, QuoteSnapshot
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import PriceBarModel, QuoteSnapshotModel


class PriceBarRepository:
    """ORM-backed repository for OHLCV price bars."""

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
        )

    def get_bars(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
    ) -> list[PriceBar]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = PriceBarModel.objects.filter(asset_code=candidate)
            if start:
                qs = qs.filter(bar_date__gte=start)
            if end:
                qs = qs.filter(bar_date__lte=end)
            rows = list(qs.order_by("-bar_date")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(self, asset_code: str) -> PriceBar | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            m = PriceBarModel.objects.filter(asset_code=candidate).order_by("-bar_date").first()
            if m is not None:
                return self._from_model(m)
        return None

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
            )
            for bar in bars
        ]
        PriceBarModel._default_manager.bulk_create(
            models,
            batch_size=1_000,
            update_conflicts=True,
            update_fields=["open", "high", "low", "close", "volume", "amount"],
            unique_fields=["asset_code", "bar_date", "freq", "adjustment", "source"],
        )
        return len(models)


class QuoteSnapshotRepository:
    """ORM-backed repository for real-time quote snapshots."""

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
        )

    def get_latest(self, asset_code: str) -> QuoteSnapshot | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            m = (
                QuoteSnapshotModel.objects.filter(asset_code=candidate)
                .order_by("-snapshot_at")
                .first()
            )
            if m is not None:
                return self._from_model(m)
        return None

    def get_series(
        self,
        asset_code: str,
        snapshot_date: date | None = None,
        limit: int = 500,
    ) -> list[QuoteSnapshot]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = QuoteSnapshotModel.objects.filter(asset_code=candidate)
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
                },
            )
            count += 1
        return count

    def delete_all(self) -> int:
        """Delete all quote snapshots for an explicitly gated production rebuild."""

        deleted_count, _ = QuoteSnapshotModel.objects.all().delete()
        return int(deleted_count)
