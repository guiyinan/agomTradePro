"""Tests for bounded Agent discovery over published TUI operations."""

from __future__ import annotations

import pytest
from django.urls import reverse

from agomtradepro_mcp.registry.runtime_handlers.owners import terminal as terminal_handlers
from apps.terminal.application.tui_workbench import TuiWorkbenchService


class _MetadataRepository:
    """Return a minimal published operation graph."""

    def load_published(self, registry_key: str = "default"):
        return {
            "version": "tui-workbench.v2",
            "registry_key": registry_key,
            "default_screen": "execution.positions",
            "groups": [],
            "modules": [],
            "screens": [],
            "actions": [
                {
                    "key": "account.positions",
                    "label": "查看持仓",
                    "description": "查看当前投资组合持仓",
                    "intent": "read_account_positions",
                    "screen_key": "execution.positions",
                    "module_key": "execution",
                    "view_type": "datagrid",
                    "risk": "read",
                    "method": "GET",
                    "endpoint": "/api/account/positions/",
                    "fields": [{"key": "portfolio_id", "required": False}],
                },
                {
                    "key": "account.position.create",
                    "label": "新增持仓",
                    "description": "新增一个投资组合持仓",
                    "intent": "create_account_position",
                    "screen_key": "execution.positions",
                    "module_key": "execution",
                    "view_type": "detail",
                    "risk": "write",
                    "method": "POST",
                    "endpoint": "/api/account/positions/",
                    "fields": [{"key": "asset_code", "required": True}],
                },
            ],
        }


def test_search_agent_actions_is_bounded_and_returns_compact_schemas():
    service = TuiWorkbenchService(metadata_repository=_MetadataRepository())

    result = service.search_agent_actions(query="持仓", limit=100, user=None)

    assert result["returned_count"] == 2
    assert result["limit"] == 20
    assert result["actions"][0]["action_key"]
    assert "endpoint" not in result["actions"][0]


def test_get_agent_action_schema_returns_governed_execution_metadata():
    service = TuiWorkbenchService(metadata_repository=_MetadataRepository())

    result = service.get_agent_action_schema("account.position.create", user=None)

    assert result["action_key"] == "account.position.create"
    assert result["risk"] == "write"
    assert result["requires_confirmation"] is True
    assert result["fields"][0]["key"] == "asset_code"


@pytest.mark.django_db
def test_agent_action_search_and_schema_api_require_authenticated_user(
    client,
    django_user_model,
):
    search_url = reverse("api_terminal:tui-agent-action-search")
    anonymous = client.get(search_url, {"query": "持仓", "limit": 3})
    assert anonymous.status_code in {401, 403}

    user = django_user_model.objects.create_user(username="tui-agent", password="secret")
    client.force_login(user)
    response = client.get(search_url, {"query": "持仓", "limit": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["returned_count"] <= 3
    if payload["actions"]:
        schema_url = reverse(
            "api_terminal:tui-agent-action-schema",
            kwargs={"action_key": payload["actions"][0]["action_key"]},
        )
        schema_response = client.get(schema_url)
        assert schema_response.status_code == 200
        assert schema_response.json()["action_key"] == payload["actions"][0]["action_key"]


@pytest.mark.django_db
def test_mcp_bridge_blocks_real_published_read_action_without_evidence_binding(
    client,
    django_user_model,
    monkeypatch,
):
    """Exercise MCP handler -> Terminal schema -> audited TUI action runtime."""

    user = django_user_model.objects.create_user(username="mcp-tui", password="secret")
    client.force_login(user)

    class DjangoClientAdapter:
        def get(self, endpoint, params=None):
            response = client.get(f"/{endpoint.lstrip('/')}", params or {})
            assert response.status_code == 200
            return response.json()

        def post(self, endpoint, json=None):
            response = client.post(
                f"/{endpoint.lstrip('/')}",
                data=json or {},
                content_type="application/json",
            )
            assert response.status_code == 200
            return response.json()

    monkeypatch.setattr(terminal_handlers, "_client", lambda: DjangoClientAdapter())

    with pytest.raises(PermissionError, match="mcp_evidence_binding_required"):
        terminal_handlers._internal_handler_terminal_run_user_read_action(
            "system.health-summary",
            {},
        )
