"""
统一价格服务

将 market_data 模块的多数据源能力封装成单一价格入口，
供 simulated_trading / account / decision 等模块统一调用。
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from apps.fund.infrastructure.adapters.hybrid_fund_adapter import HybridFundAdapter
from apps.market_data.application.registry_factory import get_registry
from apps.market_data.domain.entities import HistoricalPriceBar, QuoteSnapshot
from apps.market_data.domain.enums import DataCapability
from core.exceptions import DataFetchError


@dataclass(frozen=True)
class PriceLookupResult:
    requested_code: str
    normalized_code: str
    price: float
    as_of: date | None
    source: str
    freshness: str
    is_fallback: bool = False


class UnifiedPriceService:
    """价格中台统一入口。"""

    def __init__(self) -> None:
        self._registry = get_registry()
        self._fund_adapter: HybridFundAdapter | None = None

    @property
    def fund_adapter(self) -> HybridFundAdapter:
        if self._fund_adapter is None:
            self._fund_adapter = HybridFundAdapter()
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

        if code.startswith(("8", "4")):
            return f"{code}.BJ"
        if code.startswith(("5", "6")):
            return f"{code}.SH"
        if code.startswith(("0", "1", "2", "3")):
            return f"{code}.SZ"

        # 场外基金保留裸码给后续 fund adapter 判断
        if asset_type == "fund":
            return code
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
            f"在 {trade_date.isoformat()} 的历史价格"
            if trade_date is not None
            else "的最新价格"
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
                return PriceLookupResult(
                    requested_code=asset_code,
                    normalized_code=normalized_code,
                    price=historical.close,
                    as_of=historical.trade_date,
                    source=historical.source,
                    freshness="historical",
                    is_fallback=historical.source != "eastmoney",
                )

            if self._should_use_fund_nav(normalized_code, asset_type=asset_type):
                fund_nav = self._get_fund_nav_price(
                    normalized_code,
                    trade_date,
                    asset_type=asset_type,
                )
                if fund_nav is not None:
                    return PriceLookupResult(
                        requested_code=asset_code,
                        normalized_code=normalized_code,
                        price=fund_nav["price"],
                        as_of=fund_nav["as_of"],
                        source=fund_nav["source"],
                        freshness="historical",
                        is_fallback=fund_nav["source"] != "akshare_fund",
                    )
            return None

        quote = self._get_realtime_quote(normalized_code)
        if quote is not None:
            return PriceLookupResult(
                requested_code=asset_code,
                normalized_code=normalized_code,
                price=float(quote.price),
                as_of=None,
                source=quote.source,
                freshness="realtime",
                is_fallback=quote.source != "eastmoney",
            )

        recent_close = self._get_recent_close(normalized_code)
        if recent_close is not None:
            return PriceLookupResult(
                requested_code=asset_code,
                normalized_code=normalized_code,
                price=recent_close.close,
                as_of=recent_close.trade_date,
                source=recent_close.source,
                freshness="close_fallback",
                is_fallback=True,
            )

        if self._should_use_fund_nav(normalized_code, asset_type=asset_type):
            fund_nav = self._get_fund_nav_price(
                normalized_code,
                None,
                asset_type=asset_type,
            )
            if fund_nav is not None:
                return PriceLookupResult(
                    requested_code=asset_code,
                    normalized_code=normalized_code,
                    price=fund_nav["price"],
                    as_of=fund_nav["as_of"],
                    source=fund_nav["source"],
                    freshness="close_fallback",
                    is_fallback=True,
                )

        return None

    def _get_realtime_quote(self, normalized_code: str) -> QuoteSnapshot | None:
        snapshots = self._registry.call_with_failover(
            DataCapability.REALTIME_QUOTE,
            lambda provider: provider.get_quote_snapshots([normalized_code]),
        )
        if not snapshots:
            return None
        return snapshots[0]

    def _get_historical_price(
        self,
        normalized_code: str,
        trade_date: date,
    ) -> HistoricalPriceBar | None:
        date_str = trade_date.strftime("%Y%m%d")
        bars = self._registry.call_with_failover(
            DataCapability.HISTORICAL_PRICE,
            lambda provider: provider.get_historical_prices(
                normalized_code,
                start_date=date_str,
                end_date=date_str,
            ),
        )
        if not bars:
            return None
        return bars[-1]

    def _get_recent_close(self, normalized_code: str) -> HistoricalPriceBar | None:
        end_date = date.today()
        start_date = end_date - timedelta(days=7)
        bars = self._registry.call_with_failover(
            DataCapability.HISTORICAL_PRICE,
            lambda provider: provider.get_historical_prices(
                normalized_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            ),
        )
        if not bars:
            return None
        return bars[-1]

    def _get_fund_nav_price(
        self,
        normalized_code: str,
        trade_date: date | None,
        asset_type: str | None,
    ) -> dict[str, object] | None:
        if not self._should_use_fund_nav(normalized_code, asset_type=asset_type):
            return None

        bare_code = normalized_code.split(".")[0]
        try:
            df = self.fund_adapter.fetch_fund_nav_em(bare_code)
        except Exception:
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
            price = float(Decimal(str(row[nav_col])))
        except Exception:
            return None

        return {
            "price": price,
            "as_of": date.fromisoformat(str(row[nav_date_col])),
            "source": "akshare_fund",
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
