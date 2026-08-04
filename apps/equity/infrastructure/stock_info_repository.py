"""Stock info, naming, and universe queries for the equity stock repository.

This module owns the `StockInfoRepositoryMixin` slice of
`DjangoStockRepository`. Shared helpers and dependency wiring live in
`stock_repository.py`; do not import the compatibility facade here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.data_center.application.public import (
    backfill_asset_master_codes_port,
    list_price_covered_codes,
)
from apps.data_center.domain.protocols import (
    AssetRepositoryProtocol,
    FinancialFactRepositoryProtocol,
    PriceBarRepositoryProtocol,
    QuoteSnapshotRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)
from apps.equity.domain.entities import StockInfo

logger = logging.getLogger(__name__)


class StockInfoRepositoryMixin:
    """Stock master info, display-name resolution, and universe listing."""

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
        return self._get_minimal_stock_info_from_data_center(stock_code)

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
        resolved: dict[str, str] = {}
        for requested_code in requested_codes:
            for candidate in self._build_stock_code_candidates(requested_code):
                asset = self._dc_asset_repo.get_by_code(candidate)
                if asset is not None and asset.is_active:
                    name = str(asset.short_name or asset.name or "").strip()
                    if name:
                        resolved[requested_code] = name
                        break
            if requested_code not in resolved:
                data_center_name = self._resolve_stock_name_from_data_center(requested_code)
                if data_center_name:
                    resolved[requested_code] = data_center_name
        return resolved

    def get_stock_master_rows(self, stock_codes: list[str]) -> dict[str, dict[str, str]]:
        """Return canonical asset-master metadata without reading market facts.

        Current/decision-facing callers must be able to resolve display metadata
        without accidentally loading an un-gated price, financial, or valuation
        row.  This deliberately uses only the canonical AssetMaster repository;
        fact reads belong to the publication-gated Data Center application port.
        """

        normalized_codes = [str(code).strip().upper() for code in stock_codes if code]
        if not normalized_codes:
            return {}

        market_map = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}
        rows: dict[str, dict[str, str]] = {}
        for requested_code in dict.fromkeys(normalized_codes):
            for candidate in self._build_stock_code_candidates(requested_code):
                asset = self._dc_asset_repo.get_by_code(candidate)
                if asset is None or not asset.is_active or asset.asset_type.value != "stock":
                    continue
                rows[requested_code] = {
                    "asset_code": asset.code.upper(),
                    "name": str(asset.short_name or asset.name or ""),
                    "sector": str(asset.sector or asset.industry or ""),
                    "market": market_map.get(asset.exchange.value, ""),
                }
                break
        return rows

    def _resolve_stock_name_from_data_center(self, stock_code: str) -> str:
        """Resolve a stock display name from data_center asset master data."""

        name = self._read_stock_name_from_data_center(stock_code)
        if name:
            return name

        try:
            backfill_asset_master_codes_port(
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
        normalized_sector = str(sector or "").strip()
        return sum(
            1
            for asset in self._dc_asset_repo.list_active()
            if asset.asset_type.value == "stock"
            and normalized_sector in {asset.sector.strip(), asset.industry.strip()}
        )

    def get_all_sectors(self) -> list[str]:
        """
        获取所有行业列表

        Returns:
            行业名称列表
        """
        sectors = {
            value.strip()
            for asset in self._dc_asset_repo.list_active()
            if asset.asset_type.value == "stock"
            for value in (asset.sector, asset.industry)
            if value and value.strip()
        }
        return sorted(sectors)

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

        requested_codes = [str(code).strip().upper() for code in (stock_codes or []) if code]
        normalized_codes = {
            candidate
            for code in requested_codes
            for candidate in self._build_stock_code_candidates(code)
        }
        canonical_assets = [
            asset
            for asset in self._dc_asset_repo.list_active()
            if asset.asset_type.value == "stock"
            and (not normalized_codes or asset.code.upper() in normalized_codes)
        ]
        canonical_assets.sort(key=lambda asset: asset.code)
        for asset in canonical_assets:
            normalized = asset.code.strip().upper()
            if normalized and normalized not in seen_codes:
                codes.append(normalized)
                seen_codes.add(normalized)

        # Include canonical stocks with current price coverage even when the
        # asset-master list is populated by an upstream provider asynchronously.
        covered_codes = list_price_covered_codes(target_date)
        for raw_code in covered_codes:
            normalized = str(raw_code or "").strip().upper()
            if not normalized_codes or normalized in normalized_codes:
                if normalized not in seen_codes:
                    codes.append(normalized)
                    seen_codes.add(normalized)

        if limit:
            return codes[:limit]

        return codes

    def _get_stock_info_from_data_center(self, stock_code: str) -> StockInfo | None:
        asset = self._dc_asset_repo.get_by_code(stock_code)
        if asset is None or not asset.is_active or asset.asset_type.value != "stock":
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

__all__ = ["StockInfoRepositoryMixin"]
