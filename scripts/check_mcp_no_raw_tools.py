#!/usr/bin/env python
"""Freeze the allowed raw @server.tool() file surface during MCP consolidation."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = REPO_ROOT / "sdk" / "agomtradepro_mcp"
TOOLS_ROOT = MCP_ROOT / "tools"
RAW_TOOL_DECORATOR_RE = re.compile(r"@server\.tool\(\)")

FROZEN_ALLOWED_RAW_TOOL_FILES = frozenset(
    {
        "sdk/agomtradepro_mcp/tools/account_tools.py",
        "sdk/agomtradepro_mcp/tools/agent_proposal_tools.py",
        "sdk/agomtradepro_mcp/tools/agent_runtime_tools.py",
        "sdk/agomtradepro_mcp/tools/agent_task_tools.py",
        "sdk/agomtradepro_mcp/tools/ai_provider_tools.py",
        "sdk/agomtradepro_mcp/tools/alpha_tools.py",
        "sdk/agomtradepro_mcp/tools/alpha_trigger_tools.py",
        "sdk/agomtradepro_mcp/tools/asset_analysis_tools.py",
        "sdk/agomtradepro_mcp/tools/audit_tools.py",
        "sdk/agomtradepro_mcp/tools/backtest_tools.py",
        "sdk/agomtradepro_mcp/tools/beta_gate_tools.py",
        "sdk/agomtradepro_mcp/tools/config_center_tools.py",
        "sdk/agomtradepro_mcp/tools/core_tools.py",
        "sdk/agomtradepro_mcp/tools/dashboard_tools.py",
        "sdk/agomtradepro_mcp/tools/data_center_tools.py",
        "sdk/agomtradepro_mcp/tools/decision_rhythm_tools.py",
        "sdk/agomtradepro_mcp/tools/decision_workflow_tools.py",
        "sdk/agomtradepro_mcp/tools/equity_tools.py",
        "sdk/agomtradepro_mcp/tools/events_tools.py",
        "sdk/agomtradepro_mcp/tools/factor_tools.py",
        "sdk/agomtradepro_mcp/tools/filter_tools.py",
        "sdk/agomtradepro_mcp/tools/fund_tools.py",
        "sdk/agomtradepro_mcp/tools/hedge_tools.py",
        "sdk/agomtradepro_mcp/tools/policy_tools.py",
        "sdk/agomtradepro_mcp/tools/prompt_tools.py",
        "sdk/agomtradepro_mcp/tools/pulse_tools.py",
        "sdk/agomtradepro_mcp/tools/realtime_tools.py",
        "sdk/agomtradepro_mcp/tools/regime_tools.py",
        "sdk/agomtradepro_mcp/tools/risk_center_tools.py",
        "sdk/agomtradepro_mcp/tools/rotation_tools.py",
        "sdk/agomtradepro_mcp/tools/sector_tools.py",
        "sdk/agomtradepro_mcp/tools/sentiment_tools.py",
        "sdk/agomtradepro_mcp/tools/signal_tools.py",
        "sdk/agomtradepro_mcp/tools/simulated_trading_tools.py",
        "sdk/agomtradepro_mcp/tools/strategy_tools.py",
        "sdk/agomtradepro_mcp/tools/task_monitor_tools.py",
    }
)


def discover_raw_tool_files(search_root: Path | None = None) -> set[str]:
    """Return repo-relative files that currently define raw @server.tool decorators."""
    root = search_root or MCP_ROOT
    discovered: set[str] = set()
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if RAW_TOOL_DECORATOR_RE.search(text):
            discovered.add(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    return discovered


def validate_raw_tool_surface(
    discovered_files: set[str],
    *,
    allowed_files: set[str] | frozenset[str] = FROZEN_ALLOWED_RAW_TOOL_FILES,
) -> None:
    """Reject newly introduced raw tool files during consolidation."""
    unexpected = sorted(discovered_files - set(allowed_files))
    if unexpected:
        raise ValueError(
            "Unexpected raw @server.tool() files detected: "
            f"{unexpected}"
        )

    misplaced = sorted(
        path
        for path in discovered_files
        if not path.startswith("sdk/agomtradepro_mcp/tools/")
    )
    if misplaced:
        raise ValueError(
            "Raw @server.tool() decorators are only allowed under sdk/agomtradepro_mcp/tools/: "
            f"{misplaced}"
        )


def main() -> int:
    """CLI entrypoint for raw tool surface validation."""
    parser = argparse.ArgumentParser(
        description="Validate that the raw @server.tool() file surface has not expanded.",
    )
    parser.parse_args()

    discovered = discover_raw_tool_files()
    validate_raw_tool_surface(discovered)
    print(f"Raw MCP tool file surface OK: {len(discovered)} files")
    for path in sorted(discovered):
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
