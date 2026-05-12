"""
Content Extractor - 从HTML页面提取文章正文

支持多种提取策略：
1. BeautifulSoup4 - 基于启发式规则提取
2. readability-lxml - 基于阅读性算法提取
"""

import logging
import re
from abc import ABC
from typing import Protocol

try:
    import httpx
except ImportError:
    httpx = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from readability_lxml import Document
except ImportError:
    Document = None

logger = logging.getLogger(__name__)


class ContentExtractorError(Exception):
    """内容提取异常"""
    pass


class ContentExtractorProtocol(Protocol):
    """内容提取器协议"""

    source_name: str

    def extract(self, url: str, proxy_config: dict | None = None, timeout: int = 30) -> str:
        """
        从URL提取文章正文

        Args:
            url: 文章URL
            proxy_config: 代理配置
            timeout: 超时时间（秒）

        Returns:
            str: 提取的文章正文

        Raises:
            ContentExtractorError: 提取失败
        """
        ...


class BaseContentExtractor(ABC):
    """内容提取器基类"""

    source_name: str = "base"

    def extract(self, url: str, proxy_config: dict | None = None, timeout: int = 30) -> str:
        """默认实现：子类必须覆盖"""
        raise NotImplementedError

    def _clean_text(self, text: str) -> str:
        """
        清理文本

        Args:
            text: 原始文本

        Returns:
            str: 清理后的文本
        """
        # 移除多余的空白
        text = re.sub(r'\s+', ' ', text)
        # 移除特殊字符
        text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        return text.strip()

    def _build_proxies(self, proxy_config: dict | None) -> str | None:
        """
        构建代理URL

        Args:
            proxy_config: 代理配置字典

        Returns:
            Optional[str]: 代理URL
        """
        if not proxy_config:
            return None

        proxy_url = f"{proxy_config.get('proxy_type', 'http')}://"
        if proxy_config.get('username') and proxy_config.get('password'):
            proxy_url += f"{proxy_config['username']}:{proxy_config['password']}@"
        proxy_url += f"{proxy_config['host']}:{proxy_config['port']}"

        return proxy_url


class ReadabilityExtractor(BaseContentExtractor):
    """
    使用readability-lxml提取内容

    优点：
    - 基于Mozilla的Readability算法
    - 自动识别正文内容
    - 对各种网站结构适应性好

    缺点：
    - 依赖C扩展库
    - 某些特殊结构可能误判
    """

    source_name = "readability"

    def extract(self, url: str, proxy_config: dict | None = None, timeout: int = 30) -> str:
        """
        使用readability-lxml提取内容

        Args:
            url: 文章URL
            proxy_config: 代理配置
            timeout: 超时时间

        Returns:
            str: 提取的文章正文
        """
        if Document is None:
            raise ContentExtractorError("readability-lxml is not installed")

        if httpx is None:
            raise ContentExtractorError("httpx is not installed")

        proxies = self._build_proxies(proxy_config)

        try:
            # 获取HTML
            with httpx.Client(proxies=proxies, timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                response.raise_for_status()
                html = response.text

            # 使用readability提取
            doc = Document(html)
            content_html = doc.summary()

            # 转换为纯文本
            if BeautifulSoup:
                soup = BeautifulSoup(content_html, 'html.parser')
                text = soup.get_text(separator='\n')
            else:
                # 降级：简单移除HTML标签
                text = re.sub(r'<[^>]+>', '\n', content_html)

            # 清理文本
            text = self._clean_text(text)

            logger.debug(f"Extracted {len(text)} characters from {url}")
            return text

        except httpx.HTTPError as e:
            raise ContentExtractorError(f"HTTP error: {e}") from e
        except Exception as e:
            raise ContentExtractorError(f"Failed to extract content: {e}") from e


class BeautifulSoupExtractor(BaseContentExtractor):
    """
    使用BeautifulSoup4提取内容

    优点：
    - 纯Python实现，无C依赖
    - 可自定义提取规则
    - 轻量级

    缺点：
    - 需要针对不同网站定制规则
    - 准确性依赖规则质量
    """

    source_name = "beautifulsoup"

    # 常见的正文内容选择器（按优先级）
    CONTENT_SELECTORS = [
        # 通用选择器
        'article',
        '[role="article"]',
        '.article-content',
        '.post-content',
        '.entry-content',
        '.content',
        '.main-content',
        '#content',
        '#article',
        # 中文网站常见
        '.article-body',
        '.article-body p',
        '.artical-content',
        '.article_detail',
        '#article_content',
        '#artibody',
        # 政府网站
        '.content p',
        '.text p',
        '.article p',
    ]

    # 需要移除的元素
    REMOVE_ELEMENTS = [
        'script', 'style', 'nav', 'header', 'footer',
        'aside', '.advertisement', '.ads', '.sidebar',
        '.related', '.comments', '.share', '.social',
        'iframe', 'noscript'
    ]

    def extract(self, url: str, proxy_config: dict | None = None, timeout: int = 30) -> str:
        """
        使用BeautifulSoup4提取内容

        Args:
            url: 文章URL
            proxy_config: 代理配置
            timeout: 超时时间

        Returns:
            str: 提取的文章正文
        """
        if BeautifulSoup is None:
            raise ContentExtractorError("beautifulsoup4 is not installed")

        if httpx is None:
            raise ContentExtractorError("httpx is not installed")

        proxies = self._build_proxies(proxy_config)

        try:
            # 获取HTML
            with httpx.Client(proxies=proxies, timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                response.raise_for_status()
                html = response.text

            # 解析HTML
            soup = BeautifulSoup(html, 'html.parser')

            # 移除不需要的元素
            for element in soup.select(', '.join(self.REMOVE_ELEMENTS)):
                element.decompose()

            # 尝试各种选择器
            content = None
            for selector in self.CONTENT_SELECTORS:
                element = soup.select_one(selector)
                if element:
                    content = element.get_text(separator='\n')
                    # 检查内容质量
                    if len(content) > 200:  # 至少200字符
                        break

            # 如果没有找到合适的内容，尝试使用meta description
            if not content or len(content) < 200:
                meta_desc = soup.find('meta', attrs={'name': 'description'})
                if meta_desc and meta_desc.get('content'):
                    content = meta_desc['content']

            if not content:
                raise ContentExtractorError("Could not extract content from page")

            # 清理文本
            content = self._clean_text(content)

            logger.debug(f"Extracted {len(content)} characters from {url}")
            return content

        except httpx.HTTPError as e:
            raise ContentExtractorError(f"HTTP error: {e}") from e
        except Exception as e:
            raise ContentExtractorError(f"Failed to extract content: {e}") from e

    def extract_with_custom_selector(
        self,
        url: str,
        selector: str,
        proxy_config: dict | None = None,
        timeout: int = 30
    ) -> str:
        """
        使用自定义选择器提取内容

        Args:
            url: 文章URL
            selector: CSS选择器
            proxy_config: 代理配置
            timeout: 超时时间

        Returns:
            str: 提取的文章正文
        """
        if httpx is None:
            raise ContentExtractorError("httpx is not installed")

        proxies = self._build_proxies(proxy_config)

        try:
            with httpx.Client(proxies=proxies, timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                response.raise_for_status()
                html = response.text

            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one(selector)

            if not element:
                raise ContentExtractorError(f"Element not found: {selector}")

            content = element.get_text(separator='\n')
            content = self._clean_text(content)

            return content

        except httpx.HTTPError as e:
            raise ContentExtractorError(f"HTTP error: {e}") from e
        except Exception as e:
            raise ContentExtractorError(f"Failed to extract content: {e}") from e


class HybridContentExtractor(BaseContentExtractor):
    """
    混合内容提取器

    优先使用readability-lxml，失败时降级到BeautifulSoup4
    """

    source_name = "hybrid"

    def __init__(self):
        self.readability_extractor = ReadabilityExtractor()
        self.bs4_extractor = BeautifulSoupExtractor()

    def extract(self, url: str, proxy_config: dict | None = None, timeout: int = 30) -> str:
        """
        混合提取：先尝试readability，失败时使用BeautifulSoup4

        Args:
            url: 文章URL
            proxy_config: 代理配置
            timeout: 超时时间

        Returns:
            str: 提取的文章正文
        """
        # 优先尝试readability
        try:
            return self.readability_extractor.extract(url, proxy_config, timeout)
        except ContentExtractorError as e:
            logger.warning(f"Readability extraction failed for {url}, falling back to BeautifulSoup4: {e}")

        # 降级到BeautifulSoup4
        try:
            return self.bs4_extractor.extract(url, proxy_config, timeout)
        except ContentExtractorError:
            raise ContentExtractorError(f"All extraction methods failed for {url}") from None


# 工厂函数
def create_content_extractor(extractor_type: str = 'hybrid') -> BaseContentExtractor:
    """
    创建内容提取器

    Args:
        extractor_type: 提取器类型 ('readability', 'beautifulsoup', 'hybrid')

    Returns:
        BaseContentExtractor: 内容提取器实例

    Raises:
        ValueError: 不支持的提取器类型
    """
    extractors = {
        'readability': ReadabilityExtractor,
        'beautifulsoup': BeautifulSoupExtractor,
        'bs4': BeautifulSoupExtractor,
        'hybrid': HybridContentExtractor,
    }

    extractor_class = extractors.get(extractor_type.lower())
    if not extractor_class:
        raise ValueError(f"Unsupported extractor type: {extractor_type}. Supported: {list(extractors.keys())}")

    return extractor_class()
