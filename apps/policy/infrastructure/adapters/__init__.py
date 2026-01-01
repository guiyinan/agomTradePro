"""
Policy Data Adapters

政策数据适配器模块，用于从外部数据源获取政策事件。
"""

from .base import PolicyAdapterProtocol
from .news_adapter import NewsPolicyAdapter

# RSS Adapters
from .rss_adapter import RSSAdapterProtocol, BaseRSSAdapter, RSSAdapterError, RSSFetchError, RSSParseError
from .feedparser_adapter import FeedparserAdapter

# Content Extractors
from .content_extractor import (
    ContentExtractorProtocol,
    BaseContentExtractor,
    ReadabilityExtractor,
    BeautifulSoupExtractor,
    HybridContentExtractor,
    ContentExtractorError,
    create_content_extractor,
)

__all__ = [
    'PolicyAdapterProtocol',
    'NewsPolicyAdapter',
    # RSS Adapters
    'RSSAdapterProtocol',
    'BaseRSSAdapter',
    'RSSAdapterError',
    'RSSFetchError',
    'RSSParseError',
    'FeedparserAdapter',
    # Content Extractors
    'ContentExtractorProtocol',
    'BaseContentExtractor',
    'ReadabilityExtractor',
    'BeautifulSoupExtractor',
    'HybridContentExtractor',
    'ContentExtractorError',
    'create_content_extractor',
]
