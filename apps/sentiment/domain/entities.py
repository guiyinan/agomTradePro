"""
Sentiment 模块 - Domain 层实体

本模块定义舆情情感分析的实体类，遵循 DDD 原则。
Domain 层不依赖任何外部框架（如 Django），只使用 Python 标准库。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, List
from enum import Enum


class SentimentCategory(Enum):
    """情感分类"""
    POSITIVE = "POSITIVE"      # 正面
    NEGATIVE = "NEGATIVE"      # 负面
    NEUTRAL = "NEUTRAL"        # 中性


@dataclass(frozen=True)
class SentimentAnalysisResult:
    """
    情感分析结果实体

    存储单条文本的情感分析结果。
    """
    text: str                                 # 原始文本
    sentiment_score: float                    # 情感评分 (-3.0 ~ +3.0)
    confidence: float                         # 置信度 (0.0 ~ 1.0)
    category: SentimentCategory               # 情感分类
    keywords: List[str] = field(default_factory=list)  # 关键词列表
    analyzed_at: datetime = field(default_factory=datetime.now)
    error_message: Optional[str] = None       # 错误信息（AI 调用失败时）

    def __post_init__(self):
        """验证数据有效性"""
        # 验证评分范围
        if not -3.0 <= self.sentiment_score <= 3.0:
            raise ValueError(f"sentiment_score 必须在 -3.0 到 +3.0 之间，当前为 {self.sentiment_score}")

        # 验证置信度范围
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence 必须在 0.0 到 1.0 之间，当前为 {self.confidence}")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "text": self.text[:100] + "..." if len(self.text) > 100 else self.text,  # 截断显示
            "sentiment_score": self.sentiment_score,
            "confidence": self.confidence,
            "category": self.category.value,
            "keywords": self.keywords,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass(frozen=True)
class SentimentIndex:
    """
    情绪指数实体

    存储某日的综合情绪指数。
    """
    index_date: datetime                      # 指数日期

    # 情绪指数（-3.0 ~ +3.0）
    news_sentiment: float = 0.0              # 新闻情绪
    policy_sentiment: float = 0.0            # 政策情绪
    composite_index: float = 0.0             # 综合指数

    # 置信度
    confidence_level: float = 0.0            # 综合置信度

    # 数据充足性标记（区分"无数据"和"中性情绪"）
    data_sufficient: bool = False            # 数据是否充足

    # 分类情绪（按行业、资产类型等）
    sector_sentiment: Dict[str, float] = field(default_factory=dict)

    # 数据来源统计
    news_count: int = 0                      # 新闻数量
    policy_events_count: int = 0             # 政策事件数量

    # 元信息
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """验证数据有效性"""
        # 验证评分范围
        for name, value in [
            ("news_sentiment", self.news_sentiment),
            ("policy_sentiment", self.policy_sentiment),
            ("composite_index", self.composite_index),
        ]:
            if not -3.0 <= value <= 3.0:
                raise ValueError(f"{name} 必须在 -3.0 到 +3.0 之间，当前为 {value}")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "date": self.index_date.strftime("%Y-%m-%d"),
            "index": {
                "composite": self.composite_index,
                "news": self.news_sentiment,
                "policy": self.policy_sentiment,
            },
            "level": self._get_sentiment_level() if self.data_sufficient else "数据不足",
            "confidence": self.confidence_level,
            "data_sufficient": self.data_sufficient,
            "sector_sentiment": self.sector_sentiment,
            "sources": {
                "news_count": self.news_count,
                "policy_events_count": self.policy_events_count,
            },
        }

    def _get_sentiment_level(self) -> str:
        """获取情绪等级描述"""
        score = self.composite_index
        if score >= 1.5:
            return "极度乐观"
        elif score >= 0.5:
            return "乐观"
        elif score >= -0.5:
            return "中性"
        elif score >= -1.5:
            return "悲观"
        else:
            return "极度悲观"


@dataclass(frozen=True)
class SentimentSource:
    """
    情感数据源实体

    定义情感分析的数据来源。
    """
    source_type: str                          # 数据源类型：news/policy/social
    source_id: str                            # 数据源 ID
    title: str                                # 标题
    content: str                              # 内容
    published_at: datetime                    # 发布时间
    url: Optional[str] = None                 # 链接

    # 扩展字段
    metadata: Dict = field(default_factory=dict)  # 额外元数据

    def __post_init__(self):
        """验证数据有效性"""
        if not self.source_type:
            raise ValueError("source_type 不能为空")

        if not self.title and not self.content:
            raise ValueError("title 和 content 至少需要一个")

    def to_text(self) -> str:
        """转换为文本用于分析"""
        if self.content:
            return f"{self.title}\n{self.content}"
        return self.title
