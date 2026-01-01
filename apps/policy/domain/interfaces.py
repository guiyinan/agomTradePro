"""
Domain Layer - Protocol Interfaces for Policy

本文件定义Policy模块的Protocol接口，用于依赖注入和解耦。
"""

from typing import Protocol, List, Optional
from .entities import RSSItem, AIClassificationResult


class PolicyClassifierProtocol(Protocol):
    """政策分类器协议"""

    def classify_rss_item(
        self,
        item: RSSItem,
        content: Optional[str] = None
    ) -> AIClassificationResult:
        """
        对RSS条目进行AI分类和结构化提取

        Args:
            item: RSS条目
            content: 可选的完整内容（如果extract_content=True）

        Returns:
            AIClassificationResult: 分类结果
        """
        ...

    def batch_classify(
        self,
        items: List[tuple[RSSItem, Optional[str]]]
    ) -> List[AIClassificationResult]:
        """
        批量分类

        Args:
            items: (RSS条目, 可选内容) 的列表

        Returns:
            List[AIClassificationResult]: 分类结果列表
        """
        ...
