"""
Unit Tests for M3: SDK Agent Proposal Module.

Tests:
- Endpoint contract validation
- Method parameter mapping
- Structured failure handling
"""

import pytest
from unittest.mock import MagicMock, patch

from sdk.agomsaaf.modules.agent_proposal import AgentProposalModule


class TestAgentProposalModule:
    """Test SDK AgentProposalModule endpoint contracts."""

    def setup_method(self):
        self.mock_client = MagicMock()
        self.mock_client.get.return_value = {"ok": True}
        self.mock_client.post.return_value = {"ok": True}
        self.module = AgentProposalModule(self.mock_client)

    def test_prefix(self):
        assert self.module._prefix == "/api/agent-runtime"

    def test_create_proposal_calls_post(self):
        self.module.create_proposal(
            proposal_type="signal_create",
            risk_level="high",
            proposal_payload={"asset": "000001.SH"},
        )
        self.mock_client.post.assert_called_once()
        url = self.mock_client.post.call_args[0][0]
        assert "proposals/" in url

    def test_create_proposal_includes_all_fields(self):
        self.module.create_proposal(
            proposal_type="trade_execute",
            task_id=42,
            risk_level="medium",
            approval_required=True,
            proposal_payload={"qty": 100},
            approval_reason="Test reason",
        )
        call_kwargs = self.mock_client.post.call_args
        body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert body["proposal_type"] == "trade_execute"
        assert body["task_id"] == 42
        assert body["risk_level"] == "medium"
        assert body["approval_required"] is True
        assert body["proposal_payload"]["qty"] == 100
        assert body["approval_reason"] == "Test reason"

    def test_create_proposal_default_payload(self):
        self.module.create_proposal(proposal_type="config_write")
        call_kwargs = self.mock_client.post.call_args
        body = call_kwargs[1]["json"]
        assert body["proposal_payload"] == {}
        assert body["risk_level"] == "medium"
        assert body["approval_required"] is True
        assert "task_id" not in body

    def test_get_proposal_calls_get(self):
        self.module.get_proposal(99)
        self.mock_client.get.assert_called_once()
        url = self.mock_client.get.call_args[0][0]
        assert "proposals/99/" in url

    def test_submit_for_approval_calls_post(self):
        self.module.submit_proposal_for_approval(42)
        self.mock_client.post.assert_called_once()
        url = self.mock_client.post.call_args[0][0]
        assert "proposals/42/submit-approval/" in url

    def test_approve_proposal_calls_post(self):
        self.module.approve_proposal(42, reason="Looks good")
        self.mock_client.post.assert_called_once()
        url = self.mock_client.post.call_args[0][0]
        assert "proposals/42/approve/" in url
        body = self.mock_client.post.call_args[1]["json"]
        assert body["reason"] == "Looks good"

    def test_approve_proposal_no_reason(self):
        self.module.approve_proposal(42)
        body = self.mock_client.post.call_args[1]["json"]
        assert "reason" not in body

    def test_reject_proposal_calls_post(self):
        self.module.reject_proposal(42, reason="Too risky")
        self.mock_client.post.assert_called_once()
        url = self.mock_client.post.call_args[0][0]
        assert "proposals/42/reject/" in url

    def test_reject_proposal_no_reason(self):
        self.module.reject_proposal(42)
        body = self.mock_client.post.call_args[1]["json"]
        assert "reason" not in body

    def test_execute_proposal_calls_post(self):
        self.module.execute_proposal(42)
        self.mock_client.post.assert_called_once()
        url = self.mock_client.post.call_args[0][0]
        assert "proposals/42/execute/" in url
