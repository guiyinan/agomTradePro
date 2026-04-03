"""
东方财富股票新闻数据解析器

将 AKShare 新闻 DataFrame 行解析为标准 StockNewsItem。
"""

import hashlib
import logging
import re
from datetime import UTC, datetime, timezone
from typing import List, Optional

from apps.market_data.domain.entities import StockNewsItem

logger = logging.getLogger(__name__)

# 需要过滤的内容模式（广告、免责声明等）
_JUNK_PATTERNS = [
    re.compile(r"免责声明"),
    re.compile(r"以上内容仅供参考"),
    re.compile(r"不构成投资建议"),
    re.compile(r"风险自担"),
]


def _generate_news_id(stock_code: str, title: str, published_at: str) -> str:
    """基于内容生成去重用的 news_id"""
    raw = f"{stock_code}:{title}:{published_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _clean_content(content: str) -> str:
    """清洗新闻内容：去广告、免责声明等"""
    if not content:
        return ""
    for pattern in _JUNK_PATTERNS:
        content = pattern.sub("", content)
    return content.strip()


def _parse_datetime(value: object) -> datetime | None:
    """安全地解析时间字段"""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_akshare_news_rows(
    df: "pandas.DataFrame",  # type: ignore[name-defined]
    stock_code: str,
    limit: int = 20,
) -> list[StockNewsItem]:
    """将 ak.stock_news_em() 的 DataFrame 解析为 StockNewsItem 列表

    AKShare 新闻字段（来自东方财富）:
    - 新闻标题
    - 新闻内容
    - 发布时间
    - 文章来源
    - 新闻链接

    Args:
        df: 新闻 DataFrame
        stock_code: Tushare 格式的股票代码
        limit: 最多返回条数

    Returns:
        去重且清洗后的 StockNewsItem 列表
    """
    if df is None or df.empty:
        return []

    items: list[StockNewsItem] = []
    seen_ids: set = set()

    for _, row in df.iterrows():
        title = str(row.get("新闻标题", "")).strip()
        if not title:
            continue

        published_str = str(row.get("发布时间", ""))
        published_at = _parse_datetime(row.get("发布时间"))
        if published_at is None:
            logger.debug("跳过无法解析时间的新闻: %s", title[:30])
            continue

        news_id = _generate_news_id(stock_code, title, published_str)
        if news_id in seen_ids:
            continue
        seen_ids.add(news_id)

        content = _clean_content(str(row.get("新闻内容", "")))
        url = str(row.get("新闻链接", "")).strip() or None

        try:
            item = StockNewsItem(
                stock_code=stock_code,
                news_id=news_id,
                title=title,
                content=content,
                published_at=published_at,
                url=url,
                source="eastmoney",
            )
            items.append(item)
        except ValueError as e:
            logger.warning("跳过无效新闻: %s - %s", title[:30], e)
            continue

        if len(items) >= limit:
            break

    return items
