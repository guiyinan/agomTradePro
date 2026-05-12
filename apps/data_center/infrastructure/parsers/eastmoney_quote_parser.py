"""
东方财富行情数据解析器

将 AKShare / 东方财富原始 DataFrame 行解析为标准 QuoteSnapshot。
站点字段变更只需修改本文件。
"""

import logging
from decimal import Decimal, InvalidOperation

import pandas

from apps.data_center.infrastructure.market_gateway_entities import QuoteSnapshot

logger = logging.getLogger(__name__)


def _safe_decimal(value: object) -> Decimal | None:
    """安全地将值转换为 Decimal"""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if d != d:  # NaN check
            return None
        return d
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_float(value: object) -> float | None:
    """安全地将值转换为 float"""
    if value is None:
        return None
    try:
        f = float(value)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None


def _safe_int(value: object) -> int | None:
    """安全地将值转换为 int"""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def parse_akshare_spot_row(
    row: "pandas.Series",  # type: ignore[name-defined]
    stock_code_tushare: str,
) -> QuoteSnapshot | None:
    """将 ak.stock_zh_a_spot_em() 的一行解析为 QuoteSnapshot

    Args:
        row: AKShare 实时行情 DataFrame 的一行
        stock_code_tushare: Tushare 格式的股票代码（如 000001.SZ）

    Returns:
        QuoteSnapshot 或 None（解析失败时）
    """
    try:
        price = _safe_decimal(row.get("最新价"))
        if price is None or price <= 0:
            logger.warning(
                "无法解析 %s 的最新价: %s", stock_code_tushare, row.get("最新价")
            )
            return None

        return QuoteSnapshot(
            stock_code=stock_code_tushare,
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
            source="eastmoney",
        )
    except Exception:
        logger.exception("解析行情数据失败: %s", stock_code_tushare)
        return None
