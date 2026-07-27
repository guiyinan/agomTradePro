"""Prompt Admin discovery, evaluation-gate, and evidence regressions."""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.test import RequestFactory, override_settings

from apps.prompt.interface.admin import (
    ChainConfigAdmin,
    ChatSessionAdmin,
    PromptExecutionLogAdmin,
    PromptTemplateAdmin,
)
from apps.prompt.models import (
    ChainConfigORM,
    ChatSessionORM,
    PromptExecutionLogORM,
    PromptTemplateORM,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def test_prompt_models_are_registered_once_through_typed_admins() -> None:
    """Django autodiscovery exposes all legacy Prompt operations models."""

    expected = {
        PromptTemplateORM: PromptTemplateAdmin,
        ChainConfigORM: ChainConfigAdmin,
        PromptExecutionLogORM: PromptExecutionLogAdmin,
        ChatSessionORM: ChatSessionAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)


@pytest.mark.django_db
def test_prompt_evaluation_gate_blocks_legacy_template_mutation(django_user_model: type) -> None:
    """Active immutable governance cannot be bypassed through legacy Admin forms."""

    request = RequestFactory().get("/admin/prompt/")
    request.user = django_user_model.objects.create_superuser(
        username="prompt-root",
        email="prompt-root@example.com",
        password="test-password",
    )
    template_admin = admin.site._registry[PromptTemplateORM]

    with override_settings(PROMPT_EVAL_GATE_ENABLED=True):
        assert template_admin.has_add_permission(request) is False
        assert template_admin.has_change_permission(request) is False
    with override_settings(PROMPT_EVAL_GATE_ENABLED=False):
        assert template_admin.has_add_permission(request) is True
        assert template_admin.has_change_permission(request) is True
    assert template_admin.has_delete_permission(request) is False


def test_prompt_execution_and_chat_evidence_are_fully_immutable() -> None:
    """Admin cannot fabricate, alter, or delete execution logs and chat content."""

    for model in (PromptExecutionLogORM, ChatSessionORM):
        evidence_admin = admin.site._registry[model]
        assert evidence_admin.has_add_permission(None) is False
        assert evidence_admin.has_change_permission(None) is False
        assert evidence_admin.has_delete_permission(None) is False
