"""
Feedparser RSS Adapter

使用feedparser库解析RSS源。

优点：
- 成熟稳定，兼容性好
- 自动处理各种RSS格式
- 支持编码检测
- API简单易用

缺点：
- 项目已不再活跃更新
- 不支持HTTP/2
- 同步阻塞
"""

import logging
from datetime import datetime
from typing import List, Optional

from django.utils import timezone

try:
    import requests
except ImportError:
    requests = None

try:
    import feedparser
except ImportError:
    feedparser = None
    raise ImportError("feedparser is required. Install it with: pip install feedparser")

from ...domain.entities import ProxyConfig, RSSSourceConfig
from .rss_adapter import BaseRSSAdapter, RSSFetchError, RSSItem, RSSParseError

logger = logging.getLogger(__name__)


class FeedparserAdapter(BaseRSSAdapter):
    """
    feedparser适配器实现

    使用feedparser库抓取和解析RSS内容
    """

    source_name = "feedparser"

    def fetch(self, source_config: RSSSourceConfig) -> list[RSSItem]:
        """
        抓取RSS源

        Args:
            source_config: RSS源配置

        Returns:
            List[RSSItem]: RSS条目列表

        Raises:
            RSSFetchError: 抓取失败
            RSSParseError: 解析失败
        """
        if feedparser is None:
            raise RSSFetchError("feedparser is not installed")

        try:
            # 检查是否需要使用代理
            # proxy_config 存在本身就表示代理已启用（见 _orm_to_domain_config）
            proxy_dict = None
            if source_config.proxy_config:
                # 构建 HTTP 代理 URL
                proxy_type = source_config.proxy_config.proxy_type or 'http'
                proxy_url = f"{proxy_type}://"
                if source_config.proxy_config.username and source_config.proxy_config.password:
                    proxy_url += f"{source_config.proxy_config.username}:{source_config.proxy_config.password}@"
                proxy_url += f"{source_config.proxy_config.host}:{source_config.proxy_config.port}"

                proxy_dict = {'http': proxy_url, 'https': proxy_url}
                logger.info(f"Using proxy for {source_config.url}: {proxy_dict}")

            # 如果配置了代理且 requests 可用，先用 requests 获取内容
            if proxy_dict and requests:
                try:
                    response = requests.get(
                        source_config.url,
                        proxies=proxy_dict,
                        headers={'User-Agent': 'AgomTradePro-RSS-Bot/1.0'},
                        timeout=30
                    )
                    response.raise_for_status()
                    # 将获取的内容传给 feedparser 解析
                    feed = feedparser.parse(response.content)
                except requests.RequestException as e:
                    logger.warning(f"Failed to fetch with proxy: {e}, trying direct connection")
                    feed = feedparser.parse(source_config.url)
            else:
                # 直接使用 feedparser（会自动处理重定向和编码）
                feed = feedparser.parse(
                    source_config.url,
                    request_headers={
                        'User-Agent': 'AgomTradePro-RSS-Bot/1.0'
                    }
                )

            # 检查是否解析成功
            if feed.bozo and feed.bozo_exception:
                logger.warning(f"Feed parsing warning for {source_config.url}: {feed.bozo_exception}")

            # 检查是否有entries
            if not hasattr(feed, 'entries') or len(feed.entries) == 0:
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

        except Exception as e:
            logger.error(f"Failed to fetch RSS from {source_config.url}: {e}", exc_info=True)
            raise RSSFetchError(f"Failed to fetch RSS: {e}")

    def _parse_entry(self, entry, source_name: str) -> RSSItem | None:
        """
        解析单个RSS条目

        Args:
            entry: feedparser entry对象
            source_name: 源名称

        Returns:
            Optional[RSSItem]: 解析后的RSS条目
        """
        # 解析标题
        title = entry.get('title', '')
        if not title:
            logger.warning("Entry missing title, skipping")
            return None

        # 解析链接
        link = entry.get('link', '')
        if not link:
            logger.warning("Entry missing link, skipping")
            return None

        # 解析发布日期
        pub_date = self._parse_pub_date(entry)

        # 解析描述
        description = entry.get('description', '') or entry.get('summary', '')

        # 解析guid
        guid = entry.get('guid', '')

        # 解析作者
        author = entry.get('author', '')

        return RSSItem(
            title=title,
            link=link,
            pub_date=pub_date,
            description=description,
            guid=guid,
            author=author,
            source=source_name
        )

    def _parse_pub_date(self, entry) -> datetime:
        """
        解析发布日期

        Args:
            entry: feedparser entry对象

        Returns:
            datetime: 发布日期时间
        """
        # feedparser会自动解析各种日期格式
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6])
            except (TypeError, ValueError):
                pass

        if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
            try:
                return datetime(*entry.updated_parsed[:6])
            except (TypeError, ValueError):
                pass

        # 默认使用当前时间
        return timezone.now()
