"""Governed ORM persistence for AI provider configuration and usage evidence."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from itertools import islice
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.base import ModelBase

from shared.infrastructure.crypto import FieldEncryptionService

_SENSITIVE_CONFIG_KEYS = frozenset(
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


def _contains_control(value: str) -> bool:
    """Return whether a persisted identifier contains unsafe controls."""

    return any(character in value for character in "\r\n\x00")


def _bounded_text(value: object, *, field_name: str, maximum: int) -> str:
    """Normalize one non-empty, bounded identifier."""

    if not isinstance(value, str):
        raise ValidationError({field_name: f"{field_name} must be a string"})
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or _contains_control(normalized):
        raise ValidationError({field_name: f"{field_name} is invalid"})
    return normalized


def _money_limit(value: object, *, field_name: str) -> Decimal | None:
    """Normalize one optional finite non-negative monetary limit."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal | str):
        raise ValidationError({field_name: f"{field_name} must be finite and non-negative"})
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(
            {field_name: f"{field_name} must be finite and non-negative"}
        ) from exc
    if not normalized.is_finite() or normalized < 0:
        raise ValidationError({field_name: f"{field_name} must be finite and non-negative"})
    return normalized


def _sensitive_key(value: str) -> bool:
    """Classify credential-bearing JSON keys."""

    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized in _SENSITIVE_CONFIG_KEYS or normalized.endswith(
        ("_password", "_secret", "_token", "_credential")
    )


def _canonical_extra_config(value: object) -> dict[str, Any]:
    """Validate finite, credential-free provider runtime options."""

    nodes = 0

    def inspect(item: object, *, depth: int, path: str) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 10_000 or depth > 20:
            raise ValidationError({"extra_config": "extra_config is too deeply nested"})
        if item is None or isinstance(item, bool | int | str):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValidationError({"extra_config": f"{path} must be finite"})
            return
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                if not isinstance(raw_key, str) or not raw_key or len(raw_key) > 200:
                    raise ValidationError({"extra_config": f"{path} contains an invalid key"})
                if _sensitive_key(raw_key):
                    raise ValidationError(
                        {"extra_config": "credentials are not allowed in extra_config"}
                    )
                inspect(child, depth=depth + 1, path=f"{path}.{raw_key}")
            return
        if isinstance(item, Sequence) and not isinstance(item, str | bytes | bytearray):
            if len(item) > 1_000:
                raise ValidationError({"extra_config": f"{path} contains too many items"})
            for index, child in enumerate(item):
                inspect(child, depth=depth + 1, path=f"{path}[{index}]")
            return
        raise ValidationError({"extra_config": f"{path} contains a non-JSON value"})

    if not isinstance(value, dict):
        raise ValidationError({"extra_config": "extra_config must be an object"})
    inspect(value, depth=0, path="extra_config")
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > 262_144:
        raise ValidationError({"extra_config": "extra_config exceeds 256 KiB"})
    normalized = json.loads(encoded.decode("utf-8"))
    if not isinstance(normalized, dict):
        raise ValidationError({"extra_config": "extra_config must be an object"})
    _validate_known_runtime_options(normalized)
    return normalized


def _validate_known_runtime_options(config: dict[str, Any]) -> None:
    """Validate known adapter options while preserving custom provider fields."""

    numeric_ranges = {
        "timeout": (0.001, 300.0),
        "temperature": (0.0, 2.0),
    }
    for key, (minimum, maximum) in numeric_ranges.items():
        if key not in config:
            continue
        value = config[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            or not minimum <= float(value) <= maximum
        ):
            raise ValidationError({"extra_config": f"extra_config.{key} is invalid"})
    for key, minimum, maximum in (
        ("max_retries", 0, 10),
        ("max_tokens", 1, 1_000_000),
    ):
        if key not in config:
            continue
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValidationError({"extra_config": f"extra_config.{key} is invalid"})
    if "supported_models" in config:
        models_value = config["supported_models"]
        if (
            not isinstance(models_value, list)
            or not 1 <= len(models_value) <= 100
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item) > 100
                or _contains_control(item)
                for item in models_value
            )
            or len(models_value) != len(set(models_value))
        ):
            raise ValidationError({"extra_config": "extra_config.supported_models is invalid"})


def _redact_text(value: object, *, maximum: int = 1_000) -> str:
    """Redact credential forms from bounded usage evidence text."""

    text = str(value or "")
    redacted = _CREDENTIAL_URL_PATTERN.sub(r"\1://***@", text)
    redacted = _BEARER_PATTERN.sub("Bearer ***", redacted)
    redacted = _SECRET_ASSIGNMENT_PATTERN.sub(r"\1=***", redacted)
    return redacted[:maximum]


def _redact_metadata(value: object) -> dict[str, Any]:
    """Detach and redact bounded usage metadata."""

    if not isinstance(value, dict):
        raise ValidationError({"request_metadata": "request_metadata must be an object"})

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
        raise ValidationError({"request_metadata": "request_metadata must be an object"})
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 262_144:
        return {"_redacted": "payload_too_large"}
    return normalized


def _nonnegative_int(value: object, *, field_name: str) -> int:
    """Validate one non-negative accounting counter."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError({field_name: f"{field_name} must be a non-negative integer"})
    return value


class AppendOnlyUsageEvidenceMixin(models.Model):
    """Reject mutation and deletion of inserted usage evidence."""

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
            raise ValidationError("AI usage evidence is immutable.")
        self._prepare_and_validate()
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def _prepare_and_validate(self) -> None:
        """Validate one new usage row."""

        self.full_clean()

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject deletion of append-only usage evidence."""

        raise ValidationError("AI usage evidence cannot be deleted.")


class AIProviderConfig(models.Model):
    """
    AI提供商配置 ORM 模型

    参考 DataSourceConfig 设计，支持OpenAI兼容的多个AI提供商。
    """

    PROVIDER_TYPE_CHOICES = [
        ("openai", "OpenAI"),
        ("deepseek", "DeepSeek"),
        ("qwen", "通义千问"),
        ("moonshot", "Moonshot"),
        ("custom", "自定义"),
    ]
    API_MODE_CHOICES = [
        ("dual", "Dual (Responses + Chat Fallback)"),
        ("responses_only", "Responses Only"),
        ("chat_only", "Chat Completions Only"),
    ]
    SCOPE_CHOICES = [
        ("system", "System"),
        ("user", "User"),
    ]

    # 基本信息
    name = models.CharField(max_length=50, db_index=True, help_text="配置名称（唯一标识）")
    scope = models.CharField(
        max_length=20,
        choices=SCOPE_CHOICES,
        default="system",
        db_index=True,
        help_text="配置归属范围（system/user）",
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ai_provider_configs",
        help_text="当 scope=user 时对应的拥有者",
    )
    provider_type = models.CharField(
        max_length=20, choices=PROVIDER_TYPE_CHOICES, help_text="提供商类型"
    )
    is_active = models.BooleanField(default=True, help_text="是否启用")
    priority = models.IntegerField(
        default=10, db_index=True, help_text="优先级（数字越小越优先，用于failover）"
    )

    # 连接配置
    base_url = models.URLField(
        max_length=500, help_text="API Base URL（如 https://api.openai.com/v1）"
    )
    api_key = models.CharField(
        max_length=500,
        blank=True,
        help_text="API Key (plaintext, deprecated - use api_key_encrypted)",
    )
    api_key_encrypted = models.TextField(blank=True, help_text="API Key (encrypted at rest)")
    default_model = models.CharField(
        max_length=50, default="gpt-3.5-turbo", help_text="默认模型名称"
    )
    api_mode = models.CharField(
        max_length=20,
        choices=API_MODE_CHOICES,
        default="dual",
        help_text="OpenAI API 模式：dual/responses_only/chat_only",
    )
    fallback_enabled = models.BooleanField(
        default=True,
        help_text="dual 模式下是否允许从 Responses 回退到 Chat Completions",
    )

    # 预算控制
    daily_budget_limit = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="每日预算限制（美元）"
    )
    monthly_budget_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="每月预算限制（美元）"
    )

    # 额外配置
    extra_config = models.JSONField(default=dict, blank=True, help_text="额外配置参数")
    description = models.TextField(blank=True, help_text="描述")

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True, help_text="最后使用时间")

    class Meta:
        db_table = "ai_provider_config"
        ordering = ["priority", "name"]
        verbose_name = "AI提供商配置"
        verbose_name_plural = "AI提供商配置"
        indexes = [
            models.Index(fields=["scope", "owner_user", "is_active"]),
            models.Index(fields=["provider_type", "is_active"]),
            models.Index(fields=["is_active", "priority"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["owner_user", "name"],
                condition=Q(scope="user"),
                name="ai_provider_user_name_unique",
            ),
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(scope="system"),
                name="ai_provider_system_name_unique",
            ),
        ]

    def clean(self) -> None:
        """Validate scope, connection, credential and budget invariants."""

        super().clean()
        self.name = _bounded_text(self.name, field_name="name", maximum=50)
        self.default_model = _bounded_text(
            self.default_model, field_name="default_model", maximum=50
        )
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValidationError({"priority": "priority must be a positive integer"})
        if not 1 <= self.priority <= 10_000:
            raise ValidationError({"priority": "priority must be between 1 and 10000"})
        if self.scope == "system" and self.owner_user_id is not None:
            raise ValidationError({"owner_user": "system providers cannot have an owner"})
        if self.scope == "user" and self.owner_user_id is None:
            raise ValidationError({"owner_user": "user providers require an owner"})
        if not isinstance(self.base_url, str):
            raise ValidationError({"base_url": "base_url must be a string"})
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or len(self.base_url) > 500
            or _contains_control(self.base_url)
        ):
            raise ValidationError(
                {"base_url": "base_url must be an HTTP(S) URL without credentials"}
            )
        if not isinstance(self.api_key, str) or not isinstance(self.api_key_encrypted, str):
            raise ValidationError("API key fields must be strings")
        if self.api_key and self.api_key_encrypted:
            raise ValidationError("plaintext and encrypted API keys cannot both be populated")
        if self.api_key_encrypted and not self.api_key_encrypted.startswith(
            FieldEncryptionService.PREFIX
        ):
            raise ValidationError({"api_key_encrypted": "encrypted API key format is invalid"})
        if len(self.api_key_encrypted) > 10_000:
            raise ValidationError({"api_key_encrypted": "encrypted API key is too large"})
        self.daily_budget_limit = _money_limit(
            self.daily_budget_limit, field_name="daily_budget_limit"
        )
        self.monthly_budget_limit = _money_limit(
            self.monthly_budget_limit, field_name="monthly_budget_limit"
        )
        if (
            self.daily_budget_limit is not None
            and self.monthly_budget_limit is not None
            and self.daily_budget_limit > self.monthly_budget_limit
        ):
            raise ValidationError(
                {"monthly_budget_limit": "monthly budget cannot be below the daily budget"}
            )
        self.extra_config = _canonical_extra_config(self.extra_config)
        if not isinstance(self.description, str) or len(self.description) > 5_000:
            raise ValidationError({"description": "description exceeds 5000 characters"})

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Run model validation for every provider write."""

        # Validate raw caller values before Django fields coerce booleans or strings.
        self.clean()
        self.full_clean()
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def __str__(self) -> str:
        return f"{self.name} ({self.scope}:{self.get_provider_type_display()})"


class AIUsageLog(AppendOnlyUsageEvidenceMixin):
    """
    AI API调用日志 ORM 模型

    记录每次API调用的详细信息，用于统计和成本追踪。
    """

    PROVIDER_SCOPE_CHOICES = [
        ("system_global", "System Global"),
        ("system_fallback", "System Fallback"),
        ("personal", "Personal"),
    ]
    STATUS_CHOICES = [
        ("success", "成功"),
        ("error", "错误"),
        ("timeout", "超时"),
        ("rate_limited", "限流"),
    ]

    # 关联提供商
    provider = models.ForeignKey(
        AIProviderConfig, on_delete=models.CASCADE, related_name="usage_logs", db_index=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_usage_logs",
        db_index=True,
    )
    provider_scope = models.CharField(
        max_length=20,
        choices=PROVIDER_SCOPE_CHOICES,
        default="system_global",
        db_index=True,
        help_text="命中的 provider 归属范围",
    )
    quota_charged = models.BooleanField(
        default=False,
        help_text="是否计入用户系统兜底额度",
    )

    # 请求信息
    model = models.CharField(max_length=50, db_index=True, help_text="使用的模型")
    request_type = models.CharField(
        max_length=20, default="chat", help_text="请求类型（chat/completion/embedding等）"
    )

    # Token使用
    prompt_tokens = models.IntegerField(default=0, help_text="输入token数量")
    completion_tokens = models.IntegerField(default=0, help_text="输出token数量")
    total_tokens = models.IntegerField(default=0, db_index=True, help_text="总token数量")

    # 性能
    response_time_ms = models.IntegerField(help_text="响应时间（毫秒）")

    # 成本
    estimated_cost = models.DecimalField(
        max_digits=10, decimal_places=6, db_index=True, help_text="预估成本（美元）"
    )

    # 状态
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, db_index=True, help_text="调用状态"
    )
    error_message = models.TextField(blank=True, help_text="错误信息")

    # 元数据
    request_metadata = models.JSONField(default=dict, blank=True, help_text="请求元数据")

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, help_text="创建时间")

    class Meta:
        db_table = "ai_usage_log"
        ordering = ["-created_at"]
        verbose_name = "AI调用日志"
        verbose_name_plural = "AI调用日志"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["provider_scope", "-created_at"]),
            models.Index(fields=["provider", "-created_at"]),
            models.Index(fields=["model", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def _prepare_and_validate(self) -> None:
        """Validate, attribute and redact one usage evidence row."""

        self.model = _bounded_text(self.model, field_name="model", maximum=50)
        self.request_type = _bounded_text(self.request_type, field_name="request_type", maximum=20)
        self.prompt_tokens = _nonnegative_int(self.prompt_tokens, field_name="prompt_tokens")
        self.completion_tokens = _nonnegative_int(
            self.completion_tokens, field_name="completion_tokens"
        )
        self.total_tokens = _nonnegative_int(self.total_tokens, field_name="total_tokens")
        self.response_time_ms = _nonnegative_int(
            self.response_time_ms, field_name="response_time_ms"
        )
        if self.total_tokens < self.prompt_tokens + self.completion_tokens:
            raise ValidationError(
                {"total_tokens": "total_tokens cannot be below prompt plus completion"}
            )
        self.estimated_cost = _money_limit(
            self.estimated_cost, field_name="estimated_cost"
        ) or Decimal("0")
        if self.provider_scope == "personal":
            if (
                self.user_id is None
                or self.provider.scope != "user"
                or self.provider.owner_user_id != self.user_id
                or self.quota_charged
            ):
                raise ValidationError("personal usage attribution is invalid")
        elif self.provider_scope == "system_fallback":
            if self.user_id is None or self.provider.scope != "system" or not self.quota_charged:
                raise ValidationError("system fallback usage attribution is invalid")
        elif self.provider_scope == "system_global":
            if self.provider.scope != "system" or self.quota_charged:
                raise ValidationError("system global usage attribution is invalid")
        self.error_message = "" if self.status == "success" else _redact_text(self.error_message)
        self.request_metadata = _redact_metadata(self.request_metadata)
        self.full_clean()

    def __str__(self) -> str:
        created = self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "unsaved"
        return f"{self.provider.name} - {self.model} - {created}"


class AIUserFallbackQuota(models.Model):
    """User-scoped quota for consuming system fallback providers."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_fallback_quota",
    )
    daily_limit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="每日系统兜底额度（美元）",
    )
    monthly_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="每月系统兜底额度（美元）",
    )
    is_active = models.BooleanField(default=True, help_text="是否启用用户系统兜底额度")
    admin_note = models.TextField(blank=True, help_text="管理员备注")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_user_fallback_quota"
        verbose_name = "AI 用户兜底额度"
        verbose_name_plural = "AI 用户兜底额度"
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def clean(self) -> None:
        """Validate one finite, internally consistent fallback quota."""

        super().clean()
        self.daily_limit = _money_limit(self.daily_limit, field_name="daily_limit")
        self.monthly_limit = _money_limit(self.monthly_limit, field_name="monthly_limit")
        if (
            self.daily_limit is not None
            and self.monthly_limit is not None
            and self.daily_limit > self.monthly_limit
        ):
            raise ValidationError({"monthly_limit": "monthly limit cannot be below daily limit"})
        if not isinstance(self.admin_note, str) or len(self.admin_note) > 5_000:
            raise ValidationError({"admin_note": "admin_note exceeds 5000 characters"})

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Run quota validation for every ORM write."""

        # Validate raw caller values before Django fields coerce booleans or strings.
        self.clean()
        self.full_clean()
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def __str__(self) -> str:
        return f"{self.user} fallback quota"
