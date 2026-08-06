"""Guard read-only paths against singleton SystemSettings creation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
READ_ONLY_FUNCTIONS = {
    "core/encryption_readiness.py": ("collect_encryption_readiness",),
    "apps/account/infrastructure/backup_service.py": ("build_backup_download_url",),
    "apps/account/infrastructure/account_interface_administration_repository.py": (
        "build_user_management_context",
        "build_token_management_context",
        "toggle_user_mcp",
        "build_system_settings_context",
    ),
    "apps/account/infrastructure/account_interface_registration_repository.py": (
        "get_system_settings",
        "build_settings_context",
        "build_mcp_guide_context",
    ),
}


def test_read_only_settings_paths_use_non_mutating_singleton_read() -> None:
    """Read-only paths must not call get_or_create-backed get_settings()."""

    for relative_path, function_names in READ_ONLY_FUNCTIONS.items():
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for function_name in function_names:
            function = functions[function_name]
            calls = [
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("get_settings")
            ]
            assert any(
                call.func.attr == "get_settings_for_read" for call in calls
            ), f"{relative_path}:{function_name} must use get_settings_for_read()"
            assert all(
                call.func.attr != "get_settings" for call in calls
            ), f"{relative_path}:{function_name} must not create SystemSettings"
