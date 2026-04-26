"""Synchronise asset master coverage and local price bars for Alpha cache assets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from core.integration.alpha_cache import (
    collect_alpha_cache_codes,
    normalize_alpha_cached_code,
)
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure.asset_master_backfill import AssetMasterBackfillService
from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import AKShareEastMoneyGateway
from apps.data_center.infrastructure.gateways.tencent_gateway import TencentGateway
from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway
from apps.data_center.infrastructure.gateway_protocols import GatewayProviderProtocol
from apps.data_center.infrastructure.models import PriceBarModel
from apps.data_center.infrastructure.repositories import PriceBarRepository


@dataclass(frozen=True)
class AlphaPriceCoverageSyncReport:
    """Summary of one Alpha price coverage sync run."""

    requested_codes: list[str]
    synced_codes: list[str]
    empty_codes: list[str]
    unresolved_codes: list[str]
    total_bars: int
    start_date: date
    end_date: date

    def to_dict(self) -> dict[str, object]:
        """Return a serialisable report payload."""
        return {
            "requested_codes": self.requested_codes,
            "requested_count": len(self.requested_codes),
            "synced_codes": self.synced_codes,
            "synced_count": len(self.synced_codes),
            "empty_codes": self.empty_codes,
            "unresolved_codes": self.unresolved_codes,
            "total_bars": self.total_bars,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }


class AlphaPriceCoverageSyncService:
    """Backfill asset master and daily price bars for Alpha cache assets."""

    def __init__(
        self,
        *,
        backfill_service: AssetMasterBackfillService | None = None,
        gateways: Iterable[GatewayProviderProtocol] | None = None,
        price_repo: PriceBarRepository | None = None,
    ) -> None:
        self._backfill_service = backfill_service or AssetMasterBackfillService()
        self._gateways = list(gateways or self._build_default_gateways())
        self._price_repo = price_repo or PriceBarRepository()

    def collect_codes_from_alpha_cache(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        extra_codes: Iterable[str] = (),
    ) -> list[str]:
        """Collect canonical asset codes from cached Alpha score payloads."""
        return collect_alpha_cache_codes(
            start_date=start_date,
            end_date=end_date,
            extra_codes=extra_codes,
        )

    def sync_from_alpha_cache(
        self,
        *,
        start_date: date,
        end_date: date,
        include_remote: bool = True,
        extra_codes: Iterable[str] = (),
    ) -> AlphaPriceCoverageSyncReport:
        """Sync asset master and price bars for assets referenced by Alpha cache."""
        codes = self.collect_codes_from_alpha_cache(
            start_date=start_date,
            end_date=end_date,
            extra_codes=extra_codes,
        )
        return self.sync_codes(
            codes=codes,
            start_date=start_date,
            end_date=end_date,
            include_remote=include_remote,
        )

    def sync_codes(
        self,
        *,
        codes: Iterable[str],
        start_date: date,
        end_date: date,
        include_remote: bool = True,
    ) -> AlphaPriceCoverageSyncReport:
        """Sync asset master and price bars for an explicit code list."""
        requested_codes = self._normalize_codes(codes)
        if not requested_codes:
            return AlphaPriceCoverageSyncReport(
                requested_codes=[],
                synced_codes=[],
                empty_codes=[],
                unresolved_codes=[],
                total_bars=0,
                start_date=start_date,
                end_date=end_date,
            )

        backfill_report = self._backfill_service.backfill_codes(
            requested_codes,
            include_remote=include_remote,
        )

        synced_codes: list[str] = []
        empty_codes: list[str] = []
        total_bars = 0
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        for code in requested_codes:
            bars = self._fetch_historical_prices(code, start_str, end_str)
            if not bars:
                empty_codes.append(code)
                continue
            self._replace_managed_bars(code, start_date, end_date)
            stored_count = self._price_repo.bulk_upsert(
                [
                    PriceBar(
                        asset_code=normalize_asset_code(bar.asset_code, bar.source),
                        bar_date=bar.trade_date,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=float(bar.volume) if bar.volume is not None else None,
                        amount=bar.amount,
                        source=bar.source,
                        adjustment=PriceAdjustment.NONE,
                    )
                    for bar in bars
                ]
            )
            total_bars += stored_count
            synced_codes.append(code)

        unresolved_codes = [
            code
            for code in backfill_report.unresolved_codes
            if code not in synced_codes
        ]
        return AlphaPriceCoverageSyncReport(
            requested_codes=requested_codes,
            synced_codes=synced_codes,
            empty_codes=empty_codes,
            unresolved_codes=unresolved_codes,
            total_bars=total_bars,
            start_date=start_date,
            end_date=end_date,
        )

    @staticmethod
    def _normalize_codes(codes: Iterable[str]) -> list[str]:
        normalized_codes: list[str] = []
        seen: set[str] = set()
        for code in codes:
            normalized = normalize_alpha_cached_code(code)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_codes.append(normalized)
        return normalized_codes

    @staticmethod
    def _build_default_gateways() -> list[GatewayProviderProtocol]:
        return [
            TushareGateway(),
            AKShareEastMoneyGateway(request_interval_sec=0.8),
        ]

    def _fetch_historical_prices(
        self,
        asset_code: str,
        start_date: str,
        end_date: str,
    ) -> list:
        for gateway in self._gateways:
            bars = gateway.get_historical_prices(asset_code, start_date, end_date)
            if bars:
                return bars
        return []

    @staticmethod
    def _replace_managed_bars(asset_code: str, start_date: date, end_date: date) -> None:
        PriceBarModel.objects.filter(
            asset_code=asset_code,
            bar_date__gte=start_date,
            bar_date__lte=end_date,
            source__in=["akshare", "eastmoney", "tushare", "tencent", "alpha_price_sync"],
        ).delete()
