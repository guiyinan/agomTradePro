"""
Policy Data Adapters

政策数据适配器模块，用于从外部数据源获取政策事件。
"""

from .base import PolicyAdapterProtocol

# Content Extractors
from .content_extractor import (
    BaseContentExtractor,
    BeautifulSoupExtractor,
    ContentExtractorError,
    ContentExtractorProtocol,
    HybridContentExtractor,
    ReadabilityExtractor,
    create_content_extractor,
)
from .feedparser_adapter import FeedparserAdapter
from .news_adapter import NewsPolicyAdapter

# RSS Adapters
from .rss_adapter import (
    BaseRSSAdapter,
    RSSAdapterError,
    RSSAdapterProtocol,
    RSSFetchError,
    RSSParseError,
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
