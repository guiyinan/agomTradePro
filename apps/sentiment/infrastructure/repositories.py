"""
Sentiment 模块 - Infrastructure 层仓储实现

本模块包含仓储的具体实现，使用 Django ORM 进行数据持久化。
"""

import hashlib
from datetime import date, datetime

from apps.regime.infrastructure.config_helper import ConfigHelper, ConfigKeys
from apps.sentiment.domain.entities import SentimentAnalysisResult, SentimentIndex
from apps.sentiment.infrastructure.models import (
    SentimentAlertModel,
    SentimentAnalysisLog,
    SentimentCache,
    SentimentIndexModel,
)


class SentimentIndexRepository:
    """
    情绪指数仓储

    负责情绪指数的存储和查询。
    """

    def save(self, sentiment_index: SentimentIndex) -> SentimentIndexModel:
        """
        保存情绪指数

        Args:
            sentiment_index: 情绪指数实体

        Returns:
            SentimentIndexModel ORM 模型实例
        """
        index_date = sentiment_index.index_date
        if hasattr(index_date, 'date'):
            index_date = index_date.date()

        model, created = SentimentIndexModel._default_manager.update_or_create(
            index_date=index_date,
            defaults={
                "news_sentiment": sentiment_index.news_sentiment,
                "policy_sentiment": sentiment_index.policy_sentiment,
                "composite_index": sentiment_index.composite_index,
                "confidence_level": sentiment_index.confidence_level,
                "data_sufficient": sentiment_index.data_sufficient,
                "sector_sentiment": sentiment_index.sector_sentiment,
                "news_count": sentiment_index.news_count,
                "policy_events_count": sentiment_index.policy_events_count,
            }
        )

        return model

    def get_by_date(self, target_date: date) -> SentimentIndex | None:
        """
        根据日期获取情绪指数

        Args:
            target_date: 目标日期

        Returns:
            SentimentIndex 实体，不存在则返回 None
        """
        try:
            model = SentimentIndexModel._default_manager.get(index_date=target_date)
            return self._to_entity(model)
        except SentimentIndexModel.DoesNotExist:
            return None

    def get_latest(self) -> SentimentIndex | None:
        """
        获取最新的情绪指数

        Returns:
            SentimentIndex 实体，不存在则返回 None
        """
        model = SentimentIndexModel._default_manager.order_by("-index_date").first()
        if model:
            return self._to_entity(model)
        return None

    def get_range(self, start_date: date, end_date: date) -> list[SentimentIndex]:
        """
        获取日期范围内的情绪指数

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            SentimentIndex 实体列表
        """
        models = SentimentIndexModel._default_manager.filter(
            index_date__gte=start_date,
            index_date__lte=end_date
        ).order_by("index_date")

        return [self._to_entity(model) for model in models]

    def get_recent(self, days: int = 30) -> list[SentimentIndex]:
        """
        获取最近 N 天的情绪指数

        Args:
            days: 天数

        Returns:
            SentimentIndex 实体列表
        """
        from datetime import timedelta

        start_date = date.today() - timedelta(days=days)
        return self.get_range(start_date, date.today())

    def get_latest_index_date(self) -> date | None:
        """Return the latest stored sentiment index date."""

        latest = SentimentIndexModel._default_manager.order_by("-index_date").first()
        if latest is None:
            return None
        return latest.index_date

    @staticmethod
    def _to_entity(model: SentimentIndexModel) -> SentimentIndex:
        """
        ORM 模型转换为 Domain 实体

        Args:
            model: SentimentIndexModel 实例

        Returns:
            SentimentIndex 实体
        """
        return SentimentIndex(
            index_date=datetime.combine(model.index_date, datetime.min.time()),
            news_sentiment=model.news_sentiment,
            policy_sentiment=model.policy_sentiment,
            composite_index=model.composite_index,
            confidence_level=model.confidence_level,
            data_sufficient=model.data_sufficient,
            sector_sentiment=model.sector_sentiment,
            news_count=model.news_count,
            policy_events_count=model.policy_events_count,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SentimentAnalysisLogRepository:
    """
    情感分析日志仓储

    负责情感分析日志的存储和查询。
    """

    def log(
        self,
        source_type: str,
        input_text: str,
        result: SentimentAnalysisResult,
        ai_provider: str = None,
        ai_model: str = None,
        ai_response_time_ms: int = None,
        source_id: str = None,
    ) -> SentimentAnalysisLog:
        """
        记录情感分析日志

        Args:
            source_type: 数据源类型
            input_text: 输入文本
            result: 分析结果
            ai_provider: AI 提供商
            ai_model: AI 模型
            ai_response_time_ms: 响应时间
            source_id: 数据源 ID

        Returns:
            SentimentAnalysisLog 实例
        """
        return SentimentAnalysisLog._default_manager.create(
            source_type=source_type,
            source_id=source_id,
            input_text=input_text,
            sentiment_score=result.sentiment_score,
            category=result.category.value,
            confidence=result.confidence,
            keywords=result.keywords,
            ai_provider=ai_provider,
            ai_model=ai_model,
            ai_response_time_ms=ai_response_time_ms,
        )

    def get_recent_logs(self, limit: int = 100) -> list[SentimentAnalysisLog]:
        """
        获取最近的日志

        Args:
            limit: 返回数量限制

        Returns:
            日志列表
        """
        return list(SentimentAnalysisLog._default_manager.order_by("-created_at")[:limit])

    def get_logs_by_source(self, source_type: str, source_id: str = None) -> list[SentimentAnalysisLog]:
        """
        根据数据源获取日志

        Args:
            source_type: 数据源类型
            source_id: 数据源 ID（可选）

        Returns:
            日志列表
        """
        queryset = SentimentAnalysisLog._default_manager.filter(source_type=source_type)

        if source_id:
            queryset = queryset.filter(source_id=source_id)

        return list(queryset.order_by("-created_at"))


class SentimentCacheRepository:
    """
    情感分析缓存仓储

    负责情感分析结果的缓存管理。
    """

    def get(self, text: str) -> SentimentAnalysisResult | None:
        """
        从缓存获取分析结果

        Args:
            text: 输入文本

        Returns:
            SentimentAnalysisResult 实体，不存在则返回 None
        """
        text_hash = self._compute_hash(text)

        try:
            cache = SentimentCache._default_manager.get(text_hash=text_hash)

            from apps.sentiment.domain.entities import SentimentCategory

            return SentimentAnalysisResult(
                text=text,
                sentiment_score=cache.sentiment_score,
                confidence=cache.confidence,
                category=SentimentCategory(cache.category),
                keywords=cache.keywords,
                analyzed_at=cache.updated_at,
            )
        except SentimentCache.DoesNotExist:
            return None

    def set(self, text: str, result: SentimentAnalysisResult) -> None:
        """
        设置缓存

        Args:
            text: 输入文本
            result: 分析结果
        """
        text_hash = self._compute_hash(text)

        SentimentCache._default_manager.update_or_create(
            text_hash=text_hash,
            defaults={
                "sentiment_score": result.sentiment_score,
                "category": result.category.value,
                "confidence": result.confidence,
                "keywords": result.keywords,
            }
        )

    def clear(self, text: str = None) -> int:
        """
        清除缓存

        Args:
            text: 指定文本的缓存（不指定则清除所有）

        Returns:
            清除的记录数
        """
        if text:
            text_hash = self._compute_hash(text)
            count, _ = SentimentCache._default_manager.filter(text_hash=text_hash).delete()
        else:
            count, _ = SentimentCache._default_manager.all().delete()

        return count

    def count(self) -> int:
        """Return the number of cached sentiment analysis records."""

        return SentimentCache._default_manager.count()

    @staticmethod
    def _compute_hash(text: str) -> str:
        """
        计算文本哈希

        Args:
            text: 输入文本

        Returns:
            SHA256 哈希值
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SentimentAlertRepository:
    """情绪模块告警仓储。"""

    def create_alert(
        self,
        *,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        metadata: dict | None = None,
    ) -> SentimentAlertModel:
        """创建一条情绪模块告警记录。"""
        return SentimentAlertModel._default_manager.create(
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            metadata=metadata or {},
        )


class SentimentConfigRepository:
    """Infrastructure-backed config access for sentiment application services."""

    def get_news_weight(self, default: float) -> float:
        return ConfigHelper.get_float(
            ConfigKeys.SENTIMENT_NEWS_WEIGHT,
            default,
        )

    def get_policy_weight(self, default: float) -> float:
        return ConfigHelper.get_float(
            ConfigKeys.SENTIMENT_POLICY_WEIGHT,
            default,
        )

