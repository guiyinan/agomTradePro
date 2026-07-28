"""
东方财富资金流向数据解析器

将 AKShare 资金流向 DataFrame 行解析为标准 CapitalFlowSnapshot。
"""

import logging
from datetime import date, datetime

from apps.data_center.infrastructure.market_gateway_entities import CapitalFlowSnapshot
from shared.numeric import safe_float

from ._contracts import ExternalRowProtocol

logger = logging.getLogger(__name__)

_PARSER_EXCEPTIONS = (
    ArithmeticError,
    AttributeError,
    LookupError,
    TypeError,
    ValueError,
)


def _parse_date(value: object) -> date | None:
    """安全地将值解析为 date"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_akshare_capital_flow_row(
    row: ExternalRowProtocol,
    stock_code: str,
) -> CapitalFlowSnapshot | None:
    """将 ak.stock_individual_fund_flow() 的一行解析为 CapitalFlowSnapshot

    AKShare 资金流向字段（来自东方财富）:
    - 日期
    - 主力净流入-净额
    - 主力净流入-净占比
    - 超大单净流入-净额
    - 大单净流入-净额
    - 中单净流入-净额
    - 小单净流入-净额

    Args:
        row: 资金流向 DataFrame 的一行
        stock_code: Tushare 格式的股票代码

    Returns:
        CapitalFlowSnapshot 或 None
    """
    try:
        trade_date = _parse_date(row.get("日期"))
        if trade_date is None:
            logger.warning("无法解析 %s 的资金流向日期", stock_code)
            return None

        main_net_inflow = safe_float(row.get("主力净流入-净额"))
        main_net_ratio = safe_float(row.get("主力净流入-净占比"))
        if main_net_inflow is None or main_net_ratio is None:
            logger.warning("资金流向主字段无效: %s", stock_code)
            return None

        return CapitalFlowSnapshot(
            stock_code=stock_code,
            trade_date=trade_date,
            main_net_inflow=main_net_inflow,
            main_net_ratio=main_net_ratio,
            super_large_net_inflow=safe_float(row.get("超大单净流入-净额"), default=0.0),
            large_net_inflow=safe_float(row.get("大单净流入-净额"), default=0.0),
            medium_net_inflow=safe_float(row.get("中单净流入-净额"), default=0.0),
            small_net_inflow=safe_float(row.get("小单净流入-净额"), default=0.0),
            source="eastmoney",
        )
    except _PARSER_EXCEPTIONS as exc:
        logger.warning(
            "Eastmoney capital-flow parsing failed; stock_code=%s; exception_type=%s",
            stock_code,
            type(exc).__name__,
        )
        return None
