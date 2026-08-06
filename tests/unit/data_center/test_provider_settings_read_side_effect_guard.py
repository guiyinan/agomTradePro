"""Guard the Data Center provider-settings read path from singleton creation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_provider_settings_payload_uses_non_mutating_repository_read() -> None:
    """Provider summary reads must not call the get_or_create-backed load()."""

    source = (ROOT / "apps/data_center/application/interface_services.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "load_provider_settings_payload"
    )
    repository_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr.startswith("load")
    ]
    assert any(node.func.attr == "load_for_read" for node in repository_calls)
    assert all(node.func.attr != "load" for node in repository_calls)
