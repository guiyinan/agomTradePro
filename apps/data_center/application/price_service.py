"""
Unified price service backed by data-center facts only.

This is the canonical price lookup entry for business modules.
"""

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, TypedDict, cast

from apps.data_center.composition import (
    get_fund_nav_repository,
    get_price_bar_repository,
    get_quote_snapshot_repository,
)
from apps.data_center.domain.entities import FundNavFact, PriceBar, QuoteSnapshot
from apps.data_center.domain.protocols import (
    FundNavRepositoryProtocol,
    PriceBarRepositoryProtocol,
    QuoteSnapshotRepositoryProtocol,
)
from core.exceptions import DataFetchError
from core.integration.data_center_business_sources import build_hybrid_fund_adapter

logger = logging.getLogger(__name__)


class FundPriceResult(TypedDict):
    """Validated fund price payload from a repository or external adapter."""

    price: float
    as_of: date
    source: str


@dataclass(frozen=True)
class PriceLookupResult:
    """Validated canonical price returned to business modules."""

    requested_code: str
    normalized_code: str
    price: float
    as_of: date | None
    source: str
    freshness: str
    is_fallback: bool = False

    def __post_init__(self) -> None:
        """Reject unusable prices and unauditable result metadata."""

        if not self.requested_code.strip() or not self.normalized_code.strip():
            raise ValueError("价格查询结果缺少资产代码")
        if isinstance(self.price, bool) or not math.isfinite(self.price) or self.price <= 0:
            raise ValueError("价格查询结果必须为正有限数")
        if self.as_of is not None and not isinstance(self.as_of, date):
            raise ValueError("价格查询结果日期无效")
        if not self.source.strip():
            raise ValueError("价格查询结果缺少数据来源")
        if self.freshness not in {"historical", "realtime", "close_fallback"}:
            raise ValueError("价格查询结果新鲜度类型无效")


class UnifiedPriceService:
    """Unified price lookup over standardized data-center repositories."""

    def __init__(self) -> None:
        self._fund_adapter: Any | None = None
        self._dc_price_repo: PriceBarRepositoryProtocol = get_price_bar_repository()
        self._dc_quote_repo: QuoteSnapshotRepositoryProtocol = get_quote_snapshot_repository()
        self._dc_fund_nav_repo: FundNavRepositoryProtocol = get_fund_nav_repository()

    @property
    def fund_adapter(self) -> Any:
        if self._fund_adapter is None:
            self._fund_adapter = build_hybrid_fund_adapter()
        return self._fund_adapter

    def normalize_asset_code(
        self,
        asset_code: str,
        asset_type: str | None = None,
    ) -> str:
        code = (asset_code or "").strip().upper()
        if not code:
            raise ValueError("asset_code 不能为空")

        if "." in code:
            return code

        if asset_type == "fund":
            return code

        if code.startswith(("8", "4")):
            return f"{code}.BJ"
        if code.startswith(("5", "6")):
            return f"{code}.SH"
        if code.startswith(("0", "1", "2", "3")):
            return f"{code}.SZ"

        return code

    def get_price(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> float | None:
        result = self.get_price_result(
            asset_code=asset_code,
            trade_date=trade_date,
            asset_type=asset_type,
        )
        return result.price if result else None

    def get_latest_price(
        self,
        asset_code: str,
        asset_type: str | None = None,
    ) -> float | None:
        return self.get_price(asset_code=asset_code, trade_date=None, asset_type=asset_type)

    def require_price(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> float:
        return self.require_price_result(
            asset_code=asset_code,
            trade_date=trade_date,
            asset_type=asset_type,
        ).price

    def require_latest_price(
        self,
        asset_code: str,
        asset_type: str | None = None,
    ) -> float:
        return self.require_price(
            asset_code=asset_code,
            trade_date=None,
            asset_type=asset_type,
        )

    def require_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> PriceLookupResult:
        normalized_code = self.normalize_asset_code(asset_code, asset_type=asset_type)
        result = self.get_price_result(
            asset_code=asset_code,
            trade_date=trade_date,
            asset_type=asset_type,
        )
        if result is not None:
            return result

        when_label = (
            f"在 {trade_date.isoformat()} 的历史价格" if trade_date is not None else "的最新价格"
        )
        raise DataFetchError(
            message=f"无法获取 {asset_code} {when_label}",
            code="PRICE_UNAVAILABLE",
            details={
                "requested_code": asset_code,
                "normalized_code": normalized_code,
                "trade_date": trade_date.isoformat() if trade_date is not None else None,
                "asset_type": asset_type,
            },
        )

    def get_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> PriceLookupResult | None:
        normalized_code = self.normalize_asset_code(asset_code, asset_type=asset_type)

        if trade_date is not None:
            historical = self._get_historical_price(normalized_code, trade_date)
            if historical is not None:
                result = self._build_price_result(
                    requested_code=asset_code,
                    normalized_code=normalized_code,
                    raw_price=historical.close,
                    as_of=historical.bar_date,
                    raw_source=historical.source,
                    freshness="historical",
                    is_fallback=False,
                )
                if result is not None:
                    return result

            if self._should_use_fund_nav(normalized_code, asset_type=asset_type):
                fund_nav = self._get_fund_nav_price(
                    normalized_code,
                    trade_date,
                    asset_type=asset_type,
                )
                if fund_nav is not None:
                    return self._build_price_result(
                        requested_code=asset_code,
                        normalized_code=normalized_code,
                        raw_price=fund_nav["price"],
                        as_of=fund_nav["as_of"],
                        raw_source=fund_nav["source"],
                        freshness="historical",
                        is_fallback=True,
                    )
            return None

        quote = self._get_realtime_quote(normalized_code)
        if quote is not None:
            result = self._build_price_result(
                requested_code=asset_code,
                normalized_code=normalized_code,
                raw_price=quote.current_price,
                as_of=None,
                raw_source=quote.source,
                freshness="realtime",
                is_fallback=False,
            )
            if result is not None:
                return result

        recent_close = self._get_recent_close(normalized_code)
        if recent_close is not None:
            result = self._build_price_result(
                requested_code=asset_code,
                normalized_code=normalized_code,
                raw_price=recent_close.close,
                as_of=recent_close.bar_date,
                raw_source=recent_close.source,
                freshness="close_fallback",
                is_fallback=True,
            )
            if result is not None:
                return result

        if self._should_use_fund_nav(normalized_code, asset_type=asset_type):
            fund_nav = self._get_fund_nav_price(
                normalized_code,
                None,
                asset_type=asset_type,
            )
            if fund_nav is not None:
                return self._build_price_result(
                    requested_code=asset_code,
                    normalized_code=normalized_code,
                    raw_price=fund_nav["price"],
                    as_of=fund_nav["as_of"],
                    raw_source=fund_nav["source"],
                    freshness="close_fallback",
                    is_fallback=True,
                )

        return None

    @staticmethod
    def _build_price_result(
        *,
        requested_code: str,
        normalized_code: str,
        raw_price: object,
        as_of: date | None,
        raw_source: object,
        freshness: str,
        is_fallback: bool,
    ) -> PriceLookupResult | None:
        """Build a canonical result only from positive, attributable prices."""

        if isinstance(raw_price, bool):
            return None
        try:
            price = float(cast(Any, raw_price))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(price) or price <= 0:
            return None
        if not isinstance(raw_source, str) or not raw_source.strip():
            return None
        return PriceLookupResult(
            requested_code=requested_code,
            normalized_code=normalized_code,
            price=price,
            as_of=as_of,
            source=raw_source.strip(),
            freshness=freshness,
            is_fallback=is_fallback,
        )

    def _get_realtime_quote(self, normalized_code: str) -> QuoteSnapshot | None:
        try:
            return self._dc_quote_repo.get_latest(normalized_code)
        except Exception as exc:
            logger.debug("Realtime quote lookup failed for %s: %s", normalized_code, exc)
            return None

    def _get_historical_price(self, normalized_code: str, trade_date: date) -> PriceBar | None:
        try:
            bars = self._dc_price_repo.get_bars(
                normalized_code,
                start=trade_date,
                end=trade_date,
                limit=1,
            )
            return bars[0] if bars else None
        except Exception as exc:
            logger.debug(
                "Historical price lookup failed for %s on %s: %s",
                normalized_code,
                trade_date,
                exc,
            )
            return None

    def _get_recent_close(self, normalized_code: str) -> PriceBar | None:
        try:
            return self._dc_price_repo.get_latest(normalized_code)
        except Exception as exc:
            logger.debug("Recent close lookup failed for %s: %s", normalized_code, exc)
            return None

    def _get_fund_nav_price(
        self,
        normalized_code: str,
        trade_date: date | None,
        asset_type: str | None,
    ) -> FundPriceResult | None:
        if not self._should_use_fund_nav(normalized_code, asset_type=asset_type):
            return None

        bare_code = normalized_code.split(".")[0]
        try:
            if trade_date is not None:
                facts = self._dc_fund_nav_repo.get_series(
                    bare_code,
                    start=trade_date,
                    end=trade_date,
                )
                if facts:
                    fact = facts[0]
                    result = self._fund_fact_price(fact)
                    if result is not None:
                        return result
            else:
                latest_fact = self._dc_fund_nav_repo.get_latest(bare_code)
                if latest_fact is not None:
                    result = self._fund_fact_price(latest_fact)
                    if result is not None:
                        return result
        except Exception as exc:
            logger.debug("Fund NAV repository lookup failed for %s: %s", bare_code, exc)

        try:
            df = self.fund_adapter.fetch_fund_nav_em(bare_code)
        except Exception as exc:
            logger.debug("Fund adapter lookup failed for %s: %s", bare_code, exc)
            return None
        if df is None or df.empty:
            return None

        nav_date_col = None
        for candidate in ("nav_date", "日期"):
            if candidate in df.columns:
                nav_date_col = candidate
                break
        nav_col = None
        for candidate in ("unit_nav", "净值"):
            if candidate in df.columns:
                nav_col = candidate
                break
        if nav_date_col is None or nav_col is None:
            return None

        working_df = df.copy()
        working_df[nav_date_col] = working_df[nav_date_col].astype(str)
        if trade_date is not None:
            matched = working_df[working_df[nav_date_col] == trade_date.isoformat()]
            if matched.empty:
                return None
            row = matched.iloc[-1]
        else:
            row = working_df.iloc[-1]

        try:
            price = float(row[nav_col])
            nav_date = date.fromisoformat(str(row[nav_date_col]))
        except (TypeError, ValueError) as exc:
            logger.debug("Fund NAV price parse failed for %s: %s", bare_code, exc)
            return None
        if not math.isfinite(price) or price <= 0:
            logger.debug("Fund NAV price is invalid for %s: %r", bare_code, price)
            return None

        return {
            "price": price,
            "as_of": nav_date,
            "source": "akshare_fund",
        }

    @staticmethod
    def _fund_fact_price(fact: FundNavFact) -> FundPriceResult | None:
        """Narrow a stored fund fact before exposing it as an executable price."""

        if (
            isinstance(fact.nav, bool)
            or not math.isfinite(fact.nav)
            or fact.nav <= 0
            or not fact.source.strip()
        ):
            return None
        return {
            "price": fact.nav,
            "as_of": fact.nav_date,
            "source": fact.source.strip(),
        }

    def _should_use_fund_nav(
        self,
        normalized_code: str,
        asset_type: str | None,
    ) -> bool:
        if normalized_code.endswith((".OF", ".OFC")):
            return True
        if normalized_code.endswith((".SH", ".SZ", ".BJ")):
            return False
        return asset_type == "fund"
