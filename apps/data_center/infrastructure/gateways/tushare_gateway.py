"""
Tushare Gateway

将现有 Tushare 适配器包装为统一的 GatewayProviderProtocol。
支持 REALTIME_QUOTE 和 TECHNICAL_FACTORS 能力。
作为东方财富的备用数据源注册到 SourceRegistry。
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from apps.data_center.infrastructure.market_gateway_entities import (
    HistoricalPriceBar,
    QuoteSnapshot,
    TechnicalSnapshot,
)
from apps.data_center.infrastructure.market_gateway_enums import DataCapability
from apps.data_center.infrastructure.gateway_protocols import GatewayProviderProtocol

logger = logging.getLogger(__name__)

_SUPPORTED = {
    DataCapability.REALTIME_QUOTE,
    DataCapability.TECHNICAL_FACTORS,
    DataCapability.HISTORICAL_PRICE,
}


def _safe_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        return None if d != d else d
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return None if f != f else f
    except (ValueError, TypeError):
        return None


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


class TushareGateway(GatewayProviderProtocol):
    """Tushare 数据源 Provider

    注意：Tushare 免费版只能获取日线收盘数据，非真实时行情。
    适合作为东方财富的备用/校验源。
    """

    def provider_name(self) -> str:
        return "tushare"

    def supports(self, capability: DataCapability) -> bool:
        return capability in _SUPPORTED

    def get_quote_snapshots(
        self, stock_codes: list[str]
    ) -> list[QuoteSnapshot]:
        """从 Tushare 获取最新日线数据作为"准实时"行情"""
        try:
            from apps.equity.infrastructure.adapters import TushareStockAdapter

            adapter = TushareStockAdapter()
            results: list[QuoteSnapshot] = []

            from django.utils import timezone

            end_date = timezone.now().strftime("%Y%m%d")
            start_date = (timezone.now() - timedelta(days=5)).strftime("%Y%m%d")

            for code in stock_codes:
                try:
                    df = adapter.fetch_daily_data(
                        stock_code=code,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    if df is None or df.empty:
                        continue

                    latest = df.iloc[-1]
                    price = _safe_decimal(latest.get("close"))
                    if price is None or price <= 0:
                        continue

                    # 计算涨跌额/涨跌幅
                    pre_close = _safe_decimal(latest.get("pre_close"))
                    change = None
                    change_pct = None
                    if price and pre_close and pre_close > 0:
                        change = price - pre_close
                        change_pct = float(change / pre_close * 100)

                    results.append(
                        QuoteSnapshot(
                            stock_code=code,
                            price=price,
                            change=change,
                            change_pct=change_pct,
                            volume=_safe_int(latest.get("vol")),
                            amount=_safe_decimal(latest.get("amount")),
                            turnover_rate=_safe_float(latest.get("turnover_rate")),
                            high=_safe_decimal(latest.get("high")),
                            low=_safe_decimal(latest.get("low")),
                            open=_safe_decimal(latest.get("open")),
                            pre_close=pre_close,
                            source="tushare",
                        )
                    )
                except Exception:
                    logger.warning("Tushare 获取 %s 失败", code, exc_info=True)
                    continue

            logger.info("Tushare 行情: 请求 %d 只, 成功 %d 只", len(stock_codes), len(results))
            return results

        except Exception:
            logger.exception("Tushare gateway 批量行情失败")
            return []

    def get_technical_snapshot(
        self, stock_code: str
    ) -> TechnicalSnapshot | None:
        """从 Tushare 获取技术指标"""
        snapshots = self.get_quote_snapshots([stock_code])
        if not snapshots:
            return None
        q = snapshots[0]
        return TechnicalSnapshot(
            stock_code=stock_code,
            trade_date=date.today(),
            close=q.price,
            turnover_rate=q.turnover_rate,
            source="tushare",
        )

    def get_historical_prices(
        self,
        asset_code: str,
        start_date: str,
        end_date: str,
    ) -> list[HistoricalPriceBar]:
        """从 Tushare 获取历史 K 线"""
        try:
            from shared.infrastructure.tushare_client import create_tushare_pro_client

            pro = create_tushare_pro_client()

            code = asset_code.split(".")[0] if "." in asset_code else asset_code
            ts_code = self._to_tushare_code(code)
            df = None

            # ETF
            if code.startswith(("51", "15", "56", "58")):
                df = pro.fund_daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )

            # 指数
            if df is None or (hasattr(df, 'empty') and df.empty):
                if code.startswith(("000", "399")):
                    df = pro.index_daily(
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                    )

            # 股票
            if df is None or (hasattr(df, 'empty') and df.empty):
                df = pro.daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )

            if df is None or df.empty:
                return []

            df = df.sort_values("trade_date")
            bars: list[HistoricalPriceBar] = []
            for _, row in df.iterrows():
                try:
                    td = str(row["trade_date"])
                    bars.append(HistoricalPriceBar(
                        asset_code=code,
                        trade_date=date(int(td[:4]), int(td[4:6]), int(td[6:8])),
                        open=float(row.get("open", 0)),
                        high=float(row.get("high", 0)),
                        low=float(row.get("low", 0)),
                        close=float(row.get("close", 0)),
                        volume=_safe_int(row.get("vol")),
                        amount=_safe_float(row.get("amount")),
                        source="tushare",
                    ))
                except (ValueError, TypeError):
                    continue

            logger.info("Tushare 历史 K 线: %s 获取 %d 条", asset_code, len(bars))
            return bars

        except Exception:
            logger.exception("Tushare 历史 K 线获取失败: %s", asset_code)
            return []

    @staticmethod
    def _to_tushare_code(code: str) -> str:
        """纯数字代码转 Tushare 格式"""
        if "." in code:
            return code
        if code.startswith("6"):
            return f"{code}.SH"
        if code.startswith(("0", "3")):
            return f"{code}.SZ"
        if code.startswith("5") or code.startswith("15"):
            # ETF: 51xxxx → SH, 15xxxx → SZ
            if code.startswith(("51", "56", "58")):
                return f"{code}.SH"
            return f"{code}.SZ"
        return f"{code}.SH"
