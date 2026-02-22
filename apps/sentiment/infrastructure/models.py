"""
Sentiment 模块 - Infrastructure 层数据模型

本模块包含 Django ORM 模型定义。
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


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

    # 数据充足性标记（区分"无数据"和"中性情绪"）
    data_sufficient = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="数据充足性",
        help_text="True 表示数据充足，False 表示无数据或数据不足"
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
        if not self.data_sufficient:
            return "数据不足"

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


class SentimentAlertModel(models.Model):
    """
    Sentiment 告警 ORM 模型

    存储 Sentiment 系统的告警信息，包括 AI 调用失败等。

    Attributes:
        alert_type: 告警类型
        severity: 严重程度（info/warning/error/critical）
        title: 告警标题
        message: 告警详情
        metadata: 元数据（JSON）
        is_resolved: 是否已解决
        resolved_at: 解决时间
        created_at: 创建时间
    """

    # Severity Choices
    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_ERROR = "error"
    SEVERITY_CRITICAL = "critical"

    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "信息"),
        (SEVERITY_WARNING, "警告"),
        (SEVERITY_ERROR, "错误"),
        (SEVERITY_CRITICAL, "严重"),
    ]

    # Alert Type Choices
    ALERT_AI_FAILURE = "ai_failure"
    ALERT_NO_DATA = "no_data"
    ALERT_DATA_STALE = "data_stale"

    ALERT_TYPE_CHOICES = [
        (ALERT_AI_FAILURE, "AI 调用失败"),
        (ALERT_NO_DATA, "无数据"),
        (ALERT_DATA_STALE, "数据过期"),
    ]

    alert_type = models.CharField(
        max_length=50,
        choices=ALERT_TYPE_CHOICES,
        db_index=True,
        verbose_name="告警类型"
    )

    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default=SEVERITY_WARNING,
        db_index=True,
        verbose_name="严重程度"
    )

    title = models.CharField(
        max_length=255,
        verbose_name="告警标题"
    )

    message = models.TextField(
        verbose_name="告警详情"
    )

    metadata = models.JSONField(
        null=True,
        blank=True,
        verbose_name="元数据"
    )

    is_resolved = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="是否已解决"
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="解决时间"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="创建时间"
    )

    class Meta:
        db_table = "sentiment_alert"
        verbose_name = "Sentiment 告警"
        verbose_name_plural = "Sentiment 告警"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["alert_type", "is_resolved"]),
            models.Index(fields=["severity", "is_resolved"]),
        ]

    def __str__(self):
        return f"[{self.severity.upper()}] {self.title}"

    def resolve(self) -> None:
        """标记告警为已解决"""
        self.is_resolved = True
        self.resolved_at = timezone.now()
        self.save()
