"""Policy-facing RSS adapter backed by the Data Center transport port."""

import logging
from datetime import UTC, datetime
from time import struct_time
from typing import Protocol

from django.utils import timezone

from apps.data_center.application.public import fetch_rss_news_feed

from ...domain.entities import RSSItem, RSSSourceConfig
from .rss_adapter import BaseRSSAdapter, RSSFetchError

logger = logging.getLogger(__name__)


class FeedEntryProtocol(Protocol):
    """Narrow third-party feed entry fields consumed by this adapter."""

    published_parsed: struct_time | None
    updated_parsed: struct_time | None

    def get(self, key: str, default: str = "") -> object:
        """Return one dynamically parsed feed field."""


class FeedparserAdapter(BaseRSSAdapter):
    """
    feedparser适配器实现

    网络抓取和 feedparser 解析由 Data Center Public Port 承担；Policy
    只负责将 canonical news fact 转成自己的分类输入实体。
    """

    source_name = "feedparser"

    def fetch(self, source_config: RSSSourceConfig) -> list[RSSItem]:
        proxy_dict = self._build_proxy_dict(source_config.proxy_config)
        try:
            facts = fetch_rss_news_feed(
                url=source_config.url,
                source_name=source_config.name,
                timeout_seconds=source_config.timeout_seconds,
                retry_times=source_config.retry_times,
                proxy_config=proxy_dict,
            )
        except (RSSFetchError, ValueError, RuntimeError) as exc:
            raise RSSFetchError(str(exc)) from exc

        return [
            RSSItem(
                title=fact.title,
                link=fact.url,
                pub_date=fact.published_at,
                description=fact.summary or None,
                guid=fact.external_id or None,
                author=str(fact.extra.get("author") or "") or None,
                source=fact.source,
            )
            for fact in facts
        ]

    def _parse_entry(
        self,
        entry: FeedEntryProtocol,
        source_name: str,
    ) -> RSSItem | None:
        title = str(entry.get("title", "") or "").strip()
        if not title:
            logger.warning("Entry missing title, skipping")
            return None

        link = str(entry.get("link", "") or "").strip()
        if not link:
            logger.warning("Entry missing link, skipping")
            return None

        pub_date = self._parse_pub_date(entry)
        description = str(entry.get("description", "") or entry.get("summary", "") or "")
        guid = str(entry.get("guid", "") or "")
        author = str(entry.get("author", "") or "")

        return RSSItem(
            title=title,
            link=link,
            pub_date=pub_date,
            description=description,
            guid=guid,
            author=author,
            source=source_name,
        )

    def _parse_pub_date(self, entry: FeedEntryProtocol) -> datetime:
        if entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                pass

        if entry.updated_parsed:
            try:
                return datetime(*entry.updated_parsed[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                pass

        return timezone.now()
