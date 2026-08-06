"""Guard Qlib Admin diagnostics against legacy default-path fallback."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_qlib_admin_validation_does_not_reheat_default_provider_path() -> None:
    """Admin model validation must remain blocked when runtime config is unavailable."""

    source = (ROOT / "apps/alpha/admin.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run_validation"
    )
    function_source = ast.get_source_segment(source, function) or ""
    assert "~/.qlib/qlib_data/cn_data" not in function_source
    assert "_qlib_settings_mapping" not in function_source
