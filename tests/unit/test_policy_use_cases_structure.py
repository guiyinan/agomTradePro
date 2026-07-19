"""Structure contracts for split policy application use cases."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from apps.policy.application import use_cases

REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_MODULE = "apps.policy.application.use_cases"
OWNER_MODULES = (
    "apps.policy.application.event_use_cases",
    "apps.policy.application.rss_fetch_use_cases",
    "apps.policy.application.audit_use_cases",
    "apps.policy.application.workbench_use_cases",
)


def _imports_module(source: str, module_name: str) -> bool:
    """Return whether source imports one exact module (absolute or in-package)."""
    leaf_name = module_name.rsplit(".", 1)[-1]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == module_name:
                return True
            if node.level:
                if node.module == leaf_name:
                    return True
                if node.module is None and any(
                    alias.name == leaf_name for alias in node.names
                ):
                    return True
    return False


def test_policy_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep moved symbols available from the established module path."""
    owner_exports: set[str] = set()
    for module_name in OWNER_MODULES:
        owner_module = import_module(module_name)
        exports = set(owner_module.__all__)
        owner_exports.update(exports)
        for export_name in exports:
            assert getattr(use_cases, export_name) is getattr(owner_module, export_name)

    assert owner_exports == set(use_cases.__all__)
    assert "RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS" in use_cases.__all__
    assert "FetchRSSUseCase" in use_cases.__all__


def test_policy_use_case_modules_stay_bounded_and_one_way() -> None:
    """Prevent owner modules from regrowing or importing the aggregator."""
    budgets = {
        AGGREGATOR_MODULE: 150,
        "apps.policy.application.event_use_cases": 800,
        "apps.policy.application.rss_fetch_use_cases": 800,
        "apps.policy.application.audit_use_cases": 300,
        "apps.policy.application.workbench_use_cases": 600,
    }
    for module_name, budget in budgets.items():
        relative_path = Path(*module_name.split(".")).with_suffix(".py")
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())
        assert (
            non_empty_lines <= budget
        ), f"{relative_path} has {non_empty_lines} non-empty lines; budget is {budget}"
        if module_name != AGGREGATOR_MODULE:
            assert not _imports_module(
                source, AGGREGATOR_MODULE
            ), f"{relative_path} must not import the compatibility aggregator"
