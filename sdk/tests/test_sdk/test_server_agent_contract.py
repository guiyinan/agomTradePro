"""Contract tests for the server-side Agent API boundary."""

from __future__ import annotations

from unittest.mock import patch

from agomtradepro import AgomTradeProClient


def test_agent_execution_uses_server_route_without_provider_secrets() -> None:
    """The SDK sends a user request to the server, never a provider key."""

    client = AgomTradeProClient(base_url="https://example.test", api_token="scoped-token")
    with patch.object(client, "_request", return_value={"success": True}) as request:
        client.prompt.agent_execute(
            task_type="chat",
            user_input="列出当前需要确认的任务",
            provider_ref="server-provider-1",
            model="server-model-1",
            context_scope=["tasks"],
        )

    args, kwargs = request.call_args
    assert args == ("POST", "/api/prompt/agent/execute")
    payload = kwargs["json"]
    assert payload["task_type"] == "chat"
    assert payload["user_input"] == "列出当前需要确认的任务"
    assert payload["provider_ref"] == "server-provider-1"
    assert "provider_api_key" not in payload
    assert "api_key" not in payload
    assert "secret" not in payload
    assert "token" not in payload
