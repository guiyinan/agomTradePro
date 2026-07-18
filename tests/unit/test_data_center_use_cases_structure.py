"""Structure contracts for split data-center application use cases."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from apps.data_center.application import use_cases

REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_MODULE = "apps.data_center.application.use_cases"
OWNER_MODULES = (
    "apps.data_center.application.provider_catalog_use_cases",
    "apps.data_center.application.query_use_cases",
    "apps.data_center.application.reliability_use_cases",
    "apps.data_center.application.fact_query_use_cases",
    "apps.data_center.application.macro_governance_use_cases",
    "apps.data_center.application.sync_use_cases",
)


def _imports_module(source: str, module_name: str) -> bool:
    """Return whether source imports one exact module."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == module_name:
            return True
    return False


def test_data_center_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep moved symbols available from the established module path."""
    owner_exports: set[str] = set()
    for module_name in OWNER_MODULES:
        owner_module = import_module(module_name)
        exports = set(owner_module.__all__)
        owner_exports.update(exports)
        for export_name in exports:
            assert getattr(use_cases, export_name) is getattr(owner_module, export_name)

    assert owner_exports <= set(use_cases.__all__)
    assert "DEFAULT_DECISION_ASSET_CODES" in use_cases.__all__
    assert "DEFAULT_DECISION_MACRO_INDICATORS" in use_cases.__all__


def test_data_center_use_case_modules_stay_bounded_and_one_way() -> None:
    """Prevent owner modules from regrowing or importing the aggregator."""
    budgets = {
        AGGREGATOR_MODULE: 180,
        "apps.data_center.application.provider_catalog_use_cases": 450,
        "apps.data_center.application.query_use_cases": 600,
        "apps.data_center.application.reliability_use_cases": 650,
        "apps.data_center.application.fact_query_use_cases": 180,
        "apps.data_center.application.macro_governance_use_cases": 220,
        "apps.data_center.application.sync_use_cases": 800,
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
