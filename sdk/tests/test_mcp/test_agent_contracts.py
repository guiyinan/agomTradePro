"""Contracts for versioned MCP agent guidance and workflow playbooks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agomtradepro_mcp.agent_contracts import AgentContractStore


def test_agent_contract_is_versioned_auditable_and_excludes_hidden_chain_of_thought():
    contract = AgentContractStore().get_contract()

    assert contract["contract_id"] == "agomtradepro.agent-operating-contract"
    assert contract["version"]
    assert contract["status"] == "active"
    assert len(contract["content_sha256"]) == 64
    assert "decision_summary" in contract["structured_reasoning"]
    assert contract["structured_reasoning"]["expose_hidden_chain_of_thought"] is False
    assert "capability_key" in contract["structured_reasoning"]["decision_summary"]["required"]


def test_playbooks_are_loaded_from_versioned_configuration():
    store = AgentContractStore()

    catalog = store.list_playbooks()
    fund = store.get_playbook("fund_recommendation")

    assert catalog["version"]
    assert {item["playbook_key"] for item in catalog["playbooks"]} >= {
        "fund_recommendation",
        "account_aware_fund_recommendation",
        "signal_review",
        "execution",
    }
    assert fund["playbook_key"] == "fund_recommendation"
    assert fund["steps"]
    assert fund["human_approval_policy"] == "server_enforced"


def test_prompt_text_is_rendered_from_external_configuration():
    config_path = Path(__file__).resolve().parents[1] / "fixtures" / "agent_contract_override.json"

    rendered = AgentContractStore(config_path).render_prompt(
        "test_prompt",
        {"focus": "not-hardcoded"},
    )

    assert rendered == "Configured focus: not-hardcoded"


def test_core_tools_expose_agent_contract_and_playbooks(core_only_mcp_server):
    contract_result = asyncio.run(
        core_only_mcp_server.call_tool("agom_get_agent_contract", {"task_type": "research"})
    )[1]
    playbook_result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_get_workflow_playbook",
            {"playbook_key": "fund_recommendation"},
        )
    )[1]

    assert contract_result["ok"] is True
    assert contract_result["contract"]["version"]
    assert contract_result["requested_task_type"] == "research"
    assert playbook_result["ok"] is True
    assert playbook_result["playbook"]["playbook_key"] == "fund_recommendation"


def test_unknown_playbook_returns_stable_error(core_only_mcp_server):
    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_get_workflow_playbook",
            {"playbook_key": "missing"},
        )
    )[1]

    assert result == {
        "ok": False,
        "status": "error",
        "error": {
            "code": "playbook_not_found",
            "message": "Unknown playbook_key: missing",
        },
        "playbook_key": "missing",
    }


def test_agent_contract_resources_and_prompt_are_registered():
    from agomtradepro_mcp.server import get_prompt, list_resources, read_resource

    resources = asyncio.run(list_resources())
    uris = {item["uri"] for item in resources}
    assert "agomtradepro://agent/contract" in uris
    assert "agomtradepro://agent/playbooks" in uris

    contract = json.loads(asyncio.run(read_resource("agomtradepro://agent/contract")))
    prompt = asyncio.run(get_prompt("agom_agent_contract", {"task_type": "research"}))

    assert contract["contract_id"] == "agomtradepro.agent-operating-contract"
    assert "decision_summary" in prompt
    assert "hidden chain-of-thought" in prompt
