"""Guard the Data Center provider-settings read path from singleton creation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_provider_settings_payload_has_no_legacy_repository_read() -> None:
    """Provider runtime reads must use only the active typed snapshot."""

    source = (ROOT / "apps/data_center/application/interface_services.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "load_provider_settings_payload"
    )
    runtime_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "get_active_runtime_value"
    ]
    assert len(runtime_calls) == 3
    assert "DataProviderSettingsRepository" not in source
    assert "DataProviderSettingsModel" not in source
