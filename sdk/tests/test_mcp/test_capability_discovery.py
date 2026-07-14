"""Focused tests for the token-bounded MCP capability discovery surface."""

from __future__ import annotations

import asyncio

from agomtradepro_mcp.registry.dispatcher import (
    CAPABILITY_SEARCH_MAX_RESULTS,
    CapabilityDispatcher,
)
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def _build_dispatcher() -> CapabilityDispatcher:
    """Build a read-only dispatcher for discovery tests."""

    return CapabilityDispatcher(
        registry=CapabilityRegistryLoader().build_registry(),
        legacy_tool_caller=lambda _name, _arguments: None,
    )


def test_search_expands_chinese_portfolio_query() -> None:
    dispatcher = _build_dispatcher()

    matches = dispatcher.search(query="查看当前持仓", limit=10)

    keys = {match["capability_key"] for match in matches}
    assert "account.read.account_positions" in keys


def test_search_expands_chinese_macro_query() -> None:
    dispatcher = _build_dispatcher()

    matches = dispatcher.search(query="宏观象限", limit=10)

    keys = {match["capability_key"] for match in matches}
    assert "system.read.regime.current" in keys


def test_search_clamps_result_limit_and_keeps_discovery_payload_compact() -> None:
    dispatcher = _build_dispatcher()

    matches = dispatcher.search(query="", limit=10_000)

    assert len(matches) == CAPABILITY_SEARCH_MAX_RESULTS
    assert all("legacy_tool_names" not in match for match in matches)
    assert all("audit_tags" not in match for match in matches)
    assert all("idempotency_argument_name" not in match for match in matches)


def test_full_schema_keeps_governance_metadata() -> None:
    dispatcher = _build_dispatcher()

    schema = dispatcher.get_schema("system.read.regime.current")

    assert "legacy_tool_names" in schema
    assert "audit_tags" in schema
    assert "idempotency_argument_name" in schema


def test_core_search_reports_effective_bounded_limit(core_only_mcp_server) -> None:
    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_search",
            {"query": "", "limit": 10_000},
        )
    )

    structured = result[1]
    assert structured["limit"] == CAPABILITY_SEARCH_MAX_RESULTS
    assert structured["returned_count"] == CAPABILITY_SEARCH_MAX_RESULTS


def test_bootstrap_returns_domain_index_instead_of_capability_samples(
    core_only_mcp_server,
) -> None:
    result = asyncio.run(core_only_mcp_server.call_tool("agom_bootstrap", {}))

    structured = result[1]
    assert structured["capability_domains"]
    assert structured["discovery"]["search_max_limit"] == CAPABILITY_SEARCH_MAX_RESULTS
    assert "capabilities" not in structured


def test_initialize_instructions_keep_context_reads_on_demand() -> None:
    from agomtradepro_mcp.server import _build_welcome_message

    instructions = _build_welcome_message()

    assert "Do not preload resources or the capability catalog" in instructions
    assert "Only for investment research" in instructions
    assert "terminal.search.user_actions" in instructions
    assert (
        "Read agomtradepro://regime/current and agomtradepro://policy/status first"
        not in instructions
    )
