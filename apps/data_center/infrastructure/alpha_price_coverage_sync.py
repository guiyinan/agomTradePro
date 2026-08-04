"""Synchronise asset master coverage and local price bars for Alpha cache assets."""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from django.db import transaction

from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure.asset_master_backfill import AssetMasterBackfillService
from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
    AKShareEastMoneyGateway,
)
from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway
from apps.data_center.infrastructure.market_gateway_entities import HistoricalPriceBar
from apps.data_center.infrastructure.market_gateway_protocol import MarketGatewayProtocol
from apps.data_center.infrastructure.models import PriceBarModel
from apps.data_center.infrastructure.repositories import PriceBarRepository
from core.integration.alpha_cache import collect_alpha_cache_codes, normalize_alpha_cached_code
from core.integration.asset_master_sources import build_legacy_asset_master_source

logger = logging.getLogger(__name__)

_GATEWAY_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


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
        gateways: Iterable[MarketGatewayProtocol] | None = None,
        price_repo: PriceBarRepository | None = None,
    ) -> None:
        self._backfill_service = backfill_service or AssetMasterBackfillService(
            source_provider=build_legacy_asset_master_source()
        )
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
        self._validate_date_range(start_date, end_date)
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
        self._validate_date_range(start_date, end_date)
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
            raw_bars = self._fetch_historical_prices(code, start_str, end_str)
            bars = self._normalize_price_bars(
                asset_code=code,
                bars=raw_bars,
                start_date=start_date,
                end_date=end_date,
            )
            if not bars:
                empty_codes.append(code)
                continue
            with transaction.atomic():
                self._replace_managed_bars(code, start_date, end_date)
                stored_count = self._price_repo.bulk_upsert(bars)
            total_bars += stored_count
            synced_codes.append(code)

        unresolved_codes = [
            code for code in backfill_report.unresolved_codes if code not in synced_codes
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
    def _build_default_gateways() -> list[MarketGatewayProtocol]:
        return [
            TushareGateway(),
            AKShareEastMoneyGateway(request_interval_sec=0.8),
        ]

    def _fetch_historical_prices(
        self,
        asset_code: str,
        start_date: str,
        end_date: str,
    ) -> list[HistoricalPriceBar]:
        for gateway in self._gateways:
            try:
                bars = gateway.get_historical_prices(asset_code, start_date, end_date)
            except _GATEWAY_EXCEPTIONS as exc:
                logger.warning(
                    "Alpha price gateway failed; asset_code=%s; gateway_type=%s; "
                    "exception_type=%s",
                    asset_code,
                    type(gateway).__name__,
                    type(exc).__name__,
                )
                continue
            if not isinstance(bars, list) or not all(
                isinstance(bar, HistoricalPriceBar) for bar in bars
            ):
                logger.warning(
                    "Alpha price gateway returned invalid payload; asset_code=%s; "
                    "gateway_type=%s",
                    asset_code,
                    type(gateway).__name__,
                )
                continue
            if bars:
                return bars
        return []

    @staticmethod
    def _validate_date_range(start_date: date, end_date: date) -> None:
        if type(start_date) is not date or type(end_date) is not date:
            raise TypeError("alpha_price_date_invalid")
        if start_date > end_date:
            raise ValueError("alpha_price_date_range_invalid")

    @staticmethod
    def _normalize_price_bars(
        *,
        asset_code: str,
        bars: Iterable[HistoricalPriceBar],
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]:
        normalized: dict[tuple[date, str], PriceBar] = {}
        for bar in bars:
            source = str(bar.source).strip()
            if not source or len(source) > 50 or not source.isprintable():
                continue
            try:
                normalized_code = normalize_asset_code(bar.asset_code, source)
            except (TypeError, ValueError):
                continue
            if normalized_code != asset_code:
                continue
            if type(bar.trade_date) is not date or not start_date <= bar.trade_date <= end_date:
                continue
            if not all(
                AlphaPriceCoverageSyncService._is_positive_finite(value)
                for value in (bar.open, bar.high, bar.low, bar.close)
            ):
                continue
            if bar.high < max(bar.open, bar.low, bar.close):
                continue
            if bar.low > min(bar.open, bar.high, bar.close):
                continue
            if not AlphaPriceCoverageSyncService._is_optional_nonnegative_finite(bar.volume):
                continue
            if not AlphaPriceCoverageSyncService._is_optional_nonnegative_finite(bar.amount):
                continue
            normalized[(bar.trade_date, source)] = PriceBar(
                asset_code=normalized_code,
                bar_date=bar.trade_date,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume) if bar.volume is not None else None,
                amount=float(bar.amount) if bar.amount is not None else None,
                source=source,
                adjustment=PriceAdjustment.NONE,
            )
        return [normalized[key] for key in sorted(normalized)]

    @staticmethod
    def _is_positive_finite(value: object) -> bool:
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value > 0
        )

    @staticmethod
    def _is_optional_nonnegative_finite(value: object) -> bool:
        return value is None or (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
        )

    @staticmethod
    def _replace_managed_bars(asset_code: str, start_date: date, end_date: date) -> None:
        PriceBarModel.objects.filter(
            asset_code=asset_code,
            bar_date__gte=start_date,
            bar_date__lte=end_date,
            source__in=["akshare", "eastmoney", "tushare", "tencent", "alpha_price_sync"],
        ).delete()
