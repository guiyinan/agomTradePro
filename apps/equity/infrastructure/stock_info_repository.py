"""Stock info, naming, and universe queries for the equity stock repository.

This module owns the `StockInfoRepositoryMixin` slice of
`DjangoStockRepository`. Shared helpers and dependency wiring live in
`stock_repository.py`; do not import the compatibility facade here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests
from django.utils import timezone

from apps.data_center.domain.protocols import (
    AssetRepositoryProtocol,
    FinancialFactRepositoryProtocol,
    PriceBarRepositoryProtocol,
    QuoteSnapshotRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)
from apps.data_center.infrastructure.models import AssetMasterModel, PriceBarModel
from apps.equity.domain.entities import StockInfo

from .models import StockInfoModel

logger = logging.getLogger(__name__)


class StockInfoRepositoryMixin:
    """Stock master info, display-name resolution, and universe listing."""

    _EASTMONEY_QUOTE_URL: str
    _EASTMONEY_METADATA_FIELDS: str
    _dc_asset_repo: AssetRepositoryProtocol
    _dc_financial_repo: FinancialFactRepositoryProtocol
    _dc_price_bar_repo: PriceBarRepositoryProtocol
    _dc_quote_repo: QuoteSnapshotRepositoryProtocol
    _dc_valuation_repo: ValuationFactRepositoryProtocol

    if TYPE_CHECKING:

        def _build_stock_code_candidates(self, stock_code: str) -> list[str]: ...

        def _infer_exchange_from_market(self, market: str) -> str: ...

        def _infer_exchange_from_stock_code(self, stock_code: str) -> str: ...

        def _infer_market_from_stock_code(self, stock_code: str) -> str: ...

        def _to_eastmoney_secid(self, stock_code: str) -> str: ...

    def get_stock_info(self, stock_code: str) -> StockInfo | None:
        """
        获取单个股票的基本信息

        Args:
            stock_code: 股票代码

        Returns:
            StockInfo 或 None
        """
        dc_info = self._get_stock_info_from_data_center(stock_code)
        if dc_info is not None:
            return dc_info

        for candidate in self._build_stock_code_candidates(stock_code):
            model = StockInfoModel._default_manager.filter(stock_code=candidate).first()
            if model is not None:
                return StockInfo(
                    stock_code=model.stock_code,
                    name=model.name,
                    sector=model.sector,
                    market=model.market,
                    list_date=model.list_date,
                )
        fallback_info = self._get_minimal_stock_info_from_data_center(stock_code)
        if fallback_info is not None:
            return fallback_info
        return None

    def get_listing_exchange(self, stock_code: str) -> str:
        """Resolve the primary listing exchange for the given stock code."""

        for candidate in self._build_stock_code_candidates(stock_code):
            asset = self._dc_asset_repo.get_by_code(candidate)
            if asset is not None:
                return asset.exchange.value

        stock_info = self.get_stock_info(stock_code)
        if stock_info is not None:
            return self._infer_exchange_from_market(stock_info.market)
        return self._infer_exchange_from_stock_code(stock_code)

    def resolve_stock_names(self, stock_codes: list[str]) -> dict[str, str]:
        """批量解析股票名称。"""
        normalized_codes = [str(code).upper() for code in stock_codes if code]
        if not normalized_codes:
            return {}

        requested_codes = list(dict.fromkeys(normalized_codes))
        candidate_codes = {
            candidate
            for code in requested_codes
            for candidate in self._build_stock_code_candidates(code)
        }
        models = StockInfoModel._default_manager.filter(stock_code__in=list(candidate_codes))
        model_map = {model.stock_code.upper(): model for model in models}

        resolved: dict[str, str] = {}
        for requested_code in requested_codes:
            for candidate in self._build_stock_code_candidates(requested_code):
                model = model_map.get(candidate.upper())
                if model is not None and model.name:
                    resolved[requested_code] = model.name
                    break
            if requested_code not in resolved:
                data_center_name = self._resolve_stock_name_from_data_center(requested_code)
                if data_center_name:
                    resolved[requested_code] = data_center_name
        return resolved

    def _resolve_stock_name_from_data_center(self, stock_code: str) -> str:
        """Resolve a stock display name from data_center asset master data."""

        name = self._read_stock_name_from_data_center(stock_code)
        if name:
            return name

        try:
            from apps.data_center.infrastructure.asset_master_backfill import (
                AssetMasterBackfillService,
            )

            AssetMasterBackfillService().backfill_codes(
                self._build_stock_code_candidates(stock_code),
                include_remote=True,
            )
        except Exception as exc:
            logger.debug("Asset master read-through backfill failed for %s: %s", stock_code, exc)

        return self._read_stock_name_from_data_center(stock_code)

    def _read_stock_name_from_data_center(self, stock_code: str) -> str:
        """Read a stock display name from existing data_center asset master rows."""

        for candidate in self._build_stock_code_candidates(stock_code):
            asset = self._dc_asset_repo.get_by_code(candidate)
            if asset is None or not asset.is_active:
                continue
            name = str(asset.short_name or asset.name or "").strip()
            if name:
                return name
        return ""

    def get_stock_count_by_sector(self, sector: str) -> int:
        """
        获取指定行业的股票数量

        Args:
            sector: 行业名称

        Returns:
            股票数量
        """
        return StockInfoModel._default_manager.filter(sector=sector, is_active=True).count()

    def get_all_sectors(self) -> list[str]:
        """
        获取所有行业列表

        Returns:
            行业名称列表
        """
        sectors = (
            StockInfoModel._default_manager.filter(is_active=True)
            .values_list("sector", flat=True)
            .distinct()
        )

        return list(sectors)

    def list_active_stock_codes(
        self,
        limit: int | None = None,
        stock_codes: list[str] | None = None,
    ) -> list[str]:
        """
        获取所有活跃股票代码列表

        用于批量扫描等场景，避免构造完整实体。

        Args:
            limit: 数量限制（可选）
            stock_codes: 指定股票代码列表（可选）

        Returns:
            股票代码列表
        """
        target_date = timezone.localdate()
        codes: list[str] = []
        seen_codes: set[str] = set()

        # Keep legacy active-stock semantics for existing local equity flows.
        queryset = StockInfoModel._default_manager.filter(is_active=True)

        if stock_codes:
            normalized_codes = [str(code).strip().upper() for code in stock_codes if code]
            queryset = queryset.filter(stock_code__in=normalized_codes)
        else:
            normalized_codes = []

        local_codes = queryset.values_list("stock_code", flat=True).order_by("stock_code")
        for raw_code in local_codes:
            normalized = str(raw_code or "").strip().upper()
            if normalized and normalized not in seen_codes:
                codes.append(normalized)
                seen_codes.add(normalized)

        # Expand the default sync / quality universe to the canonical stocks that
        # currently have price coverage in Data Center, matching Alpha's visible pool.
        asset_queryset = AssetMasterModel._default_manager.filter(
            is_active=True,
            asset_type="stock",
            exchange__in=["SSE", "SZSE", "BSE"],
        )
        if normalized_codes:
            asset_queryset = asset_queryset.filter(code__in=normalized_codes)
        canonical_codes = list(asset_queryset.values_list("code", flat=True))
        if canonical_codes:
            price_covered_codes = (
                PriceBarModel._default_manager.filter(
                    bar_date__lte=target_date,
                    asset_code__in=canonical_codes,
                )
                .values_list("asset_code", flat=True)
                .distinct()
                .order_by("asset_code")
            )
            for raw_code in price_covered_codes:
                normalized = str(raw_code or "").strip().upper()
                if normalized and normalized not in seen_codes:
                    codes.append(normalized)
                    seen_codes.add(normalized)

        if limit:
            return codes[:limit]

        return codes

    def _get_stock_info_from_data_center(self, stock_code: str) -> StockInfo | None:
        asset = self._dc_asset_repo.get_by_code(stock_code)
        if asset is None:
            return None

        market_map = {
            "SSE": "SH",
            "SZSE": "SZ",
            "BSE": "BJ",
        }
        market = market_map.get(
            asset.exchange.value, self._infer_market_from_stock_code(asset.code)
        )
        return StockInfo(
            stock_code=asset.code,
            name=asset.short_name or asset.name,
            sector=asset.sector or asset.industry or "",
            market=market,
            list_date=asset.list_date,
        )

    def _get_minimal_stock_info_from_data_center(self, stock_code: str) -> StockInfo | None:
        candidate_code = None

        latest_quote = self._dc_quote_repo.get_latest(stock_code)
        if latest_quote is not None:
            candidate_code = latest_quote.asset_code
        else:
            latest_bar = self._dc_price_bar_repo.get_latest(stock_code)
            if latest_bar is not None:
                candidate_code = latest_bar.asset_code
            else:
                latest_valuation = self._dc_valuation_repo.get_latest(stock_code)
                if latest_valuation is not None:
                    candidate_code = latest_valuation.asset_code
                else:
                    latest_financial = self._dc_financial_repo.get_latest(stock_code)
                    if latest_financial is not None:
                        candidate_code = latest_financial.asset_code

        if candidate_code is None:
            return None

        return StockInfo(
            stock_code=candidate_code,
            name=candidate_code,
            sector="",
            market=self._infer_market_from_stock_code(candidate_code),
            list_date=None,
        )

    def _get_stock_info_from_eastmoney(self, stock_code: str) -> StockInfo | None:
        params = {
            "secid": self._to_eastmoney_secid(stock_code),
            "fields": self._EASTMONEY_METADATA_FIELDS,
            "invt": "2",
            "fltt": "1",
        }
        try:
            with requests.Session() as session:
                session.trust_env = False
                session.headers.update(
                    {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/133.0.0.0 Safari/537.36"
                        ),
                        "Accept": "application/json,text/plain,*/*",
                        "Referer": "https://quote.eastmoney.com/",
                    }
                )
                response = session.get(
                    self._EASTMONEY_QUOTE_URL,
                    params=params,
                    timeout=15,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("Failed to fetch remote stock info for %s: %s", stock_code, exc)
            return None

        data = payload.get("data") or {}
        raw_price = data.get("f43")
        if raw_price in (None, "", "-"):
            return None

        remote_name = str(data.get("f58") or "").strip() or stock_code
        return StockInfo(
            stock_code=stock_code,
            name=remote_name,
            sector="",
            market=self._infer_market_from_stock_code(stock_code),
            list_date=None,
        )


__all__ = ["StockInfoRepositoryMixin"]
