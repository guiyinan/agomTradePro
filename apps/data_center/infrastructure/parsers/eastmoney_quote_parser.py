"""
东方财富行情数据解析器

将 AKShare / 东方财富原始 DataFrame 行解析为标准 QuoteSnapshot。
站点字段变更只需修改本文件。
"""

import logging
from decimal import Decimal, InvalidOperation

from apps.data_center.infrastructure.market_gateway_entities import QuoteSnapshot
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


def _safe_decimal(value: object) -> Decimal | None:
    """安全地将值转换为 Decimal"""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if not d.is_finite():
            return None
        return d
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_int(value: object) -> int | None:
    """安全地将值转换为 int"""
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            return None
        normalized = safe_float(value)
        return int(normalized) if normalized is not None else None
    except (OverflowError, ValueError, TypeError):
        return None


def _nonnegative_decimal(value: object) -> Decimal | None:
    """Return a finite non-negative Decimal or None for a damaged field."""

    normalized = _safe_decimal(value)
    if normalized is None or normalized < 0:
        return None
    return normalized


def _nonnegative_int(value: object) -> int | None:
    """Return a non-negative integer or None for a damaged field."""

    normalized = _safe_int(value)
    if normalized is None or normalized < 0:
        return None
    return normalized


def parse_akshare_spot_row(
    row: ExternalRowProtocol,
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
            logger.warning("无法解析 %s 的最新价: %s", stock_code_tushare, row.get("最新价"))
            return None

        return QuoteSnapshot(
            stock_code=stock_code_tushare,
            price=price,
            change=_safe_decimal(row.get("涨跌额")),
            change_pct=safe_float(row.get("涨跌幅")),
            volume=_nonnegative_int(row.get("成交量")),
            amount=_nonnegative_decimal(row.get("成交额")),
            turnover_rate=safe_float(row.get("换手率")),
            volume_ratio=safe_float(row.get("量比")),
            high=_nonnegative_decimal(row.get("最高")),
            low=_nonnegative_decimal(row.get("最低")),
            open=_nonnegative_decimal(row.get("今开")),
            pre_close=_nonnegative_decimal(row.get("昨收")),
            source="eastmoney",
        )
    except _PARSER_EXCEPTIONS as exc:
        logger.warning(
            "Eastmoney quote parsing failed; stock_code=%s; exception_type=%s",
            stock_code_tushare,
            type(exc).__name__,
        )
        return None
