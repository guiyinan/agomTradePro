"""ORM persistence for governed Prompt configuration and execution evidence."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from itertools import islice
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

_PLACEHOLDER_TYPES = frozenset({"simple", "structured", "function", "conditional"})
_PLACEHOLDER_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
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
        "session_id",
        "token",
    }
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|secret|token|api[_-]?key|authorization|cookie|credential)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_CREDENTIAL_URL_PATTERN = re.compile(r"(?i)\b(https?|postgres(?:ql)?|redis)://[^\s/@:]+:[^\s/@]+@")
_MAX_EVIDENCE_JSON_BYTES = 1_048_576
_MAX_EVIDENCE_TEXT = 50_000


def _contains_control(value: str) -> bool:
    """Return whether an identifier contains unsafe control characters."""

    return any(character in value for character in "\r\n\x00")


def _redact_text(value: str, *, max_length: int = _MAX_EVIDENCE_TEXT) -> str:
    """Redact common credential forms and bound persisted evidence text."""

    redacted = _CREDENTIAL_URL_PATTERN.sub(r"\1://***@", value)
    redacted = _BEARER_PATTERN.sub("Bearer ***", redacted)
    redacted = _SECRET_ASSIGNMENT_PATTERN.sub(r"\1=***", redacted)
    if len(redacted) > max_length:
        suffix = "...[truncated]"
        return f"{redacted[: max(0, max_length - len(suffix))]}{suffix}"
    return redacted


def _is_sensitive_key(value: str) -> bool:
    """Classify credential-bearing JSON keys without exposing their values."""

    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        ("_password", "_secret", "_token", "_credential")
    )


def _sanitize_json(value: object) -> object:
    """Return detached, finite and credential-redacted JSON evidence."""

    nodes = 0

    def visit(item: object, *, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if nodes > 10_000 or depth > 20:
            return "[truncated]"
        if item is None or isinstance(item, bool | int):
            return item
        if isinstance(item, float):
            return item if math.isfinite(item) else "[non_finite_number]"
        if isinstance(item, Decimal):
            return str(item) if item.is_finite() else "[non_finite_number]"
        if isinstance(item, str):
            return _redact_text(item, max_length=10_000)
        if isinstance(item, Mapping):
            normalized: dict[str, object] = {}
            for raw_key, raw_value in islice(item.items(), 1_000):
                key = str(raw_key)[:200]
                normalized[key] = (
                    "***" if _is_sensitive_key(key) else visit(raw_value, depth=depth + 1)
                )
            return normalized
        if isinstance(item, Sequence) and not isinstance(item, str | bytes | bytearray):
            return [visit(child, depth=depth + 1) for child in item[:1_000]]
        return f"[{type(item).__name__}]"

    sanitized = visit(value, depth=0)
    encoded = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_EVIDENCE_JSON_BYTES:
        return {"_redacted": "payload_too_large"}
    return sanitized


def _canonical_json(value: object, *, field_name: str, max_bytes: int = 65_536) -> object:
    """Validate and detach configuration JSON without lossy string coercion."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {field_name: f"{field_name} must contain finite JSON values"}
        ) from exc
    if len(encoded) > max_bytes:
        raise ValidationError({field_name: f"{field_name} exceeds the storage limit"})
    return json.loads(encoded.decode("utf-8"))


def _positive_token_limit(value: object) -> int | None:
    """Validate the optional model token ceiling."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 200_000:
        raise ValidationError({"max_tokens": "max_tokens must be between 1 and 200000"})
    return value


def _normalize_placeholder(value: object, *, index: int) -> dict[str, Any]:
    """Validate one persisted placeholder definition."""

    if not isinstance(value, dict):
        raise ValidationError({"placeholders": f"placeholder {index} must be an object"})
    allowed_keys = {
        "name",
        "type",
        "description",
        "default_value",
        "required",
        "function_name",
        "function_params",
    }
    if not set(value).issubset(allowed_keys):
        raise ValidationError({"placeholders": f"placeholder {index} contains unknown fields"})
    name = value.get("name")
    placeholder_type = value.get("type")
    description = value.get("description", "")
    required = value.get("required", True)
    if not isinstance(name, str) or not _PLACEHOLDER_NAME_PATTERN.fullmatch(name) or len(name) > 50:
        raise ValidationError({"placeholders": f"placeholder {index} has an invalid name"})
    if placeholder_type not in _PLACEHOLDER_TYPES:
        raise ValidationError({"placeholders": f"placeholder {index} has an invalid type"})
    if (
        not isinstance(description, str)
        or len(description) > 1_000
        or _contains_control(description)
    ):
        raise ValidationError({"placeholders": f"placeholder {index} has an invalid description"})
    if not isinstance(required, bool):
        raise ValidationError({"placeholders": f"placeholder {index}.required must be boolean"})
    function_name = value.get("function_name")
    if function_name in (None, ""):
        function_name = None
    elif (
        not isinstance(function_name, str)
        or not _PLACEHOLDER_NAME_PATTERN.fullmatch(function_name)
        or len(function_name) > 100
    ):
        raise ValidationError({"placeholders": f"placeholder {index} has an invalid function"})
    if placeholder_type == "function" and function_name is None:
        raise ValidationError({"placeholders": f"placeholder {index} requires function_name"})
    function_params = value.get("function_params")
    if function_params is not None and not isinstance(function_params, dict):
        raise ValidationError(
            {"placeholders": f"placeholder {index}.function_params must be an object"}
        )
    return {
        "name": name,
        "type": placeholder_type,
        "description": description,
        "default_value": _canonical_json(
            value.get("default_value"), field_name="placeholders", max_bytes=32_768
        ),
        "required": required,
        "function_name": function_name,
        "function_params": _canonical_json(
            function_params, field_name="placeholders", max_bytes=32_768
        ),
    }


def _normalize_chain_step(value: object, *, field_name: str) -> dict[str, Any]:
    """Validate and detach one persisted chain step."""

    if not isinstance(value, dict):
        raise ValidationError({"steps": f"{field_name} must be an object"})
    allowed_keys = {
        "step_id",
        "template_id",
        "step_name",
        "order",
        "input_mapping",
        "output_parser",
        "parallel_group",
        "enable_tool_calling",
        "available_tools",
    }
    if not set(value).issubset(allowed_keys):
        raise ValidationError({"steps": f"{field_name} contains unknown fields"})

    def text(key: str, *, maximum: int, optional: bool = False) -> str | None:
        raw = value.get(key)
        if optional and raw in (None, ""):
            return None
        if not isinstance(raw, str | int):
            raise ValidationError({"steps": f"{field_name}.{key} is invalid"})
        normalized = str(raw).strip()
        if not normalized or len(normalized) > maximum or _contains_control(normalized):
            raise ValidationError({"steps": f"{field_name}.{key} is invalid"})
        return normalized

    step_id = text("step_id", maximum=50)
    template_id = text("template_id", maximum=50)
    step_name = text("step_name", maximum=100)
    order = value.get("order")
    if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 10_000:
        raise ValidationError({"steps": f"{field_name}.order is invalid"})
    input_mapping = value.get("input_mapping")
    if not isinstance(input_mapping, dict) or len(input_mapping) > 100:
        raise ValidationError({"steps": f"{field_name}.input_mapping must be an object"})
    normalized_mapping: dict[str, str] = {}
    for raw_key, raw_value in input_mapping.items():
        if (
            not isinstance(raw_key, str)
            or not isinstance(raw_value, str)
            or not raw_key
            or len(raw_key) > 100
            or len(raw_value) > 1_000
            or _contains_control(raw_key)
            or _contains_control(raw_value)
        ):
            raise ValidationError({"steps": f"{field_name}.input_mapping is invalid"})
        normalized_mapping[raw_key] = raw_value
    enable_tool_calling = value.get("enable_tool_calling", False)
    if not isinstance(enable_tool_calling, bool):
        raise ValidationError({"steps": f"{field_name}.enable_tool_calling must be boolean"})
    available_tools = value.get("available_tools")
    if available_tools is not None:
        if (
            isinstance(available_tools, str)
            or not isinstance(available_tools, Sequence)
            or len(available_tools) > 100
        ):
            raise ValidationError({"steps": f"{field_name}.available_tools is invalid"})
        normalized_tools = [
            tool
            for tool in available_tools
            if isinstance(tool, str) and tool and len(tool) <= 100 and not _contains_control(tool)
        ]
        if len(normalized_tools) != len(available_tools) or len(set(normalized_tools)) != len(
            normalized_tools
        ):
            raise ValidationError({"steps": f"{field_name}.available_tools is invalid"})
        available_tools = normalized_tools
    return {
        "step_id": step_id,
        "template_id": template_id,
        "step_name": step_name,
        "order": order,
        "input_mapping": normalized_mapping,
        "output_parser": text("output_parser", maximum=1_000, optional=True),
        "parallel_group": text("parallel_group", maximum=100, optional=True),
        "enable_tool_calling": enable_tool_calling,
        "available_tools": available_tools,
    }


class AppendOnlyPromptEvidenceMixin(models.Model):
    """Allow one insert and reject later mutation or deletion of Prompt evidence."""

    class Meta:
        abstract = True

    def _prepare_and_validate(self) -> None:
        """Normalize and validate one new evidence record."""

        self.full_clean()

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Insert validated evidence and reject updates."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("Prompt execution evidence is immutable.")
        self._prepare_and_validate()
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject deletion of append-only Prompt evidence."""

        raise ValidationError("Prompt execution evidence cannot be deleted.")


class PromptTemplateORM(models.Model):
    """Prompt模板ORM模型"""

    CATEGORY_CHOICES = [
        ("report", "Report Analysis"),
        ("signal", "Signal Generation"),
        ("analysis", "Data Analysis"),
        ("chat", "Chat"),
    ]

    # 基本信息
    name = models.CharField(
        max_length=100, unique=True, db_index=True, help_text="模板名称（唯一标识）"
    )
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, db_index=True, help_text="分类"
    )
    version = models.CharField(max_length=20, default="1.0", help_text="版本号")

    # 模板内容
    template_content = models.TextField(help_text="模板内容（支持Jinja2语法）")
    system_prompt = models.TextField(blank=True, help_text="系统提示词")

    # 占位符定义（JSON存储）
    placeholders = models.JSONField(default=list, blank=True, help_text="占位符定义列表")

    # AI参数
    temperature = models.FloatField(default=0.7, help_text="温度参数（0.0-2.0）")
    max_tokens = models.IntegerField(null=True, blank=True, help_text="最大token数")

    # 元数据
    description = models.TextField(blank=True, help_text="描述")
    is_active = models.BooleanField(default=True, db_index=True, help_text="是否激活")

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")
    last_used_at = models.DateTimeField(null=True, blank=True, help_text="最后使用时间")

    class Meta:
        db_table = "prompt_template"
        ordering = ["category", "name"]
        verbose_name = "Prompt模板"
        verbose_name_plural = "Prompt模板"
        indexes = [
            models.Index(fields=["category", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.category}/{self.name}@{self.version}"

    def clean(self) -> None:
        """Validate and detach a legacy template before publication."""

        super().clean()
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, int | float):
            raise ValidationError({"temperature": "temperature must be a finite number"})
        temperature = float(self.temperature)
        if not math.isfinite(temperature) or not 0.0 <= temperature <= 2.0:
            raise ValidationError({"temperature": "temperature must be between 0 and 2"})
        self.temperature = temperature
        self.max_tokens = _positive_token_limit(self.max_tokens)
        if len(self.template_content) > 100_000:
            raise ValidationError(
                {"template_content": "template_content exceeds 100000 characters"}
            )
        if len(self.system_prompt) > 50_000:
            raise ValidationError({"system_prompt": "system_prompt exceeds 50000 characters"})
        if len(self.description) > 5_000:
            raise ValidationError({"description": "description exceeds 5000 characters"})
        if not isinstance(self.placeholders, list) or len(self.placeholders) > 100:
            raise ValidationError(
                {"placeholders": "placeholders must be a list of at most 100 items"}
            )
        normalized = [
            _normalize_placeholder(item, index=index)
            for index, item in enumerate(self.placeholders)
        ]
        names = [item["name"] for item in normalized]
        if len(names) != len(set(names)):
            raise ValidationError({"placeholders": "placeholder names must be unique"})
        self.placeholders = normalized

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Run model validation for every repository or ORM write."""

        self.clean()
        self.full_clean()
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class ChainConfigORM(models.Model):
    """链式配置ORM模型"""

    EXECUTION_MODE_CHOICES = [
        ("serial", "Serial"),
        ("parallel", "Parallel"),
        ("tool", "Tool Calling"),
        ("hybrid", "Hybrid"),
    ]

    name = models.CharField(
        max_length=100, unique=True, db_index=True, help_text="链名称（唯一标识）"
    )
    category = models.CharField(
        max_length=20, choices=PromptTemplateORM.CATEGORY_CHOICES, db_index=True, help_text="分类"
    )
    description = models.TextField(blank=True, help_text="描述")
    steps = models.JSONField(default=list, help_text="步骤定义列表")
    execution_mode = models.CharField(
        max_length=20, choices=EXECUTION_MODE_CHOICES, default="serial", help_text="执行模式"
    )
    aggregate_step = models.JSONField(null=True, blank=True, help_text="汇总步骤配置")
    is_active = models.BooleanField(default=True, db_index=True, help_text="是否激活")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")

    class Meta:
        db_table = "chain_config"
        ordering = ["category", "name"]
        verbose_name = "链配置"
        verbose_name_plural = "链配置"
        indexes = [
            models.Index(fields=["category", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.category}/{self.name} ({self.execution_mode})"

    def clean(self) -> None:
        """Validate executable chain structure before it becomes active."""

        super().clean()
        if not isinstance(self.steps, list) or len(self.steps) > 100:
            raise ValidationError({"steps": "steps must be a list of at most 100 items"})
        if self.is_active and not self.steps:
            raise ValidationError({"steps": "active chains require at least one step"})
        normalized_steps = [
            _normalize_chain_step(item, field_name=f"steps[{index}]")
            for index, item in enumerate(self.steps)
        ]
        step_ids = [step["step_id"] for step in normalized_steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValidationError({"steps": "step_id values must be unique"})
        order_groups: dict[int, set[str | None]] = {}
        for step in normalized_steps:
            order_groups.setdefault(step["order"], set()).add(step["parallel_group"])
        for order, groups in order_groups.items():
            order_count = sum(step["order"] == order for step in normalized_steps)
            if order_count > 1 and (None in groups or len(groups) != 1):
                raise ValidationError(
                    {"steps": "duplicate orders require one shared parallel_group"}
                )
        self.steps = normalized_steps
        if self.aggregate_step is not None:
            self.aggregate_step = _normalize_chain_step(
                self.aggregate_step, field_name="aggregate_step"
            )

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Run structural validation for every repository or ORM write."""

        self.clean()
        excluded_fields = {"steps"} if not self.is_active and not self.steps else None
        self.full_clean(exclude=excluded_fields)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class PromptExecutionLogORM(AppendOnlyPromptEvidenceMixin):
    """Prompt执行日志ORM模型"""

    STATUS_CHOICES = [
        ("success", "Success"),
        ("error", "Error"),
        ("timeout", "Timeout"),
    ]

    # 关联
    template = models.ForeignKey(
        PromptTemplateORM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execution_logs",
        help_text="关联的模板",
    )
    chain = models.ForeignKey(
        ChainConfigORM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execution_logs",
        help_text="关联的链",
    )

    # 执行信息
    execution_id = models.CharField(max_length=100, db_index=True, help_text="执行ID")
    step_id = models.CharField(max_length=50, null=True, blank=True, help_text="步骤ID")

    # 请求
    placeholder_values = models.JSONField(default=dict, blank=True, help_text="占位符值")
    rendered_prompt = models.TextField(help_text="渲染后的Prompt")

    # 响应
    ai_response = models.TextField(help_text="AI响应内容")
    parsed_output = models.JSONField(null=True, blank=True, help_text="解析后的输出")

    # 性能指标
    response_time_ms = models.IntegerField(help_text="响应时间（毫秒）")
    prompt_tokens = models.IntegerField(default=0, help_text="输入token数")
    completion_tokens = models.IntegerField(default=0, help_text="输出token数")
    total_tokens = models.IntegerField(default=0, help_text="总token数")
    estimated_cost = models.DecimalField(
        max_digits=10, decimal_places=6, default=0, help_text="预估成本"
    )

    # 提供商信息
    provider_used = models.CharField(max_length=50, blank=True, help_text="使用的提供商")
    model_used = models.CharField(max_length=50, blank=True, help_text="使用的模型")
    prompt_version_id = models.CharField(max_length=64, blank=True, db_index=True)
    output_schema_version = models.CharField(max_length=64, blank=True)
    eval_baseline_id = models.CharField(max_length=64, blank=True)
    decision_snapshot_id = models.CharField(max_length=64, blank=True, db_index=True)

    # 状态
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="success", help_text="执行状态"
    )
    error_message = models.TextField(blank=True, help_text="错误信息")

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, help_text="执行时间")

    class Meta:
        db_table = "prompt_execution_log"
        ordering = ["-created_at"]
        verbose_name = "执行日志"
        verbose_name_plural = "执行日志"
        indexes = [
            models.Index(fields=["execution_id", "-created_at"]),
            models.Index(fields=["template", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.execution_id} - {self.status}"

    def _prepare_and_validate(self) -> None:
        """Redact credentials and validate bounded execution evidence."""

        sanitized_placeholders = _sanitize_json(self.placeholder_values)
        if not isinstance(sanitized_placeholders, dict):
            raise ValidationError({"placeholder_values": "placeholder_values must be an object"})
        self.placeholder_values = sanitized_placeholders
        self.parsed_output = (
            None if self.parsed_output is None else _sanitize_json(self.parsed_output)
        )
        self.rendered_prompt = _redact_text(str(self.rendered_prompt or ""))
        self.ai_response = _redact_text(str(self.ai_response or ""))
        self.execution_id = _redact_text(str(self.execution_id or ""), max_length=100)
        self.provider_used = _redact_text(str(self.provider_used or ""), max_length=50)
        self.model_used = _redact_text(str(self.model_used or ""), max_length=50)
        if self.status == "timeout":
            self.error_message = "prompt_execution_timeout"
        elif self.status == "error":
            self.error_message = "prompt_execution_failed"
        else:
            self.error_message = ""
        for field_name in (
            "response_time_ms",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationError({field_name: f"{field_name} must be a non-negative integer"})
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValidationError(
                {"total_tokens": "total_tokens must equal prompt plus completion"}
            )
        try:
            cost = Decimal(str(self.estimated_cost))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError({"estimated_cost": "estimated_cost must be finite"}) from exc
        if not cost.is_finite() or cost < 0:
            raise ValidationError(
                {"estimated_cost": "estimated_cost must be finite and non-negative"}
            )
        self.estimated_cost = cost
        self.full_clean(exclude={"rendered_prompt", "ai_response"})


class ChatSessionORM(AppendOnlyPromptEvidenceMixin):
    """聊天会话ORM模型"""

    session_id = models.CharField(max_length=100, unique=True, db_index=True, help_text="会话ID")
    user_message = models.TextField(help_text="用户消息")
    ai_response = models.TextField(help_text="AI响应")
    context = models.JSONField(default=dict, blank=True, help_text="上下文数据")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, help_text="创建时间")

    class Meta:
        db_table = "chat_session"
        ordering = ["-created_at"]
        verbose_name = "聊天会话"
        verbose_name_plural = "聊天会话"

    def __str__(self) -> str:
        return f"Session: {self.session_id}"

    def _prepare_and_validate(self) -> None:
        """Redact and bound persisted chat evidence before insertion."""

        self.user_message = _redact_text(str(self.user_message or ""))
        self.ai_response = _redact_text(str(self.ai_response or ""))
        self.session_id = _redact_text(str(self.session_id or ""), max_length=100)
        sanitized_context = _sanitize_json(self.context)
        if not isinstance(sanitized_context, dict):
            raise ValidationError({"context": "context must be an object"})
        self.context = sanitized_context
        self.full_clean()
