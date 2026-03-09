"""
Tushare Gateway

将现有 Tushare 适配器包装为统一的 MarketDataProviderProtocol。
支持 REALTIME_QUOTE 和 TECHNICAL_FACTORS 能力。
作为东方财富的备用数据源注册到 SourceRegistry。
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from apps.market_data.domain.entities import QuoteSnapshot, TechnicalSnapshot
from apps.market_data.domain.enums import DataCapability
from apps.market_data.domain.protocols import MarketDataProviderProtocol

logger = logging.getLogger(__name__)

_SUPPORTED = {DataCapability.REALTIME_QUOTE, DataCapability.TECHNICAL_FACTORS}


def _safe_decimal(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        return None if d != d else d
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        return None if f != f else f
    except (ValueError, TypeError):
        return None


def _safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


class TushareGateway(MarketDataProviderProtocol):
    """Tushare 数据源 Provider

    注意：Tushare 免费版只能获取日线收盘数据，非真实时行情。
    适合作为东方财富的备用/校验源。
    """

    def provider_name(self) -> str:
        return "tushare"

    def supports(self, capability: DataCapability) -> bool:
        return capability in _SUPPORTED

    def get_quote_snapshots(
        self, stock_codes: List[str]
    ) -> List[QuoteSnapshot]:
        """从 Tushare 获取最新日线数据作为"准实时"行情"""
        try:
            from apps.equity.infrastructure.adapters.tushare_stock_adapter import (
                TushareStockAdapter,
            )

            adapter = TushareStockAdapter()
            results: List[QuoteSnapshot] = []

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
    ) -> Optional[TechnicalSnapshot]:
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
