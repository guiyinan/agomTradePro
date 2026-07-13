"""Tests for the frozen raw MCP tool surface check script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "check_mcp_no_raw_tools.py"
    spec = importlib.util.spec_from_file_location("check_mcp_no_raw_tools", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_raw_tool_surface_accepts_frozen_current_surface():
    module = _load_module()

    module.validate_raw_tool_surface(set(module.FROZEN_ALLOWED_RAW_TOOL_FILES))


def test_validate_raw_tool_surface_rejects_unexpected_raw_tool_file():
    module = _load_module()

    discovered = set(module.FROZEN_ALLOWED_RAW_TOOL_FILES)
    discovered.add("sdk/agomtradepro_mcp/tools/new_legacy_tools.py")

    with pytest.raises(ValueError, match="Unexpected raw @server.tool"):
        module.validate_raw_tool_surface(discovered)


def test_validate_raw_tool_surface_rejects_raw_tool_outside_tools_dir():
    module = _load_module()

    discovered = {"sdk/agomtradepro_mcp/server.py"}

    with pytest.raises(ValueError, match="only allowed under sdk/agomtradepro_mcp/tools/"):
        module.validate_raw_tool_surface(discovered, allowed_files={"sdk/agomtradepro_mcp/server.py"})


def test_discover_raw_tool_files_matches_frozen_surface():
    module = _load_module()

    discovered = module.discover_raw_tool_files()

    assert discovered == set(module.FROZEN_ALLOWED_RAW_TOOL_FILES)
