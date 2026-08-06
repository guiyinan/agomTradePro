"""Guard Qlib Admin diagnostics against legacy default-path fallback."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from django.contrib.admin.sites import AdminSite

from apps.alpha import admin as alpha_admin

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


def test_qlib_admin_model_root_blocks_without_typed_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifact storage must not reheat QLIB_SETTINGS when the typed runtime is blocked."""

    monkeypatch.setattr(
        "core.integration.runtime_settings.get_runtime_qlib_config",
        lambda: {
            "status": "blocked",
            "must_not_use_for_decision": True,
        },
    )
    admin_instance = alpha_admin.QlibModelRegistryAdmin(
        alpha_admin.QlibModelRegistryModel,
        AdminSite(),
    )

    with pytest.raises(RuntimeError, match="runtime_config_snapshot_unavailable"):
        admin_instance._model_root()
