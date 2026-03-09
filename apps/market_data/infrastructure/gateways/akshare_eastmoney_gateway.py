"""
AKShare 东方财富 Gateway

通过 AKShare 封装访问东方财富数据。
如果 AKShare 失效，可替换为直接 HTTP 请求的 gateway，
而不需要修改 parser 和业务逻辑。
"""

import logging
import time
from typing import Dict, List, Optional

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
from apps.market_data.infrastructure.parsers.eastmoney_quote_parser import (
    parse_akshare_spot_row,
)

logger = logging.getLogger(__name__)

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
        """批量获取实时行情（东方财富实时行情接口）"""
        self._throttle()
        try:
            import akshare as ak

            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                logger.warning("AKShare stock_zh_a_spot_em 返回空数据")
                return []

            df["代码"] = df["代码"].astype(str).str.strip()

            # 构建 AKShare 代码 → Tushare 代码映射
            ak_to_ts: Dict[str, str] = {
                _to_akshare_code(c): c for c in stock_codes
            }

            results: List[QuoteSnapshot] = []
            for ak_code, ts_code in ak_to_ts.items():
                matched = df[df["代码"] == ak_code]
                if matched.empty:
                    continue
                snapshot = parse_akshare_spot_row(matched.iloc[0], ts_code)
                if snapshot is not None:
                    results.append(snapshot)

            logger.info(
                "东方财富行情: 请求 %d 只, 成功 %d 只",
                len(stock_codes),
                len(results),
            )
            return results

        except Exception:
            logger.exception("获取东方财富实时行情失败")
            return []

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
