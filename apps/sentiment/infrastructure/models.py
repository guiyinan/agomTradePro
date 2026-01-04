"""
Sentiment 模块 - Infrastructure 层数据模型

本模块包含 Django ORM 模型定义。
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class SentimentIndexModel(models.Model):
    """
    舆情情绪指数表

    存储每日的综合情绪指数。
    """

    index_date = models.DateField(
        unique=True,
        db_index=True,
        verbose_name="指数日期"
    )

    # 情绪指数（-3.0 ~ +3.0）
    news_sentiment = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)],
        verbose_name="新闻情绪"
    )

    policy_sentiment = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)],
        verbose_name="政策情绪"
    )

    composite_index = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)],
        db_index=True,
        verbose_name="综合指数"
    )

    # 置信度
    confidence_level = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="置信度"
    )

    # 分类情绪（JSON）
    sector_sentiment = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="行业情绪",
        help_text="格式: {\"金融\": 0.5, \"科技\": 0.8}"
    )

    # 数据来源统计
    news_count = models.IntegerField(
        default=0,
        verbose_name="新闻数量"
    )

    policy_events_count = models.IntegerField(
        default=0,
        verbose_name="政策事件数量"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = "sentiment_index"
        verbose_name = "情绪指数"
        verbose_name_plural = "情绪指数"
        ordering = ["-index_date"]

    def __str__(self):
        return f"{self.index_date} - {self.composite_index:.2f}"

    @property
    def sentiment_level(self) -> str:
        """获取情绪等级"""
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


class SentimentAnalysisLog(models.Model):
    """
    情感分析日志表

    记录每次情感分析的详细信息，用于追溯和调试。
    """

    # 输入信息
    source_type = models.CharField(
        max_length=50,
        verbose_name="数据源类型",
        help_text="news/policy/social/manual"
    )

    source_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="数据源ID"
    )

    input_text = models.TextField(
        verbose_name="输入文本"
    )

    # 分析结果
    sentiment_score = models.FloatField(
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)],
        verbose_name="情感评分"
    )

    category = models.CharField(
        max_length=20,
        verbose_name="情感分类"
    )

    confidence = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="置信度"
    )

    keywords = models.JSONField(
        default=list,
        blank=True,
        verbose_name="关键词"
    )

    # AI 调用信息
    ai_provider = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="AI提供商"
    )

    ai_model = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="AI模型"
    )

    ai_response_time_ms = models.IntegerField(
        blank=True,
        null=True,
        verbose_name="AI响应时间(ms)"
    )

    # 元信息
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="创建时间"
    )

    class Meta:
        db_table = "sentiment_analysis_log"
        verbose_name = "情感分析日志"
        verbose_name_plural = "情感分析日志"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source_type", "source_id"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.source_type} - {self.sentiment_score:.2f}"


class SentimentCache(models.Model):
    """
    情感分析缓存表

    缓存文本的情感分析结果，避免重复调用 AI API。
    使用文本哈希作为缓存键。
    """

    text_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="文本哈希"
    )

    sentiment_score = models.FloatField(
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)],
        verbose_name="情感评分"
    )

    category = models.CharField(
        max_length=20,
        verbose_name="情感分类"
    )

    confidence = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="置信度"
    )

    keywords = models.JSONField(
        default=list,
        blank=True,
        verbose_name="关键词"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = "sentiment_cache"
        verbose_name = "情感分析缓存"
        verbose_name_plural = "情感分析缓存"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.text_hash[:8]}... - {self.sentiment_score:.2f}"
