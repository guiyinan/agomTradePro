"""MCP tool registration smoke tests for extended modules."""

import asyncio

import pytest


def test_extended_mcp_tools_registered():
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}

    expected = {
        "list_accounts",
        "get_account",
        "create_account",
        "get_account_positions",
        "get_account_performance",
        "delete_simulated_account",
        "batch_delete_simulated_accounts",
        "list_ai_providers",
        "list_prompt_templates",
        "get_audit_summary",
        "publish_event",
        "submit_decision_request",
        "decision_workflow_precheck",
        "decision_workflow_get_funnel_context",
        "list_beta_gate_configs",
        "list_alpha_triggers",
        "get_dashboard_summary_v1",
        "get_dashboard_alpha_decision_chain_v1",
        "asset_multidim_screen",
        "analyze_sentiment",
        "get_task_monitor_statistics",
        "list_filters",
        "list_rotation_regimes",
        "get_account_rotation_config",
        "apply_rotation_template_to_account_config",
        "get_alpha_stock_scores",
        "upload_alpha_scores",
        "get_pulse_current",
        "get_pulse_history",
        "get_regime_navigator",
        "get_action_recommendation",
        "explain_pulse_dimensions",
        "list_data_center_providers",
        "test_data_center_provider_connection",
        "get_data_center_provider_status",
        "data_center_get_quotes",
        "data_center_get_capital_flows",
    }

    missing = expected - names
    assert not missing, f"Missing MCP tools: {sorted(missing)}"
