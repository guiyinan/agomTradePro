"""
RSS Adapter - Base Protocol and Exception Classes

定义RSS适配器的接口协议。
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Protocol
from datetime import datetime

from ...domain.entities import RSSItem, RSSSourceConfig, ProxyConfig


class RSSAdapterError(Exception):
    """RSS适配器异常基类"""
    pass


class RSSFetchError(RSSAdapterError):
    """RSS抓取失败"""
    pass


class RSSParseError(RSSAdapterError):
    """RSS解析失败"""
    pass


class RSSAdapterProtocol(Protocol):
    """
    RSS适配器协议

    所有RSS适配器必须实现此协议。
    """

    source_name: str

    def fetch(self, source_config: RSSSourceConfig) -> List[RSSItem]:
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
        ...


class BaseRSSAdapter(ABC):
    """
    RSS适配器基类

    提供通用的辅助方法。
    """

    source_name: str = "base"

    def fetch(self, source_config: RSSSourceConfig) -> List[RSSItem]:
        """默认实现：子类必须覆盖"""
        raise NotImplementedError

    def _build_proxy_dict(self, proxy_config: Optional[ProxyConfig]) -> Optional[dict]:
        """
        构建代理配置字典

        Args:
            proxy_config: 代理配置

        Returns:
            Optional[dict]: 代理字典，格式如 {'http': 'http://host:port', 'https': 'https://host:port'}
        """
        if not proxy_config:
            return None

        proxy_url = f"{proxy_config.proxy_type}://"
        if proxy_config.username and proxy_config.password:
            proxy_url += f"{proxy_config.username}:{proxy_config.password}@"
        proxy_url += f"{proxy_config.host}:{proxy_config.port}"

        return {'http': proxy_url, 'https': proxy_url}

    def _parse_rss_date(self, date_str: str) -> datetime:
        """
        解析RSS日期格式（RFC 2822）

        Args:
            date_str: 日期字符串

        Returns:
            datetime: 解析后的日期时间
        """
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.now()

    def _get_dedup_key(self, item: RSSItem) -> str:
        """
        获取去重键

        优先级：guid > link > title+pubDate

        Args:
            item: RSS条目

        Returns:
            str: 去重键
        """
        if item.guid:
            return f"guid:{item.guid}"
        elif item.link:
            return f"link:{item.link}"
        else:
            import hashlib
            title_hash = hashlib.md5(item.title.encode()).hexdigest()
            return f"title:{title_hash}:{item.pub_date.isoformat()}"
