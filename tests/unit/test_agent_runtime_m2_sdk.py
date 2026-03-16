"""
Unit tests for Agent Runtime M2 - SDK Modules.

WP-M2-03: Tests for runtime and context SDK module endpoint contracts.
"""

import pytest
from unittest.mock import patch, MagicMock

from agomsaaf.modules.agent_runtime import AgentRuntimeModule
from agomsaaf.modules.agent_context import AgentContextModule


class TestAgentRuntimeModule:
    """Test AgentRuntimeModule endpoint contracts."""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.get.return_value = {}
        client.post.return_value = {}
        return client

    @pytest.fixture
    def module(self, mock_client):
        return AgentRuntimeModule(mock_client)

    def test_prefix(self, module):
        assert module._prefix == "/api/agent-runtime"

    def test_create_task_calls_post(self, module, mock_client):
        module.create_task("research", "macro_review", {"focus": "regime"})
        mock_client.post.assert_called_once_with(
            "/api/agent-runtime/tasks/",
            data=None,
            json={
                "task_domain": "research",
                "task_type": "macro_review",
                "input_payload": {"focus": "regime"},
            },
        )

    def test_create_task_default_payload(self, module, mock_client):
        module.create_task("monitoring", "alert_check")
        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["input_payload"] == {}

    def test_get_task_calls_get(self, module, mock_client):
        module.get_task(42)
        mock_client.get.assert_called_once_with(
            "/api/agent-runtime/tasks/42/",
            params=None,
        )

    def test_list_tasks_default_params(self, module, mock_client):
        module.list_tasks()
        mock_client.get.assert_called_once()
        params = mock_client.get.call_args[1]["params"]
        assert params["limit"] == 50
        assert params["offset"] == 0

    def test_list_tasks_with_filters(self, module, mock_client):
        module.list_tasks(status="draft", task_domain="research", limit=10)
        params = mock_client.get.call_args[1]["params"]
        assert params["status"] == "draft"
        assert params["task_domain"] == "research"
        assert params["limit"] == 10

    def test_resume_task_calls_post(self, module, mock_client):
        module.resume_task(42, reason="Fixed")
        mock_client.post.assert_called_once()
        url = mock_client.post.call_args[0][0]
        assert "42/resume/" in url
        json_body = mock_client.post.call_args[1]["json"]
        assert json_body["reason"] == "Fixed"

    def test_cancel_task_calls_post(self, module, mock_client):
        module.cancel_task(42, "No longer needed")
        mock_client.post.assert_called_once()
        url = mock_client.post.call_args[0][0]
        assert "42/cancel/" in url
        json_body = mock_client.post.call_args[1]["json"]
        assert json_body["reason"] == "No longer needed"

    def test_get_task_timeline(self, module, mock_client):
        module.get_task_timeline(42)
        mock_client.get.assert_called_once()
        url = mock_client.get.call_args[0][0]
        assert "42/timeline/" in url

    def test_get_task_artifacts(self, module, mock_client):
        module.get_task_artifacts(42)
        mock_client.get.assert_called_once()
        url = mock_client.get.call_args[0][0]
        assert "42/artifacts/" in url

    def test_get_needs_attention(self, module, mock_client):
        module.get_needs_attention(limit=5)
        mock_client.get.assert_called_once()
        params = mock_client.get.call_args[1]["params"]
        assert params["limit"] == 5


class TestAgentContextModule:
    """Test AgentContextModule endpoint contracts."""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.get.return_value = {
            "domain": "research",
            "generated_at": "2026-03-16T12:00:00Z",
            "regime_summary": {"status": "ok"},
        }
        return client

    @pytest.fixture
    def module(self, mock_client):
        return AgentContextModule(mock_client)

    def test_prefix(self, module):
        assert module._prefix == "/api/agent-runtime/context"

    def test_get_context_snapshot(self, module, mock_client):
        result = module.get_context_snapshot("research")
        mock_client.get.assert_called_once()
        url = mock_client.get.call_args[0][0]
        assert "research/" in url

    def test_get_research_context(self, module, mock_client):
        module.get_research_context()
        url = mock_client.get.call_args[0][0]
        assert "research/" in url

    def test_get_monitoring_context(self, module, mock_client):
        module.get_monitoring_context()
        url = mock_client.get.call_args[0][0]
        assert "monitoring/" in url

    def test_get_decision_context(self, module, mock_client):
        module.get_decision_context()
        url = mock_client.get.call_args[0][0]
        assert "decision/" in url

    def test_get_execution_context(self, module, mock_client):
        module.get_execution_context()
        url = mock_client.get.call_args[0][0]
        assert "execution/" in url

    def test_get_ops_context(self, module, mock_client):
        module.get_ops_context()
        url = mock_client.get.call_args[0][0]
        assert "ops/" in url
