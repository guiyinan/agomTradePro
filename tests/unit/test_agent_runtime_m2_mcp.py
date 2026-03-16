"""
Unit tests for Agent Runtime M2 - MCP Tools, Resources, and Prompts.

WP-M2-04/05/06: Tests for tool/resource/prompt registration and execution.
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock


class TestAgentTaskToolRegistration:
    """Test that agent task tools are registered in the MCP server."""

    @pytest.fixture
    def tool_names(self):
        """Get all registered tool names from MCP server."""
        from agomsaaf_mcp.server import server
        tools = asyncio.get_event_loop().run_until_complete(server.list_tools())
        return [t.name for t in tools]

    def test_start_research_task_registered(self, tool_names):
        assert "start_research_task" in tool_names

    def test_start_monitoring_task_registered(self, tool_names):
        assert "start_monitoring_task" in tool_names

    def test_start_decision_task_registered(self, tool_names):
        assert "start_decision_task" in tool_names

    def test_start_execution_task_registered(self, tool_names):
        assert "start_execution_task" in tool_names

    def test_start_ops_task_registered(self, tool_names):
        assert "start_ops_task" in tool_names

    def test_resume_agent_task_registered(self, tool_names):
        assert "resume_agent_task" in tool_names

    def test_cancel_agent_task_registered(self, tool_names):
        assert "cancel_agent_task" in tool_names


class TestContextResourceRegistration:
    """Test that context resources are registered."""

    @pytest.fixture
    def resource_uris(self):
        """Get all registered resource URIs."""
        from agomsaaf_mcp.server import server
        resources = asyncio.get_event_loop().run_until_complete(server.list_resources())
        return [str(r.uri) for r in resources]

    def test_research_context_resource(self, resource_uris):
        assert "agomsaaf://context/research/current" in resource_uris

    def test_monitoring_context_resource(self, resource_uris):
        assert "agomsaaf://context/monitoring/current" in resource_uris

    def test_decision_context_resource(self, resource_uris):
        assert "agomsaaf://context/decision/current" in resource_uris

    def test_execution_context_resource(self, resource_uris):
        assert "agomsaaf://context/execution/current" in resource_uris

    def test_ops_context_resource(self, resource_uris):
        assert "agomsaaf://context/ops/current" in resource_uris


class TestWorkflowPromptRegistration:
    """Test that workflow guide prompts are registered."""

    @pytest.fixture
    def prompt_names(self):
        """Get all registered prompt names."""
        from agomsaaf_mcp.server import server
        prompts = asyncio.get_event_loop().run_until_complete(server.list_prompts())
        return [p.name for p in prompts]

    def test_research_workflow_prompt(self, prompt_names):
        assert "run_research_workflow" in prompt_names

    def test_monitoring_workflow_prompt(self, prompt_names):
        assert "run_monitoring_workflow" in prompt_names

    def test_decision_workflow_prompt(self, prompt_names):
        assert "run_decision_workflow" in prompt_names

    def test_execution_workflow_prompt(self, prompt_names):
        assert "run_execution_workflow" in prompt_names

    def test_ops_workflow_prompt(self, prompt_names):
        assert "run_ops_workflow" in prompt_names


class TestAgentTaskToolExecution:
    """Test agent task tool execution with mocked SDK."""

    @patch("agomsaaf_mcp.tools.agent_task_tools.AgomSAAFClient")
    def test_start_research_task_creates_task(self, mock_client_cls):
        """start_research_task calls create_task and fetches context."""
        mock_client = MagicMock()
        mock_client.agent_runtime.create_task.return_value = {
            "request_id": "atr_20260316_ABC123",
            "task": {"id": 1, "task_domain": "research", "status": "draft"},
        }
        mock_client.agent_context.get_context_snapshot.return_value = {
            "domain": "research",
            "generated_at": "2026-03-16T12:00:00Z",
            "regime_summary": {"status": "ok", "dominant_regime": "Recovery"},
            "policy_summary": {"status": "ok"},
        }
        mock_client_cls.return_value = mock_client

        from agomsaaf_mcp.tools.agent_task_tools import register_agent_task_tools
        from mcp.server.fastmcp import FastMCP

        test_server = FastMCP("test")
        register_agent_task_tools(test_server)

        # Find and call the tool function
        tools = test_server._tool_manager._tools
        tool_fn = tools["start_research_task"].fn
        result = tool_fn(task_type="macro_review", input_payload={"focus": "regime"})

        mock_client.agent_runtime.create_task.assert_called_once_with(
            task_domain="research",
            task_type="macro_review",
            input_payload={"focus": "regime"},
        )
        assert "context_snapshot" in result
        assert result["context_snapshot"]["domain"] == "research"

    @patch("agomsaaf_mcp.tools.agent_task_tools.AgomSAAFClient")
    def test_start_task_context_unavailable_degrades(self, mock_client_cls):
        """Task is still created even when context fetch fails."""
        mock_client = MagicMock()
        mock_client.agent_runtime.create_task.return_value = {
            "request_id": "atr_20260316_ABC123",
            "task": {"id": 1, "task_domain": "ops", "status": "draft"},
        }
        mock_client.agent_context.get_context_snapshot.side_effect = Exception("timeout")
        mock_client_cls.return_value = mock_client

        from agomsaaf_mcp.tools.agent_task_tools import register_agent_task_tools
        from mcp.server.fastmcp import FastMCP

        test_server = FastMCP("test")
        register_agent_task_tools(test_server)

        tool_fn = test_server._tool_manager._tools["start_ops_task"].fn
        result = tool_fn()

        assert result["context_snapshot"]["status"] == "unavailable"
        # Task was still created
        mock_client.agent_runtime.create_task.assert_called_once()

    @patch("agomsaaf_mcp.tools.agent_task_tools.AgomSAAFClient")
    def test_resume_agent_task(self, mock_client_cls):
        """resume_agent_task calls resume on SDK."""
        mock_client = MagicMock()
        mock_client.agent_runtime.resume_task.return_value = {
            "request_id": "atr_20260316_ABC123",
            "task": {"id": 42, "status": "draft"},
        }
        mock_client_cls.return_value = mock_client

        from agomsaaf_mcp.tools.agent_task_tools import register_agent_task_tools
        from mcp.server.fastmcp import FastMCP

        test_server = FastMCP("test")
        register_agent_task_tools(test_server)

        tool_fn = test_server._tool_manager._tools["resume_agent_task"].fn
        result = tool_fn(task_id=42, reason="Fixed data issue")

        mock_client.agent_runtime.resume_task.assert_called_once_with(
            task_id=42,
            target_status=None,
            reason="Fixed data issue",
        )

    @patch("agomsaaf_mcp.tools.agent_task_tools.AgomSAAFClient")
    def test_cancel_agent_task(self, mock_client_cls):
        """cancel_agent_task calls cancel on SDK."""
        mock_client = MagicMock()
        mock_client.agent_runtime.cancel_task.return_value = {
            "request_id": "atr_20260316_ABC123",
            "task": {"id": 42, "status": "cancelled"},
        }
        mock_client_cls.return_value = mock_client

        from agomsaaf_mcp.tools.agent_task_tools import register_agent_task_tools
        from mcp.server.fastmcp import FastMCP

        test_server = FastMCP("test")
        register_agent_task_tools(test_server)

        tool_fn = test_server._tool_manager._tools["cancel_agent_task"].fn
        result = tool_fn(task_id=42, reason="No longer needed")

        mock_client.agent_runtime.cancel_task.assert_called_once_with(
            task_id=42,
            reason="No longer needed",
        )
