"""Typed Prompt Admin views that preserve immutable evaluation governance."""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest

from apps.prompt.models import (
    ChainConfigORM,
    ChatSessionORM,
    PromptExecutionLogORM,
    PromptTemplateORM,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def _prompt_eval_gate_enabled() -> bool:
    """Read the dynamic project setting through a typed boolean boundary."""

    return bool(getattr(settings, "PROMPT_EVAL_GATE_ENABLED", False))


@admin.register(PromptTemplateORM)
class PromptTemplateAdmin(TypedModelAdmin[PromptTemplateORM]):
    """Inspect legacy templates without bypassing immutable version promotion."""

    list_display = [
        "name",
        "category",
        "version",
        "is_active",
        "temperature",
        "last_used_at",
        "created_at",
    ]
    list_filter = ["category", "is_active"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_at", "updated_at", "last_used_at"]
    ordering = ["category", "name"]
    fieldsets = (
        ("基本信息", {"fields": ("name", "category", "version", "description", "is_active")}),
        ("模板内容", {"fields": ("template_content", "system_prompt", "placeholders")}),
        ("AI参数", {"fields": ("temperature", "max_tokens")}),
        (
            "时间信息",
            {"fields": ("created_at", "updated_at", "last_used_at"), "classes": ("collapse",)},
        ),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Route creation through PromptVersion evaluation while the gate is enabled."""

        return super().has_add_permission(request) and not _prompt_eval_gate_enabled()

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: PromptTemplateORM | None = None,
    ) -> bool:
        """Prevent direct mutation of legacy templates under immutable governance."""

        return super().has_change_permission(request, obj) and not _prompt_eval_gate_enabled()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: PromptTemplateORM | None = None,
    ) -> bool:
        """Preserve template references held by execution and decision evidence."""

        del request, obj
        return False


@admin.register(ChainConfigORM)
class ChainConfigAdmin(TypedModelAdmin[ChainConfigORM]):
    """Manage Prompt chain orchestration definitions."""

    list_display = ["name", "category", "execution_mode", "is_active", "created_at"]
    list_filter = ["category", "execution_mode", "is_active"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(PromptExecutionLogORM)
class PromptExecutionLogAdmin(TypedModelAdmin[PromptExecutionLogORM]):
    """Expose immutable Prompt execution evidence for inspection."""

    list_display = [
        "execution_id",
        "template",
        "status",
        "response_time_ms",
        "total_tokens",
        "created_at",
    ]
    list_filter = ["status", "provider_used"]
    search_fields = ["execution_id", "template__name"]
    readonly_fields = [field.name for field in PromptExecutionLogORM._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent operators from fabricating execution evidence."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: PromptExecutionLogORM | None = None,
    ) -> bool:
        """Keep Prompt execution evidence immutable."""

        del request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: PromptExecutionLogORM | None = None,
    ) -> bool:
        """Prevent deletion of Prompt execution evidence through Admin."""

        del request, obj
        return False


@admin.register(ChatSessionORM)
class ChatSessionAdmin(TypedModelAdmin[ChatSessionORM]):
    """Expose private chat sessions as immutable operational evidence."""

    list_display = ["session_id", "created_at"]
    search_fields = ["session_id", "user_message"]
    readonly_fields = [field.name for field in ChatSessionORM._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent operators from fabricating chat sessions."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: ChatSessionORM | None = None,
    ) -> bool:
        """Keep private chat content immutable."""

        del request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ChatSessionORM | None = None,
    ) -> bool:
        """Prevent deletion of chat evidence through Admin."""

        del request, obj
        return False
