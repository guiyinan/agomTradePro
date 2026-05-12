"""
Unit Tests for M3: MCP Agent Proposal Tools.

Tests:
- Tool registration
- Tool execution with mocked SDK
"""

from unittest.mock import MagicMock, patch

import pytest

# Ensure MCP server has tools registered
from agomtradepro_mcp.server import server

from tests.utils.async_helpers import run_async_callable


def _get_tool_names():
    """Get all registered tool names from MCP server."""
    tools = run_async_callable(server.list_tools)
    return {t.name for t in tools}


class TestProposalToolRegistration:
    """Test that all M3 proposal tools are registered."""

    @pytest.fixture(autouse=True)
    def _tool_names(self):
        self.tool_names = _get_tool_names()

    def test_create_agent_proposal_registered(self):
        assert "create_agent_proposal" in self.tool_names

    def test_get_agent_proposal_registered(self):
        assert "get_agent_proposal" in self.tool_names

    def test_approve_agent_proposal_registered(self):
        assert "approve_agent_proposal" in self.tool_names

    def test_reject_agent_proposal_registered(self):
        assert "reject_agent_proposal" in self.tool_names

    def test_execute_agent_proposal_registered(self):
        assert "execute_agent_proposal" in self.tool_names


class TestProposalToolExecution:
    """Test proposal tool execution with mocked SDK."""

    @patch("agomtradepro_mcp.tools.agent_proposal_tools.AgomTradeProClient")
    def test_create_proposal_calls_sdk(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.agent_proposal.create_proposal.return_value = {
            "request_id": "apr_test",
            "proposal": {"id": 1, "status": "generated"},
        }

        from agomtradepro_mcp.tools.agent_proposal_tools import register_agent_proposal_tools
        from mcp.server.fastmcp import FastMCP

        test_server = FastMCP("test_m3")
        register_agent_proposal_tools(test_server)

        # Find and call the tool
        tools = run_async_callable(test_server.list_tools)
        tool_map = {t.name: t for t in tools}
        assert "create_agent_proposal" in tool_map

        # Invoke via function
        mock_instance.agent_proposal.create_proposal.assert_not_called()
        result = mock_instance.agent_proposal.create_proposal(
            proposal_type="signal_create",
            risk_level="high",
        )
        assert result["proposal"]["status"] == "generated"

    @patch("agomtradepro_mcp.tools.agent_proposal_tools.AgomTradeProClient")
    def test_approve_proposal_calls_sdk(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.agent_proposal.approve_proposal.return_value = {
            "request_id": "apr_test",
            "proposal": {"id": 1, "status": "approved"},
        }

        result = mock_instance.agent_proposal.approve_proposal(
            proposal_id=1,
            reason="Approved",
        )
        assert result["proposal"]["status"] == "approved"

    @patch("agomtradepro_mcp.tools.agent_proposal_tools.AgomTradeProClient")
    def test_reject_proposal_calls_sdk(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.agent_proposal.reject_proposal.return_value = {
            "request_id": "apr_test",
            "proposal": {"id": 1, "status": "rejected"},
        }

        result = mock_instance.agent_proposal.reject_proposal(
            proposal_id=1,
            reason="Rejected",
        )
        assert result["proposal"]["status"] == "rejected"

    @patch("agomtradepro_mcp.tools.agent_proposal_tools.AgomTradeProClient")
    def test_execute_proposal_calls_sdk(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.agent_proposal.execute_proposal.return_value = {
            "request_id": "apr_test",
            "proposal": {"id": 1, "status": "executed"},
            "execution_record_id": 42,
            "guardrail_decision": {"decision": "allowed"},
        }

        result = mock_instance.agent_proposal.execute_proposal(proposal_id=1)
        assert result["execution_record_id"] == 42
        assert result["guardrail_decision"]["decision"] == "allowed"
