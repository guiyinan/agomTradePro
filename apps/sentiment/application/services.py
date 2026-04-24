"""
Sentiment 模块 - Application 层服务

本模块包含应用服务，负责编排业务逻辑。
Application 层依赖 Domain 层和 Infrastructure 层的接口。
"""

import json
import logging
import re
from datetime import datetime
from typing import List, Optional

from django.utils import timezone

from apps.ai_provider.domain.entities import AIChatRequest
from apps.ai_provider.infrastructure.adapters import OpenAICompatibleAdapter
from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from apps.sentiment.domain.entities import (
    SentimentAnalysisResult,
    SentimentCategory,
    SentimentIndex,
    SentimentSource,
)
from apps.sentiment.infrastructure.repositories import SentimentAlertRepository
from shared.infrastructure.config_helper import ConfigHelper, ConfigKeys

logger = logging.getLogger(__name__)

# 默认权重值（从配置读取失败时使用）
DEFAULT_NEWS_WEIGHT = 0.4
DEFAULT_POLICY_WEIGHT = 0.6


class SentimentAnalyzer:
    """
    情感分析服务（调用 AI API）

    使用系统 AI API（apps/ai_provider）进行金融舆情情感分析。
    """

    def __init__(self, provider_repository: AIProviderRepository):
        """
        初始化情感分析器

        Args:
            provider_repository: AI 提供商仓储
        """
        self.provider_repo = provider_repository
        self._adapter_cache = {}

    def analyze_text(self, text: str) -> SentimentAnalysisResult:
        """
        分析文本情感

        Args:
            text: 待分析的文本

        Returns:
            SentimentAnalysisResult 情感分析结果
        """
        # 1. 构建 Prompt
        prompt = self._build_sentiment_prompt(text)

        # 2. 获取 AI 适配器
        adapter = self._get_ai_adapter()

        # 3. 调用 AI API
        response = adapter.chat_completion(
            messages=[
                {"role": "system", "content": "你是一个专业的金融舆情情感分析专家。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # 降低随机性，提高一致性
            max_tokens=500
        )

        # 4. 解析结果
        if response["status"] != "success":
            # AI 调用失败，返回中性结果并发送告警
            self._send_ai_failure_alert(text, response.get("error", "Unknown error"))
            return SentimentAnalysisResult(
                text=text,
                sentiment_score=0.0,
                confidence=0.0,
                category=SentimentCategory.NEUTRAL,
                keywords=[],
                analyzed_at=timezone.now(),
                error_message=f"AI 调用失败: {response.get('error', 'Unknown error')}",
            )

        sentiment_score = self._parse_sentiment_score(response["content"])
        confidence = self._estimate_confidence(response, sentiment_score)
        category = self._categorize_sentiment(sentiment_score)
        keywords = self._extract_keywords(text, response["content"])

        return SentimentAnalysisResult(
            text=text,
            sentiment_score=sentiment_score,
            confidence=confidence,
            category=category,
            keywords=keywords,
            analyzed_at=timezone.now(),
        )

    def analyze_batch(self, texts: list[str]) -> list[SentimentAnalysisResult]:
        """
        批量分析文本情感

        Args:
            texts: 待分析的文本列表

        Returns:
            情感分析结果列表
        """
        return [self.analyze_text(text) for text in texts]

    def analyze_source(self, source: SentimentSource) -> SentimentAnalysisResult:
        """
        分析数据源的情感

        Args:
            source: 情感数据源

        Returns:
            情感分析结果
        """
        text = source.to_text()
        result = self.analyze_text(text)

        # 将来源信息添加到结果中（通过自定义字段）
        return result

    def _get_ai_adapter(self) -> OpenAICompatibleAdapter:
        """获取 AI 适配器（带缓存）"""
        if not self._adapter_cache:
            # 获取激活的提供商
            providers = self.provider_repo.get_active_configured_system_providers()

            if not providers:
                raise RuntimeError("没有带可用凭据的 AI 提供商配置，请先在管理后台配置")

            # 使用优先级最高的提供商
            provider = providers[0]

            # 创建适配器 - 使用 repository 的 get_api_key 方法解密
            extra_config = provider.extra_config if isinstance(provider.extra_config, dict) else {}
            api_key = self.provider_repo.get_api_key(provider)
            self._adapter_cache = OpenAICompatibleAdapter(
                base_url=provider.base_url,
                api_key=api_key,
                default_model=provider.default_model,
                api_mode=extra_config.get("api_mode"),
                fallback_enabled=extra_config.get("fallback_enabled"),
            )

        return self._adapter_cache

    def _build_sentiment_prompt(self, text: str) -> str:
        """
        构建情感分析 Prompt

        Args:
            text: 待分析的文本

        Returns:
            Prompt 字符串
        """
        return f"""请分析以下金融新闻/政策的情感倾向，并给出 -3.0 到 +3.0 的评分。

评分标准：
- -3.0: 极度负面（如熔断、危机、暴跌、崩盘）
- -1.5: 负面（如下跌、利空、收紧、加息）
- 0.0: 中性（如持平、观望、维持）
- +1.5: 正面（如上涨、利好、放松、降息）
- +3.0: 极度正面（如大涨、降准、重大利好）

文本内容：
{text}

请只返回一个 JSON 格式的结果，包含以下字段：
{{
    "score": <评分>,
    "reasoning": "<简要理由>",
    "keywords": ["<关键词1>", "<关键词2>"]
}}

不要返回其他内容。"""

    def _parse_sentiment_score(self, ai_response: str) -> float:
        """
        解析 AI 返回的情感评分

        Args:
            ai_response: AI 响应内容

        Returns:
            情感评分（-3.0 ~ +3.0）
        """
        # 尝试解析 JSON 格式
        try:
            # 提取 JSON 部分
            json_match = re.search(r'\{[^}]+\}', ai_response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                score = float(data.get("score", 0))
                return max(-3.0, min(3.0, score))
        except (json.JSONDecodeError, ValueError):
            pass

        # 降级：直接提取数字
        number_match = re.search(r'-?\d+\.?\d*', ai_response)
        if number_match:
            score = float(number_match.group())
            return max(-3.0, min(3.0, score))

        # 默认返回中性
        return 0.0

    def _estimate_confidence(self, response: dict, sentiment_score: float) -> float:
        """
        估算置信度

        Args:
            response: AI 响应
            sentiment_score: 情感评分

        Returns:
            置信度（0.0 ~ 1.0）
        """
        # 基础置信度
        base_confidence = 0.75

        # 根据评分极端程度调整置信度
        # 极端评分（接近 ±3）通常置信度更高
        score_magnitude = abs(sentiment_score)
        if score_magnitude >= 2.0:
            base_confidence = 0.85
        elif score_magnitude >= 1.0:
            base_confidence = 0.80

        # 根据响应时间调整（响应过快可能是缓存，过慢可能是网络问题）
        response_time = response.get("response_time_ms", 0)
        if 500 < response_time < 5000:  # 0.5-5 秒是正常范围
            base_confidence += 0.05

        return min(1.0, base_confidence)

    def _categorize_sentiment(self, score: float) -> SentimentCategory:
        """
        将评分转换为分类

        Args:
            score: 情感评分

        Returns:
            SentimentCategory
        """
        if score >= 0.5:
            return SentimentCategory.POSITIVE
        elif score <= -0.5:
            return SentimentCategory.NEGATIVE
        else:
            return SentimentCategory.NEUTRAL

    def _extract_keywords(self, text: str, ai_response: str) -> list[str]:
        """
        提取关键词

        Args:
            text: 原始文本
            ai_response: AI 响应

        Returns:
            关键词列表
        """
        keywords = []

        # 尝试从 AI 响应中提取
        try:
            json_match = re.search(r'\{[^}]+\}', ai_response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                keywords = data.get("keywords", [])
                if isinstance(keywords, list):
                    return keywords[:5]  # 最多返回 5 个
        except (json.JSONDecodeError, ValueError):
            pass

        # 降级：简单的关键词提取（金融相关词汇）
        financial_keywords = [
            "加息", "降息", "降准", "宽松", "紧缩",
            "上涨", "下跌", "大涨", "暴跌",
            "利好", "利空", "复苏", "衰退",
            "通胀", "通缩", "PMI", "GDP",
        ]

        for keyword in financial_keywords:
            if keyword in text:
                keywords.append(keyword)

        return keywords[:5]

    def _send_ai_failure_alert(self, text: str, error_message: str) -> None:
        """
        发送 AI 调用失败告警

        Args:
            text: 分析失败的文本
            error_message: 错误信息
        """
        logger.warning(f"Sentiment AI 调用失败: {error_message}, 文本: {text[:50]}...")

        try:
            # 创建告警记录到数据库
            SentimentAlertRepository().create_alert(
                alert_type="ai_failure",
                severity="warning",
                title="Sentiment AI 调用失败",
                message=f"情感分析 AI 调用失败，已降级为中性结果。\n错误: {error_message}",
                metadata={
                    "text_preview": text[:200] if text else "",
                    "error": error_message,
                }
            )
        except Exception as e:
            # 告警失败不应影响主流程
            logger.error(f"发送 AI 失败告警时出错: {e}")


class SentimentIndexCalculator:
    """
    情绪指数计算器

    负责根据多个情感分析结果计算综合情绪指数。
    """

    def calculate_index(
        self,
        news_scores: list[float],
        policy_scores: list[float],
        news_weight: float | None = None,
        policy_weight: float | None = None,
    ) -> SentimentIndex:
        """
        计算综合情绪指数

        Args:
            news_scores: 新闻情感评分列表
            policy_scores: 政策情感评分列表
            news_weight: 新闻权重（None 表示从配置读取）
            policy_weight: 政策权重（None 表示从配置读取）

        Returns:
            SentimentIndex 情绪指数
        """
        # 从配置读取权重（如果未指定）
        if news_weight is None:
            news_weight = ConfigHelper.get_float(
                ConfigKeys.SENTIMENT_NEWS_WEIGHT,
                DEFAULT_NEWS_WEIGHT
            )
        if policy_weight is None:
            policy_weight = ConfigHelper.get_float(
                ConfigKeys.SENTIMENT_POLICY_WEIGHT,
                DEFAULT_POLICY_WEIGHT
            )
        # 计算新闻情绪
        news_sentiment = self._weighted_average(news_scores) if news_scores else 0.0

        # 计算政策情绪
        policy_sentiment = self._weighted_average(policy_scores) if policy_scores else 0.0

        # 计算综合指数
        composite_index = news_sentiment * news_weight + policy_sentiment * policy_weight

        # 计算置信度（基于数据量）
        total_count = len(news_scores) + len(policy_scores)
        confidence_level = min(1.0, total_count / 10.0)  # 最多 10 条数据达到满置信

        # 判断数据是否充足
        # 定义：至少有 1 条新闻或 1 条政策事件才算数据充足
        data_sufficient = len(news_scores) > 0 or len(policy_scores) > 0

        return SentimentIndex(
            index_date=timezone.now(),
            news_sentiment=news_sentiment,
            policy_sentiment=policy_sentiment,
            composite_index=composite_index,
            confidence_level=confidence_level,
            data_sufficient=data_sufficient,
            news_count=len(news_scores),
            policy_events_count=len(policy_scores),
        )

    @staticmethod
    def _weighted_average(scores: list[float]) -> float:
        """
        计算加权平均（近期数据权重更高）

        Args:
            scores: 评分列表（按时间顺序，旧->新）

        Returns:
            加权平均分
        """
        if not scores:
            return 0.0

        # 简单线性权重：最新的权重最高
        n = len(scores)
        weights = list(range(1, n + 1))  # [1, 2, 3, ...]

        weighted_sum = sum(score * weight for score, weight in zip(scores, weights))
        total_weight = sum(weights)

        return weighted_sum / total_weight if total_weight > 0 else 0.0
