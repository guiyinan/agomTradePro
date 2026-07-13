"""Tests for the MCP default tool budget check script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "check_mcp_tool_budget.py"
    spec = importlib.util.spec_from_file_location("check_mcp_tool_budget", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_default_tool_budget_accepts_core_only_surface():
    module = _load_module()

    tool_names = sorted(module.CORE_TOOL_NAMES)

    module.validate_default_tool_budget(tool_names, max_tools=10)


def test_validate_default_tool_budget_rejects_unexpected_tool():
    module = _load_module()

    tool_names = sorted([*module.CORE_TOOL_NAMES, "get_current_regime"])

    with pytest.raises(ValueError, match="unexpected tools"):
        module.validate_default_tool_budget(tool_names, max_tools=10)


def test_list_default_tool_names_returns_governed_surface():
    module = _load_module()

    tool_names = module.list_default_tool_names()

    assert sorted(tool_names) == sorted(module.CORE_TOOL_NAMES)
