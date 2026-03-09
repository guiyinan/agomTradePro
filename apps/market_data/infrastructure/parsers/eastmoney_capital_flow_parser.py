"""
东方财富资金流向数据解析器

将 AKShare 资金流向 DataFrame 行解析为标准 CapitalFlowSnapshot。
"""

import logging
from datetime import date, datetime
from typing import Optional

from apps.market_data.domain.entities import CapitalFlowSnapshot

logger = logging.getLogger(__name__)


def _safe_float(value: object) -> float:
    """安全地将值转换为 float，失败返回 0.0"""
    if value is None:
        return 0.0
    try:
        f = float(value)
        if f != f:  # NaN
            return 0.0
        return f
    except (ValueError, TypeError):
        return 0.0


def _parse_date(value: object) -> Optional[date]:
    """安全地将值解析为 date"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_akshare_capital_flow_row(
    row: "pandas.Series",  # type: ignore[name-defined]
    stock_code: str,
) -> Optional[CapitalFlowSnapshot]:
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

        return CapitalFlowSnapshot(
            stock_code=stock_code,
            trade_date=trade_date,
            main_net_inflow=_safe_float(row.get("主力净流入-净额")),
            main_net_ratio=_safe_float(row.get("主力净流入-净占比")),
            super_large_net_inflow=_safe_float(row.get("超大单净流入-净额")),
            large_net_inflow=_safe_float(row.get("大单净流入-净额")),
            medium_net_inflow=_safe_float(row.get("中单净流入-净额")),
            small_net_inflow=_safe_float(row.get("小单净流入-净额")),
            source="eastmoney",
        )
    except Exception:
        logger.exception("解析资金流向数据失败: %s", stock_code)
        return None
