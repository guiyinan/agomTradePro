# ruff: noqa: F401, I001
"""API and use-case regression tests for AI capability routing."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai_capability.application.dtos import RouteRequestDTO
from apps.ai_capability.application.use_cases import (
    CapabilityExecutionDispatcher,
    RouteMessageUseCase,
    SyncCapabilitiesUseCase,
)
from apps.ai_capability.infrastructure.models import CapabilityCatalogModel
from apps.config_center.infrastructure.decision_runtime_models import (
    DecisionRuntimeStateModel,
)
from apps.terminal.infrastructure.models import TerminalRuntimeSettingsORM


@pytest.fixture
def api_client(db):
    """Return an HTTP client with an explicit active decision-runtime gate."""

    DecisionRuntimeStateModel._default_manager.update_or_create(
        state_id=1,
        defaults={
            "status": "active",
            "reason": "",
            "changed_at": timezone.now(),
            "changed_by": "test:ai-capability-api-client",
            "release_ref": "test",
            "expected_resume_at": None,
        },
    )
    return APIClient()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="cap_staff",
        password="test123",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="cap_regular",
        password="test123",
        is_staff=False,
    )


@pytest.fixture
def write_capability(db):
    return CapabilityCatalogModel.objects.create(
        capability_key="api.post.api.runtime.reset",
        source_type="api",
        source_ref="POST api/runtime/reset/",
        name="Runtime Reset",
        summary="Reset runtime state",
        description="Reset runtime state for the system",
        route_group="write_api",
        category="runtime",
        execution_target={"type": "api", "method": "POST", "path": "api/runtime/reset/"},
        risk_level="high",
        requires_confirmation=True,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=False,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=True,
        review_status="auto",
    )


@pytest.fixture
def builtin_status_capability(db):
    return CapabilityCatalogModel.objects.create(
        capability_key="builtin.system_status",
        source_type="builtin",
        source_ref="builtin://system_status",
        name="System Status",
        summary="Read system readiness",
        description="Return the current system readiness summary",
        route_group="builtin",
        category="system",
        execution_target={"handler": "system_status"},
        risk_level="safe",
        requires_confirmation=True,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=False,
        review_status="approved",
    )


@pytest.fixture
def mcp_tool_capability(db):
    return CapabilityCatalogModel.objects.create(
        capability_key="mcp_tool.get_macro_summary",
        source_type="mcp_tool",
        source_ref="get_macro_summary",
        name="get_macro_summary",
        summary="Read macro summary",
        description="Read macro summary from MCP",
        route_group="tool",
        category="mcp",
        execution_target={"type": "mcp_tool", "tool_name": "get_macro_summary"},
        risk_level="low",
        requires_mcp=True,
        requires_confirmation=True,
        enabled_for_routing=True,
        enabled_for_terminal=False,
        enabled_for_chat=False,
        enabled_for_agent=True,
        visibility="admin",
        auto_collected=True,
        review_status="approved",
    )


__all__ = [name for name in globals() if not name.startswith("__")]
