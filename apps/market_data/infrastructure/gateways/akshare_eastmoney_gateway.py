"""
AKShare 东方财富 Gateway

通过 AKShare 封装访问东方财富数据。
如果 AKShare 失效，可替换为直接 HTTP 请求的 gateway，
而不需要修改 parser 和业务逻辑。
"""

import logging
import time
from decimal import Decimal, InvalidOperation
from typing import List, Optional

import requests

from apps.market_data.domain.entities import (
    CapitalFlowSnapshot,
    QuoteSnapshot,
    StockNewsItem,
    TechnicalSnapshot,
)
from apps.market_data.domain.enums import DataCapability
from apps.market_data.domain.protocols import MarketDataProviderProtocol
from apps.market_data.infrastructure.parsers.eastmoney_capital_flow_parser import (
    parse_akshare_capital_flow_row,
)
from apps.market_data.infrastructure.parsers.eastmoney_news_parser import (
    parse_akshare_news_rows,
)

logger = logging.getLogger(__name__)

_QUOTE_FIELDS = (
    "f19,f39,f43,f44,f45,f46,f47,f48,f49,f50,f57,f58,f59,f60,"
    "f71,f84,f85,f86,f92,f108,f116,f117,f152,f154,f161,f164,"
    "f167,f168,f169,f170,f171,f532,f600,f601"
)
_EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"

# 支持的能力集合
_SUPPORTED_CAPABILITIES = {
    DataCapability.REALTIME_QUOTE,
    DataCapability.CAPITAL_FLOW,
    DataCapability.STOCK_NEWS,
    DataCapability.TECHNICAL_FACTORS,
}


def _to_akshare_code(tushare_code: str) -> str:
    """将 Tushare 格式（000001.SZ）转换为 AKShare 纯数字格式（000001）"""
    if "." in tushare_code:
        return tushare_code.split(".")[0]
    return tushare_code


def _to_tushare_code(akshare_code: str, market_hint: str = "") -> str:
    """将 AKShare 纯数字格式转换为 Tushare 格式

    根据代码前缀推断市场：
    - 6 开头 → SH
    - 0/3 开头 → SZ
    - 8/4 开头 → BJ
    """
    code = akshare_code.strip()
    if "." in code:
        return code
    if code.startswith("6"):
        return f"{code}.SH"
    elif code.startswith(("0", "3")):
        return f"{code}.SZ"
    elif code.startswith(("8", "4")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _to_market_arg(stock_code: str) -> str:
    """将 Tushare 股票代码转换为东方财富资金流接口所需 market 参数。"""
    if stock_code.endswith(".SH"):
        return "sh"
    if stock_code.endswith(".BJ"):
        return "bj"
    return "sz"


def _to_secid(stock_code: str) -> str:
    """将 Tushare 股票代码转换为东方财富 secid。"""
    code = _to_akshare_code(stock_code)
    if stock_code.endswith(".SH"):
        return f"1.{code}"
    if stock_code.endswith(".BJ"):
        return f"0.{code}"
    return f"0.{code}"


def _safe_decimal(value: object, scale: int = 1) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        decimal_value = Decimal(str(value))
        if scale != 1:
            decimal_value /= Decimal(str(scale))
        return decimal_value
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_float(value: object, scale: int = 1) -> Optional[float]:
    decimal_value = _safe_decimal(value, scale=scale)
    return float(decimal_value) if decimal_value is not None else None


def _safe_int(value: object) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


class AKShareEastMoneyGateway(MarketDataProviderProtocol):
    """通过 AKShare 封装访问东方财富的 Provider

    职责：
    - 调用 AKShare API（底层为东方财富）
    - 字段映射交给 parser 层
    - 限流与重试
    - 错误隔离
    """

    def __init__(
        self,
        request_interval_sec: float = 0.5,
        batch_size: int = 500,
    ) -> None:
        self._request_interval = request_interval_sec
        self._batch_size = batch_size
        self._last_request_time: float = 0.0

    def provider_name(self) -> str:
        return "eastmoney"

    def supports(self, capability: DataCapability) -> bool:
        return capability in _SUPPORTED_CAPABILITIES

    # ------------------------------------------------------------------
    # REALTIME_QUOTE
    # ------------------------------------------------------------------

    def get_quote_snapshots(
        self, stock_codes: List[str]
    ) -> List[QuoteSnapshot]:
        """批量获取实时行情（东方财富单股接口）"""
        self._throttle()
        results: List[QuoteSnapshot] = []
        with requests.Session() as session:
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
            for stock_code in stock_codes:
                snapshot = self._fetch_quote_snapshot(session, stock_code)
                if snapshot is not None:
                    results.append(snapshot)
                self._throttle()

        logger.info(
            "东方财富行情: 请求 %d 只, 成功 %d 只",
            len(stock_codes),
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # CAPITAL_FLOW
    # ------------------------------------------------------------------

    def get_capital_flows(
        self, stock_code: str, period: str = "5d"
    ) -> List[CapitalFlowSnapshot]:
        """获取个股资金流向"""
        self._throttle()
        try:
            import akshare as ak

            ak_code = _to_akshare_code(stock_code)
            df = ak.stock_individual_fund_flow(
                stock=ak_code, market=_to_market_arg(stock_code)
            )
            if df is None or df.empty:
                logger.warning("AKShare 资金流向返回空数据: %s", stock_code)
                return []

            # 按 period 过滤天数
            days = self._parse_period_days(period)
            if days and len(df) > days:
                df = df.tail(days)

            results: List[CapitalFlowSnapshot] = []
            for _, row in df.iterrows():
                snapshot = parse_akshare_capital_flow_row(row, stock_code)
                if snapshot is not None:
                    results.append(snapshot)

            logger.info(
                "东方财富资金流向: %s 获取 %d 条", stock_code, len(results)
            )
            return results

        except Exception:
            logger.exception("获取东方财富资金流向失败: %s", stock_code)
            return []

    # ------------------------------------------------------------------
    # STOCK_NEWS
    # ------------------------------------------------------------------

    def get_stock_news(
        self, stock_code: str, limit: int = 20
    ) -> List[StockNewsItem]:
        """获取个股新闻"""
        self._throttle()
        try:
            import akshare as ak

            ak_code = _to_akshare_code(stock_code)
            df = ak.stock_news_em(symbol=ak_code)
            return parse_akshare_news_rows(df, stock_code, limit=limit)

        except Exception:
            logger.exception("获取东方财富股票新闻失败: %s", stock_code)
            return []

    # ------------------------------------------------------------------
    # TECHNICAL_FACTORS
    # ------------------------------------------------------------------

    def get_technical_snapshot(
        self, stock_code: str
    ) -> Optional[TechnicalSnapshot]:
        """获取技术指标快照

        turnover_rate 和 volume_ratio 来自实时行情，
        KDJ/BOLL 需要从历史日线计算，此处暂只提供行情内包含的字段。
        """
        snapshots = self.get_quote_snapshots([stock_code])
        if not snapshots:
            return None

        quote = snapshots[0]
        from datetime import date as date_type

        return TechnicalSnapshot(
            stock_code=stock_code,
            trade_date=date_type.today(),
            close=quote.price,
            turnover_rate=quote.turnover_rate,
            volume_ratio=quote.volume_ratio,
            source="eastmoney",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """简单限流：两次请求之间至少间隔 _request_interval 秒"""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._request_interval:
            time.sleep(self._request_interval - elapsed)
        self._last_request_time = time.monotonic()

    def _fetch_quote_snapshot(
        self,
        session: requests.Session,
        stock_code: str,
    ) -> Optional[QuoteSnapshot]:
        """通过东财单股接口获取一只股票的行情。"""
        params = {
            "secid": _to_secid(stock_code),
            "fields": _QUOTE_FIELDS,
            "invt": "2",
            "fltt": "1",
        }
        try:
            response = session.get(
                _EASTMONEY_QUOTE_URL,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.warning("获取东方财富单股行情失败: %s", stock_code, exc_info=True)
            return None

        data = payload.get("data") or {}
        price = _safe_decimal(data.get("f43"), scale=100)
        if price is None or price <= 0:
            return None

        return QuoteSnapshot(
            stock_code=stock_code,
            price=price,
            change=_safe_decimal(data.get("f169"), scale=100),
            change_pct=_safe_float(data.get("f170"), scale=100),
            volume=_safe_int(data.get("f47")),
            amount=_safe_decimal(data.get("f48")),
            turnover_rate=_safe_float(data.get("f168"), scale=100),
            volume_ratio=_safe_float(data.get("f50"), scale=100),
            high=_safe_decimal(data.get("f44"), scale=100),
            low=_safe_decimal(data.get("f45"), scale=100),
            open=_safe_decimal(data.get("f46"), scale=100),
            pre_close=_safe_decimal(data.get("f60"), scale=100),
            source="eastmoney",
        )

    @staticmethod
    def _parse_period_days(period: str) -> Optional[int]:
        """将 '5d', '10d' 格式解析为天数"""
        period = period.strip().lower()
        if period.endswith("d"):
            try:
                return int(period[:-1])
            except ValueError:
                return None
        return None
