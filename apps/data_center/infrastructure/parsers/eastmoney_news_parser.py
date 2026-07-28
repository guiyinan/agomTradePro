"""
东方财富股票新闻数据解析器

将 AKShare 新闻 DataFrame 行解析为标准 StockNewsItem。
"""

import hashlib
import logging
import math
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from apps.data_center.infrastructure.market_gateway_entities import StockNewsItem

from ._contracts import ExternalDataFrameProtocol

logger = logging.getLogger(__name__)

_MAX_NEWS_ITEMS = 500
_MAX_TITLE_LENGTH = 500
_MAX_CONTENT_LENGTH = 100_000
_MAX_URL_LENGTH = 2_048

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
    return content.strip()[:_MAX_CONTENT_LENGTH]


def _clean_title(value: object) -> str:
    """Return one bounded single-line title from an external cell."""

    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return ""
    return " ".join(str(value).split())[:_MAX_TITLE_LENGTH]


def _safe_url(value: object) -> str | None:
    """Return one bounded credential-free HTTP(S) news URL."""

    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > _MAX_URL_LENGTH or any(
        ord(character) < 32 or ord(character) == 127 for character in normalized
    ):
        return None
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return normalized


def _parse_datetime(value: object) -> datetime | None:
    """安全地解析时间字段"""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    s = str(value).strip()
    if not s or len(s) > 64 or any(ord(character) < 32 for character in s):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_akshare_news_rows(
    df: ExternalDataFrameProtocol | None,
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
    if (
        df is None
        or df.empty
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
    ):
        return []
    bounded_limit = min(limit, _MAX_NEWS_ITEMS)

    items: list[StockNewsItem] = []
    seen_ids: set[str] = set()

    for _, row in df.iterrows():
        title = _clean_title(row.get("新闻标题", ""))
        if not title:
            continue

        published_at = _parse_datetime(row.get("发布时间"))
        if published_at is None:
            logger.debug("跳过无法解析时间的新闻: %s", title[:30])
            continue

        news_id = _generate_news_id(stock_code, title, published_at.isoformat())
        if news_id in seen_ids:
            continue
        seen_ids.add(news_id)

        content = _clean_content(str(row.get("新闻内容", "")))
        url = _safe_url(row.get("新闻链接", ""))

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
        except ValueError as exc:
            logger.warning(
                "Skipping invalid Eastmoney news item; exception_type=%s",
                type(exc).__name__,
            )
            continue

        if len(items) >= bounded_limit:
            break

    return items
