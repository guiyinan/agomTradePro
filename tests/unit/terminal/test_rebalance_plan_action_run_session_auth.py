"""Contract checks for Session-only plan actions through the generic TUI runner."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.account.infrastructure.models import AccountProfileModel, UserAccessTokenModel
from apps.terminal.interface import api_views

_ACTION_KEY = "rebalance-plan.list"
_ACTION_URL = f"/api/tui/actions/{_ACTION_KEY}/run/"
_DEFAULT_SCREEN = "task.rebalance-plan"


def _metadata_payload() -> dict[str, Any]:
    """Return the minimal published action needed by the generic action runner."""

    return {
        "default_screen": _DEFAULT_SCREEN,
        "modules": [{"key": "daily-decisions", "label": "日常决策"}],
        "screens": [
            {
                "key": _DEFAULT_SCREEN,
                "module_key": "daily-decisions",
                "label": "模拟账户调仓",
                "view_type": "datagrid",
                "default_action_key": _ACTION_KEY,
            }
        ],
        "actions": [
            {
                "key": _ACTION_KEY,
                "label": "计划列表",
                "description": "读取本人模拟调仓计划。",
                "intent": "rebalance-plan",
                "screen_key": _DEFAULT_SCREEN,
                "module_key": "daily-decisions",
                "risk": "read",
                "view_type": "datagrid",
                "method": "GET",
                "endpoint": "/api/simulated-trading/accounts/<int:account_id>/rebalance-plans/",
                "fields": [
                    {
                        "key": "account_id",
                        "label": "本人模拟账户",
                        "binding": "path",
                        "input_type": "hidden",
                        "value_type": "integer",
                        "required": True,
                    }
                ],
                "session_auth_required": True,
            }
        ],
    }


class _MetadataRepository:
    def load_published(self, registry_key: str = "default") -> dict[str, Any]:
        return _metadata_payload()


class _AuditRepository:
    def save(self, entry: Any) -> Any:
        return entry


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "status_code": 200,
            "payload": {
                "success": True,
                "outcome": "success",
                "view_model": {"kind": "detail", "fields": []},
            },
        }


def _create_mcp_enabled_user(username: str) -> Any:
    user = get_user_model().objects.create_user(username=username, password="test-password")
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": username,
            "initial_capital": Decimal("1000000.00"),
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
            "mcp_enabled": True,
        },
    )
    return user


def _install_action_run_dependencies(monkeypatch: pytest.MonkeyPatch) -> _RecordingExecutor:
    executor = _RecordingExecutor()
    monkeypatch.setattr(
        api_views,
        "get_tui_metadata_repository",
        lambda: _MetadataRepository(),
    )
    monkeypatch.setattr(
        api_views,
        "get_terminal_audit_repository",
        lambda: _AuditRepository(),
    )
    monkeypatch.setattr(api_views, "get_tui_action_executor", lambda: executor)
    return executor


@pytest.mark.django_db
def test_write_enabled_api_token_cannot_proxy_session_only_plan_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real token-authenticated generic action run is denied before execution."""

    user = _create_mcp_enabled_user("plan_action_token")
    token, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="plan-action-contract",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE,
    )
    executor = _install_action_run_dependencies(monkeypatch)
    client = APIClient()

    response = client.post(
        _ACTION_URL,
        {"params": {"account_id": 1}},
        format="json",
        HTTP_AUTHORIZATION=f"Token {raw_key}",
    )

    token.refresh_from_db()
    assert response.status_code == 403
    assert response.data["error_code"] == "tui_session_auth_required"
    assert token.last_used_at is not None
    assert executor.calls == []


@pytest.mark.django_db
def test_authenticated_browser_session_can_reach_plan_action_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Django login session passes the gate and reaches the existing action runner."""

    user = _create_mcp_enabled_user("plan_action_session")
    executor = _install_action_run_dependencies(monkeypatch)
    client = APIClient()
    client.force_login(user)

    response = client.post(
        _ACTION_URL,
        {"params": {"account_id": 1}},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert len(executor.calls) == 1
    assert executor.calls[0]["method"] == "GET"
    assert executor.calls[0]["endpoint"] == "/api/simulated-trading/accounts/1/rebalance-plans/"
    assert executor.calls[0]["params"] == {}
    assert executor.calls[0]["body"] == {}
    assert executor.calls[0]["user"].pk == user.pk
    assert executor.calls[0]["session"].session_key
