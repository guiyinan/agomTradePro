"""
AKShare 通用 Gateway

将现有 AKShare 通用行情能力包装为 MarketDataProviderProtocol。
与 AKShareEastMoneyGateway 的区别：这里是通用 AKShare 能力，
不绑定东方财富特定接口。

作为东方财富的备用数据源注册到 SourceRegistry。
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from apps.market_data.domain.entities import QuoteSnapshot, TechnicalSnapshot
from apps.market_data.domain.enums import DataCapability
from apps.market_data.domain.protocols import MarketDataProviderProtocol

logger = logging.getLogger(__name__)

_SUPPORTED = {DataCapability.REALTIME_QUOTE, DataCapability.TECHNICAL_FACTORS}


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


def _to_akshare_code(tushare_code: str) -> str:
    if "." in tushare_code:
        return tushare_code.split(".")[0]
    return tushare_code


def _to_tushare_code(ak_code: str) -> str:
    code = ak_code.strip()
    if "." in code:
        return code
    if code.startswith("6"):
        return f"{code}.SH"
    elif code.startswith(("0", "3")):
        return f"{code}.SZ"
    elif code.startswith(("8", "4")):
        return f"{code}.BJ"
    return f"{code}.SZ"


class AKShareGeneralGateway(MarketDataProviderProtocol):
    """AKShare 通用数据源 Provider

    使用 ak.stock_zh_a_spot_em() 获取全量 A 股实时行情。
    注意：该接口底层也可能来自东方财富，但被视为通用 AKShare 能力。
    当东方财富的专用 gateway 熔断时，此 provider 可作为备用。
    """

    def provider_name(self) -> str:
        return "akshare_general"

    def supports(self, capability: DataCapability) -> bool:
        return capability in _SUPPORTED

    def get_quote_snapshots(
        self, stock_codes: list[str]
    ) -> list[QuoteSnapshot]:
        """批量获取实时行情"""
        try:
            import akshare as ak

            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                logger.warning("AKShare stock_zh_a_spot_em 返回空数据")
                return []

            df["代码"] = df["代码"].astype(str).str.strip()

            ak_to_ts: dict[str, str] = {
                _to_akshare_code(c): c for c in stock_codes
            }

            results: list[QuoteSnapshot] = []
            for ak_code, ts_code in ak_to_ts.items():
                matched = df[df["代码"] == ak_code]
                if matched.empty:
                    continue
                row = matched.iloc[0]

                price = _safe_decimal(row.get("最新价"))
                if price is None or price <= 0:
                    continue

                results.append(
                    QuoteSnapshot(
                        stock_code=ts_code,
                        price=price,
                        change=_safe_decimal(row.get("涨跌额")),
                        change_pct=_safe_float(row.get("涨跌幅")),
                        volume=_safe_int(row.get("成交量")),
                        amount=_safe_decimal(row.get("成交额")),
                        turnover_rate=_safe_float(row.get("换手率")),
                        volume_ratio=_safe_float(row.get("量比")),
                        high=_safe_decimal(row.get("最高")),
                        low=_safe_decimal(row.get("最低")),
                        open=_safe_decimal(row.get("今开")),
                        pre_close=_safe_decimal(row.get("昨收")),
                        source="akshare_general",
                    )
                )

            logger.info(
                "AKShare 通用行情: 请求 %d 只, 成功 %d 只",
                len(stock_codes),
                len(results),
            )
            return results

        except Exception:
            logger.exception("AKShare 通用 gateway 行情失败")
            return []

    def get_technical_snapshot(
        self, stock_code: str
    ) -> TechnicalSnapshot | None:
        """从行情中提取技术指标"""
        snapshots = self.get_quote_snapshots([stock_code])
        if not snapshots:
            return None
        q = snapshots[0]
        return TechnicalSnapshot(
            stock_code=stock_code,
            trade_date=date.today(),
            close=q.price,
            turnover_rate=q.turnover_rate,
            volume_ratio=q.volume_ratio,
            source="akshare_general",
        )
