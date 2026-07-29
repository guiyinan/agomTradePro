"""Sentiment 模块 - Infrastructure 层数据模型.

本模块包含 Django ORM 模型定义。
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from itertools import islice
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.base import ModelBase
from django.utils import timezone

_CATEGORIES = frozenset({"POSITIVE", "NEGATIVE", "NEUTRAL"})
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "password",
        "private_key",
        "secret",
        "session",
        "token",
    }
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|secret|token|api[_-]?key|authorization|cookie|credential)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_CREDENTIAL_URL_PATTERN = re.compile(r"(?i)\b(https?|postgres(?:ql)?|redis)://[^\s/@:]+:[^\s/@]+@")


def _bounded_text(
    value: object,
    *,
    field_name: str,
    maximum: int,
    allow_blank: bool = False,
) -> str:
    """Normalize one bounded persisted string."""

    if not isinstance(value, str):
        raise ValidationError({field_name: f"{field_name} must be a string"})
    normalized = value.strip()
    if (
        (not normalized and not allow_blank)
        or len(normalized) > maximum
        or any(character in normalized for character in "\r\n\x00")
    ):
        raise ValidationError({field_name: f"{field_name} is invalid"})
    return normalized


def _finite_score(
    value: object,
    *,
    field_name: str,
    minimum: float,
    maximum: float,
) -> float:
    """Normalize one bounded finite model score."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError({field_name: f"{field_name} must be a finite number"})
    normalized = float(value)
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise ValidationError(
            {field_name: f"{field_name} must be finite and between {minimum} and {maximum}"}
        )
    return normalized


def _nonnegative_int(value: object, *, field_name: str) -> int:
    """Validate one non-negative accounting counter."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError({field_name: f"{field_name} must be a non-negative integer"})
    return value


def _keywords(value: object) -> list[str]:
    """Detach and validate a bounded keyword list."""

    if not isinstance(value, list) or len(value) > 100:
        raise ValidationError({"keywords": "keywords must be an array of at most 100 items"})
    normalized = [_bounded_text(item, field_name="keywords", maximum=100) for item in value]
    if len(normalized) != len(set(normalized)):
        raise ValidationError({"keywords": "keywords must be unique"})
    return normalized


def _sector_sentiment(value: object) -> dict[str, float]:
    """Detach and validate the bounded sector score map."""

    if not isinstance(value, dict) or len(value) > 500:
        raise ValidationError(
            {"sector_sentiment": "sector_sentiment must be an object with at most 500 items"}
        )
    normalized: dict[str, float] = {}
    for raw_key, raw_score in value.items():
        key = _bounded_text(raw_key, field_name="sector_sentiment", maximum=100)
        if key in normalized:
            raise ValidationError({"sector_sentiment": "sector names must be unique"})
        normalized[key] = _finite_score(
            raw_score,
            field_name="sector_sentiment",
            minimum=-3.0,
            maximum=3.0,
        )
    return normalized


def _sensitive_key(value: str) -> bool:
    """Classify credential-bearing evidence keys."""

    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        ("_password", "_secret", "_token", "_credential")
    )


def _redact_text(value: object, *, maximum: int) -> str:
    """Bound and redact common credential forms from evidence text."""

    text = str(value or "")
    redacted = _CREDENTIAL_URL_PATTERN.sub(r"\1://***@", text)
    redacted = _BEARER_PATTERN.sub("Bearer ***", redacted)
    redacted = _SECRET_ASSIGNMENT_PATTERN.sub(r"\1=***", redacted)
    return redacted[:maximum]


def _redacted_metadata(value: object) -> dict[str, Any] | None:
    """Detach, bound and redact alert metadata."""

    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError({"metadata": "metadata must be an object"})

    def visit(item: object, *, depth: int) -> object:
        if depth > 10:
            return "[truncated]"
        if item is None or isinstance(item, bool | int):
            return item
        if isinstance(item, float):
            return item if math.isfinite(item) else "[non_finite_number]"
        if isinstance(item, str):
            return _redact_text(item, maximum=2_000)
        if isinstance(item, Mapping):
            return {
                str(key)[:200]: (
                    "***" if _sensitive_key(str(key)) else visit(child, depth=depth + 1)
                )
                for key, child in islice(item.items(), 500)
            }
        if isinstance(item, Sequence) and not isinstance(item, str | bytes | bytearray):
            return [visit(child, depth=depth + 1) for child in islice(item, 500)]
        return f"[{type(item).__name__}]"

    normalized = visit(value, depth=0)
    if not isinstance(normalized, dict):
        raise ValidationError({"metadata": "metadata must be an object"})
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 262_144:
        return {"_redacted": "payload_too_large"}
    return normalized


class ValidatedSentimentModel(models.Model):
    """Run model contracts for every ordinary ORM write."""

    class Meta:
        abstract = True

    def _validate_raw_values(self) -> None:
        """Reject values that Django fields would otherwise coerce unsafely."""

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Validate raw and normalized values before persistence."""

        self._validate_raw_values()
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class AppendOnlySentimentEvidence(ValidatedSentimentModel):
    """Reject mutation and instance deletion of inserted analysis evidence."""

    class Meta:
        abstract = True

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Insert validated evidence and reject later updates."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("Sentiment analysis evidence is immutable.")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject deletion of append-only analysis evidence."""

        raise ValidationError("Sentiment analysis evidence cannot be deleted.")


class SentimentIndexModel(ValidatedSentimentModel):
    """
    舆情情绪指数表

    存储每日的综合情绪指数。
    """

    index_date = models.DateField(unique=True, db_index=True, verbose_name="指数日期")

    # 情绪指数（-3.0 ~ +3.0）
    news_sentiment = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)],
        verbose_name="新闻情绪",
    )

    policy_sentiment = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)],
        verbose_name="政策情绪",
    )

    composite_index = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)],
        db_index=True,
        verbose_name="综合指数",
    )

    # 置信度
    confidence_level = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="置信度",
    )

    # 数据充足性标记（区分"无数据"和"中性情绪"）
    data_sufficient = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="数据充足性",
        help_text="True 表示数据充足，False 表示无数据或数据不足",
    )

    # 分类情绪（JSON）
    sector_sentiment = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="行业情绪",
        help_text='格式: {"金融": 0.5, "科技": 0.8}',
    )

    # 数据来源统计
    news_count = models.IntegerField(default=0, verbose_name="新闻数量")

    policy_events_count = models.IntegerField(default=0, verbose_name="政策事件数量")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "sentiment_index"
        verbose_name = "情绪指数"
        verbose_name_plural = "情绪指数"
        ordering = ["-index_date"]

    def _validate_raw_values(self) -> None:
        """Reject booleans before numeric field coercion."""

        for field_name in (
            "news_sentiment",
            "policy_sentiment",
            "composite_index",
            "confidence_level",
            "news_count",
            "policy_events_count",
        ):
            if isinstance(getattr(self, field_name), bool):
                raise ValidationError({field_name: f"{field_name} cannot be a boolean"})

    def clean(self) -> None:
        """Validate one finite, bounded sentiment index fact."""

        super().clean()
        for field_name in ("news_sentiment", "policy_sentiment", "composite_index"):
            setattr(
                self,
                field_name,
                _finite_score(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=-3.0,
                    maximum=3.0,
                ),
            )
        self.confidence_level = _finite_score(
            self.confidence_level,
            field_name="confidence_level",
            minimum=0.0,
            maximum=1.0,
        )
        self.news_count = _nonnegative_int(self.news_count, field_name="news_count")
        self.policy_events_count = _nonnegative_int(
            self.policy_events_count, field_name="policy_events_count"
        )
        self.sector_sentiment = _sector_sentiment(self.sector_sentiment)

    def __str__(self) -> str:
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


class SentimentAnalysisLog(AppendOnlySentimentEvidence):
    """
    情感分析日志表

    记录每次情感分析的详细信息，用于追溯和调试。
    """

    # 输入信息
    source_type = models.CharField(
        max_length=50, verbose_name="数据源类型", help_text="news/policy/social/manual"
    )

    source_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="数据源ID")

    input_text = models.TextField(verbose_name="输入文本")

    # 分析结果
    sentiment_score = models.FloatField(
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)], verbose_name="情感评分"
    )

    category = models.CharField(max_length=20, verbose_name="情感分类")

    confidence = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)], verbose_name="置信度"
    )

    keywords = models.JSONField(default=list, blank=True, verbose_name="关键词")

    # AI 调用信息
    ai_provider = models.CharField(max_length=100, blank=True, null=True, verbose_name="AI提供商")

    ai_model = models.CharField(max_length=100, blank=True, null=True, verbose_name="AI模型")

    ai_response_time_ms = models.IntegerField(blank=True, null=True, verbose_name="AI响应时间(ms)")

    # 元信息
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="创建时间")

    class Meta:
        db_table = "sentiment_analysis_log"
        verbose_name = "情感分析日志"
        verbose_name_plural = "情感分析日志"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source_type", "source_id"]),
            models.Index(fields=["-created_at"]),
        ]

    def _validate_raw_values(self) -> None:
        """Reject booleans before numeric field coercion."""

        for field_name in ("sentiment_score", "confidence", "ai_response_time_ms"):
            if isinstance(getattr(self, field_name), bool):
                raise ValidationError({field_name: f"{field_name} cannot be a boolean"})

    def clean(self) -> None:
        """Validate and redact one AI analysis evidence row."""

        super().clean()
        self.source_type = _bounded_text(self.source_type, field_name="source_type", maximum=50)
        if self.source_id is not None:
            self.source_id = (
                _bounded_text(self.source_id, field_name="source_id", maximum=100, allow_blank=True)
                or None
            )
        if not isinstance(self.input_text, str) or not self.input_text:
            raise ValidationError({"input_text": "input_text is required"})
        self.input_text = _redact_text(self.input_text, maximum=1_048_576)
        self.sentiment_score = _finite_score(
            self.sentiment_score,
            field_name="sentiment_score",
            minimum=-3.0,
            maximum=3.0,
        )
        self.category = _bounded_text(self.category, field_name="category", maximum=20)
        if self.category not in _CATEGORIES:
            raise ValidationError({"category": "category is unsupported"})
        self.confidence = _finite_score(
            self.confidence,
            field_name="confidence",
            minimum=0.0,
            maximum=1.0,
        )
        self.keywords = _keywords(self.keywords)
        for field_name in ("ai_provider", "ai_model"):
            value = getattr(self, field_name)
            if value is not None:
                setattr(
                    self,
                    field_name,
                    _bounded_text(value, field_name=field_name, maximum=100, allow_blank=True)
                    or None,
                )
        if self.ai_response_time_ms is not None:
            self.ai_response_time_ms = _nonnegative_int(
                self.ai_response_time_ms, field_name="ai_response_time_ms"
            )

    def __str__(self) -> str:
        return f"{self.source_type} - {self.sentiment_score:.2f}"


class SentimentCache(ValidatedSentimentModel):
    """
    情感分析缓存表

    缓存文本的情感分析结果，避免重复调用 AI API。
    使用文本哈希作为缓存键。
    """

    text_hash = models.CharField(max_length=64, unique=True, db_index=True, verbose_name="文本哈希")

    sentiment_score = models.FloatField(
        validators=[MinValueValidator(-3.0), MaxValueValidator(3.0)], verbose_name="情感评分"
    )

    category = models.CharField(max_length=20, verbose_name="情感分类")

    confidence = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)], verbose_name="置信度"
    )

    keywords = models.JSONField(default=list, blank=True, verbose_name="关键词")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "sentiment_cache"
        verbose_name = "情感分析缓存"
        verbose_name_plural = "情感分析缓存"
        ordering = ["-updated_at"]

    def _validate_raw_values(self) -> None:
        """Reject booleans before numeric field coercion."""

        for field_name in ("sentiment_score", "confidence"):
            if isinstance(getattr(self, field_name), bool):
                raise ValidationError({field_name: f"{field_name} cannot be a boolean"})

    def clean(self) -> None:
        """Validate one bounded sentiment cache entry."""

        super().clean()
        self.text_hash = _bounded_text(self.text_hash, field_name="text_hash", maximum=64).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", self.text_hash):
            raise ValidationError({"text_hash": "text_hash must be a SHA-256 hex digest"})
        self.sentiment_score = _finite_score(
            self.sentiment_score,
            field_name="sentiment_score",
            minimum=-3.0,
            maximum=3.0,
        )
        self.category = _bounded_text(self.category, field_name="category", maximum=20)
        if self.category not in _CATEGORIES:
            raise ValidationError({"category": "category is unsupported"})
        self.confidence = _finite_score(
            self.confidence,
            field_name="confidence",
            minimum=0.0,
            maximum=1.0,
        )
        self.keywords = _keywords(self.keywords)

    def __str__(self) -> str:
        return f"{self.text_hash[:8]}... - {self.sentiment_score:.2f}"


class SentimentAlertModel(ValidatedSentimentModel):
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
        max_length=50, choices=ALERT_TYPE_CHOICES, db_index=True, verbose_name="告警类型"
    )

    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default=SEVERITY_WARNING,
        db_index=True,
        verbose_name="严重程度",
    )

    title = models.CharField(max_length=255, verbose_name="告警标题")

    message = models.TextField(verbose_name="告警详情")

    metadata = models.JSONField(null=True, blank=True, verbose_name="元数据")

    is_resolved = models.BooleanField(default=False, db_index=True, verbose_name="是否已解决")

    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="解决时间")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="创建时间")

    class Meta:
        db_table = "sentiment_alert"
        verbose_name = "Sentiment 告警"
        verbose_name_plural = "Sentiment 告警"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["alert_type", "is_resolved"]),
            models.Index(fields=["severity", "is_resolved"]),
        ]

    def clean(self) -> None:
        """Validate, redact and reconcile one sentiment alert."""

        super().clean()
        self.title = _bounded_text(self.title, field_name="title", maximum=255)
        if not isinstance(self.message, str) or not self.message:
            raise ValidationError({"message": "message is required"})
        self.message = _redact_text(self.message, maximum=5_000)
        self.metadata = _redacted_metadata(self.metadata)
        if self.is_resolved:
            if self.resolved_at is None or not timezone.is_aware(self.resolved_at):
                raise ValidationError(
                    {"resolved_at": "resolved alerts require an aware resolved_at"}
                )
        elif self.resolved_at is not None:
            raise ValidationError({"resolved_at": "unresolved alerts cannot have resolved_at"})

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.title}"

    def resolve(self) -> None:
        """标记告警为已解决"""
        self.is_resolved = True
        self.resolved_at = timezone.now()
        self.save()
