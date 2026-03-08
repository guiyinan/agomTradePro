"""MCP tool registration smoke tests for extended modules."""

import asyncio

import pytest


def test_extended_mcp_tools_registered():
    try:
        from agomsaaf_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}

    expected = {
        "list_ai_providers",
        "list_prompt_templates",
        "get_audit_summary",
        "publish_event",
        "submit_decision_request",
        "decision_workflow_precheck",
        "list_beta_gate_configs",
        "list_alpha_triggers",
        "get_dashboard_summary_v1",
        "asset_multidim_screen",
        "analyze_sentiment",
        "get_task_monitor_statistics",
        "list_filters",
        "list_rotation_regimes",
        "get_account_rotation_config",
        "apply_rotation_template_to_account_config",
    }

    missing = expected - names
    assert not missing, f"Missing MCP tools: {sorted(missing)}"
