"""
Feedparser RSS Adapter

使用 feedparser + requests 抓取和解析 RSS 源。

关键设计：始终通过 requests.get() 获取内容（可控超时），
再用 feedparser.parse() 解析字节内容，避免 feedparser 直接发起
无超时控制的网络请求。
"""

import logging
from datetime import datetime

from django.utils import timezone

try:
    import requests
except ImportError:
    requests = None

try:
    import feedparser
except ImportError:
    feedparser = None
    raise ImportError("feedparser is required. Install it with: pip install feedparser") from None

from ...domain.entities import RSSSourceConfig
from .rss_adapter import BaseRSSAdapter, RSSFetchError, RSSItem

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = "AgomTradePro-RSS-Bot/1.0"


class FeedparserAdapter(BaseRSSAdapter):
    """
    feedparser适配器实现

    始终通过 requests 获取 RSS 内容（可控超时/重试/代理），
    再使用 feedparser 解析字节内容。
    """

    source_name = "feedparser"

    def fetch(self, source_config: RSSSourceConfig) -> list[RSSItem]:
        if feedparser is None:
            raise RSSFetchError("feedparser is not installed")
        if requests is None:
            raise RSSFetchError("requests is not installed")

        timeout = source_config.timeout_seconds
        max_retries = source_config.retry_times

        proxy_dict = self._build_proxy_dict(source_config.proxy_config)

        content = self._fetch_with_retries(source_config.url, proxy_dict, timeout, max_retries)

        feed = feedparser.parse(content)

        if feed.bozo and feed.bozo_exception:
            logger.warning(f"Feed parsing warning for {source_config.url}: {feed.bozo_exception}")

        if not hasattr(feed, "entries") or len(feed.entries) == 0:
            logger.warning(f"No entries found in RSS feed: {source_config.url}")
            return []

        items = []
        for entry in feed.entries:
            try:
                item = self._parse_entry(entry, source_config.name)
                if item:
                    items.append(item)
            except Exception as e:
                logger.warning(f"Failed to parse entry from {source_config.name}: {e}")
                continue

        logger.info(f"Fetched {len(items)} items from {source_config.name}")
        return items

    def _fetch_with_retries(
        self,
        url: str,
        proxy_dict: dict | None,
        timeout: int,
        max_retries: int,
    ) -> bytes:
        """
        通过 requests 获取 RSS 内容，支持重试。

        Args:
            url: RSS 源 URL
            proxy_dict: 代理配置
            timeout: 超时秒数
            max_retries: 最大重试次数

        Returns:
            bytes: RSS 原始内容

        Raises:
            RSSFetchError: 所有重试均失败
        """
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(
                    url,
                    proxies=proxy_dict,
                    headers={"User-Agent": _DEFAULT_USER_AGENT},
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.content

            except requests.Timeout as e:
                last_exc = e
                logger.warning(
                    f"RSS fetch timeout (attempt {attempt}/{max_retries}) for {url}: {e}"
                )
            except requests.RequestException as e:
                last_exc = e
                logger.warning(f"RSS fetch error (attempt {attempt}/{max_retries}) for {url}: {e}")

            if attempt < max_retries:
                import time

                time.sleep(min(attempt * 2, 10))

        raise RSSFetchError(f"Failed to fetch RSS after {max_retries} retries: {url} - {last_exc}")

    def _parse_entry(self, entry, source_name: str) -> RSSItem | None:
        title = entry.get("title", "")
        if not title:
            logger.warning("Entry missing title, skipping")
            return None

        link = entry.get("link", "")
        if not link:
            logger.warning("Entry missing link, skipping")
            return None

        pub_date = self._parse_pub_date(entry)
        description = entry.get("description", "") or entry.get("summary", "")
        guid = entry.get("guid", "")
        author = entry.get("author", "")

        return RSSItem(
            title=title,
            link=link,
            pub_date=pub_date,
            description=description,
            guid=guid,
            author=author,
            source=source_name,
        )

    def _parse_pub_date(self, entry) -> datetime:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6])
            except (TypeError, ValueError):
                pass

        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                return datetime(*entry.updated_parsed[:6])
            except (TypeError, ValueError):
                pass

        return timezone.now()
