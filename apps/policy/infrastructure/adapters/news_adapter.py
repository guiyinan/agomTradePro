"""
News Policy Adapter - 新闻政策事件适配器

从新闻源获取政策事件信息。
注意：本适配器提供基础框架，实际使用时需要根据具体新闻源进行调整。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

from apps.data_center.application.public import fetch_rss_news_feed, probe_rss_news_feed

from ...domain.entities import PolicyEvent, PolicyLevel
from .base import (
    PolicyAdapterError,
    PolicyAdapterProtocol,
    PolicySourceUnavailableError,
)

logger = logging.getLogger(__name__)


class _NewsProbeResponseProtocol(Protocol):
    status_code: int


class _NewsSessionProtocol(Protocol):
    def get(self, url: str, *, timeout: int) -> _NewsProbeResponseProtocol:
        """Probe an external source through the Data Center transport."""


@dataclass
class _NewsProbeResponse:
    status_code: int


class _DataCenterNewsSession:
    """Compatibility session facade backed by the Data Center RSS port."""

    def __init__(self, config: NewsSourceConfig) -> None:
        self._config = config

    def get(self, url: str, *, timeout: int) -> _NewsProbeResponseProtocol:
        try:
            probe_rss_news_feed(
                url=url,
                source_name=self._config.name,
                timeout_seconds=timeout,
                retry_times=1,
            )
        except Exception:
            return _NewsProbeResponse(status_code=503)
        return _NewsProbeResponse(status_code=200)


@dataclass
class NewsSourceConfig:
    """新闻源配置"""

    name: str
    base_url: str
    api_key: str | None = None
    request_timeout: int = 10
    rate_limit_delay: float = 1.0  # 秒

    def __post_init__(self) -> None:
        """Reject unsafe or unbounded provider configuration."""
        parsed_url = urlsplit(self.base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError("news source URL must use HTTP or HTTPS")
        if parsed_url.username is not None or parsed_url.password is not None:
            raise ValueError("news source URL must not contain credentials")
        if not 1 <= self.request_timeout <= 120:
            raise ValueError("request_timeout must be between 1 and 120 seconds")
        if not 0 <= self.rate_limit_delay <= 60:
            raise ValueError("rate_limit_delay must be between 0 and 60 seconds")


class NewsPolicyAdapter(PolicyAdapterProtocol):
    """
    基于新闻的政策事件适配器

    功能：
    1. 从新闻源搜索政策相关新闻
    2. 根据关键词判断政策档位
    3. 提取事件信息

    注意：这是一个框架实现，实际使用需要：
    - 配置具体的新闻 API（如新浪财经、东方财富等）
    - 根据实际 API 响应格式调整解析逻辑
    - 可能需要处理反爬机制
    """

    # 政策档位关键词配置
    LEVEL_KEYWORDS = {
        PolicyLevel.P3: [
            "熔断",
            "紧急救市",
            "市场恐慌",
            "股市崩盘",
            "汇率一次性调整",
            "资本管制",
            "非常规措施",
        ],
        PolicyLevel.P2: [
            "降息",
            "加息",
            "降准",
            "加息",
            "财政刺激",
            "减税降费",
            "特别国债",
            "政策出台",
            "重大政策",
            "政策落地",
            "央行",
            "证监会",
            "银保监会",
            "发布会",
        ],
        PolicyLevel.P1: [
            "政策预期",
            "政策信号",
            "或将",
            "有望",
            "讨论",
            "研究",
            "酝酿",
            "考虑",
            "表态",
            "定调",
            "会议",
            "讲话",
        ],
    }

    def __init__(self, config: NewsSourceConfig):
        """
        初始化适配器

        Args:
            config: 新闻源配置
        """
        self.config = config
        self.session: _NewsSessionProtocol = _DataCenterNewsSession(config)

    def fetch_policy_events(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> list[PolicyEvent]:
        """
        获取政策事件列表

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[PolicyEvent]: 政策事件列表
        """
        if not self.is_available():
            raise PolicySourceUnavailableError(f"News source {self.config.name} is unavailable")

        events: list[PolicyEvent] = []

        try:
            # 默认搜索最近 7 天
            if end_date is None:
                end_date = date.today()
            if start_date is None:
                start_date = end_date - timedelta(days=7)

            # 搜索政策相关新闻
            news_items = self._search_policy_news(start_date, end_date)

            # 解析新闻为政策事件
            for item in news_items:
                event = self._parse_news_to_event(item)
                if event:
                    events.append(event)

            logger.info(f"Fetched {len(events)} policy events from {self.config.name}")

        except Exception as exc:
            logger.error("policy_news_fetch_failed: %s", type(exc).__name__)
            raise PolicyAdapterError("policy_news_fetch_failed") from exc

        return events

    def is_available(self) -> bool:
        """
        检查适配器是否可用

        Returns:
            bool: 是否可用
        """
        try:
            response = self.session.get(self.config.base_url, timeout=self.config.request_timeout)
            return response.status_code == 200
        except Exception:
            return False

    def get_source_name(self) -> str:
        """获取数据源名称"""
        return self.config.name

    def _search_policy_news(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        """
        搜索政策相关新闻

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[Dict]: 新闻列表
        """
        try:
            facts = fetch_rss_news_feed(
                url=self.config.base_url,
                source_name=self.config.name,
                timeout_seconds=self.config.request_timeout,
                retry_times=1,
            )
        except Exception as exc:
            logger.warning("policy_news_search_failed: error_type=%s", type(exc).__name__)
            return []

        return [
            {
                "title": fact.title,
                "content": fact.summary,
                "url": fact.url,
                "pub_date": fact.published_at.date().isoformat(),
            }
            for fact in facts
            if start_date <= fact.published_at.date() <= end_date
        ]

    def _parse_news_to_event(self, news_item: dict[str, Any]) -> PolicyEvent | None:
        """
        将新闻解析为政策事件

        Args:
            news_item: 新闻项

        Returns:
            Optional[PolicyEvent]: 政策事件，解析失败返回 None
        """
        try:
            # 提取基本信息
            title = news_item.get("title", "")
            content = news_item.get("content", "")
            url = news_item.get("url", "")
            pub_date_str = news_item.get("pub_date", "")

            # 解析日期
            pub_date = self._parse_date(pub_date_str)
            if not pub_date:
                return None

            # 判断政策档位
            level = self._classify_policy_level(title + " " + content)

            # 生成描述（取内容前 200 字）
            description = content[:200] + "..." if len(content) > 200 else content

            return PolicyEvent(
                event_date=pub_date,
                level=level,
                title=title,
                description=description,
                evidence_url=url,
            )

        except Exception as exc:
            logger.warning("policy_news_item_invalid: %s", type(exc).__name__)
            return None

    def _classify_policy_level(self, text: str) -> PolicyLevel:
        """
        根据文本内容判断政策档位

        Args:
            text: 文本内容

        Returns:
            PolicyLevel: 政策档位
        """
        text = text.lower()

        # 按优先级检查（P3 > P2 > P1 > P0）
        for level in [PolicyLevel.P3, PolicyLevel.P2, PolicyLevel.P1]:
            keywords = self.LEVEL_KEYWORDS[level]
            if any(kw in text for kw in keywords):
                return level

        # 默认返回 P0
        return PolicyLevel.P0

    def _parse_date(self, date_str: str) -> date | None:
        """
        解析日期字符串

        支持多种格式：
        - 2024-01-15
        - 2024/01/15
        - 2024年01月15日
        - ISO 8601 格式

        Args:
            date_str: 日期字符串

        Returns:
            Optional[date]: 解析后的日期
        """
        if not date_str:
            return None

        # 常见格式
        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y年%m月%d日",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.date()
            except ValueError:
                continue

        logger.warning(f"Failed to parse date: {date_str}")
        return None


class RSSPolicyAdapter(PolicyAdapterProtocol):
    """
    基于 RSS 管道的政策事件适配器

    从 PolicyLog 表中读取已由 FetchRSSUseCase 抓取并分类的政策事件，
    转换为 PolicyEvent 领域实体。

    数据流: RSS源 → FetchRSSUseCase → PolicyLog(DB) → 本适配器 → PolicyEvent
    """

    def fetch_policy_events(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> list[PolicyEvent]:
        """
        从 PolicyLog 获取政策事件

        Args:
            start_date: 起始日期（默认最近 7 天）
            end_date: 结束日期（默认今天）

        Returns:
            政策事件列表
        """
        from apps.policy.infrastructure.models import PolicyLog

        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=7)

        logs = PolicyLog._default_manager.filter(
            event_date__gte=start_date,
            event_date__lte=end_date,
        ).order_by("-event_date")[:100]

        events = []
        for log in logs:
            try:
                level = PolicyLevel(log.level)
            except ValueError:
                level = PolicyLevel.P0

            events.append(
                PolicyEvent(
                    event_date=log.event_date,
                    level=level,
                    title=log.title,
                    description=log.description,
                    evidence_url=log.evidence_url,
                )
            )

        logger.info(f"RSSPolicyAdapter: loaded {len(events)} events from PolicyLog")
        return events

    def is_available(self) -> bool:
        """检查 PolicyLog 表是否可访问"""
        try:
            from apps.policy.infrastructure.models import PolicyLog

            PolicyLog._default_manager.exists()
            return True
        except Exception:
            return False

    def get_source_name(self) -> str:
        return "RSS Pipeline (PolicyLog)"
