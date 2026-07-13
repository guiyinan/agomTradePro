"""Catalog replacement evidence for SDK-aligned persisted reads."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


@pytest.mark.parametrize(
    ("capability_key", "owner_app", "legacy_tool_name"),
    [
        ("equity.read.financial_history", "equity", "get_stock_financials"),
        ("fund.read.score", "fund", "get_fund_score"),
        ("sector.read.score", "sector", "get_sector_score"),
        (
            "realtime.read.sector_performance",
            "realtime",
            "get_sector_realtime_performance",
        ),
        ("strategy.read.performance", "strategy", "get_strategy_performance"),
        ("strategy.read.signals", "strategy", "get_strategy_signals"),
        ("strategy.read.positions", "strategy", "get_strategy_positions"),
        ("factor.read.portfolio", "factor", "get_factor_portfolio"),
    ],
)
def test_sdk_aligned_reads_replace_legacy_catalog_entries(
    capability_key,
    owner_app,
    legacy_tool_name,
):
    manifest = SimpleNamespace(
        capability_key=capability_key,
        summary="Canonical persisted read",
        description="Canonical persisted read contract.",
        owner_app=owner_app,
        tags=(owner_app, "read"),
        audit_tags=(),
        input_schema={"type": "object", "properties": {}},
        risk_level="low",
        requires_confirmation=False,
        idempotency="none",
        legacy_tool_names=(legacy_tool_name,),
    )
    raw_tool = SimpleNamespace(
        name=legacy_tool_name,
        description="Legacy read",
        inputSchema={},
    )

    with patch(
        "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
        return_value=[manifest],
    ), patch(
        "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
        return_value={"agom_capability_call"},
    ), patch(
        "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
        return_value=[raw_tool],
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key[f"mcp_tool.{capability_key}"]
    legacy = by_key[f"mcp_tool.{legacy_tool_name}"]
    assert governed.execution_target["replacement_for"] == [legacy_tool_name]
    assert legacy.execution_target["replacement_capability_key"] == capability_key
    assert legacy.enabled_for_terminal is False
