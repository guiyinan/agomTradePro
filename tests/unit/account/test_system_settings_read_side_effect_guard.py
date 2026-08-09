"""Guard read-only paths against singleton SystemSettings creation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CANONICAL_ONLY_FUNCTIONS = {
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


def test_account_runtime_paths_do_not_read_the_legacy_singleton() -> None:
    """Account entrypoints must project canonical values onto an unsaved shape only."""

    for relative_path, function_names in CANONICAL_ONLY_FUNCTIONS.items():
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for function_name in function_names:
            function = functions[function_name]
            legacy_reads = [
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"get_settings", "get_settings_for_read"}
            ]
            assert (
                not legacy_reads
            ), f"{relative_path}:{function_name} must not read persisted SystemSettings"
