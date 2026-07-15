"""Structure contracts for the split auto-advisor application services."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from apps.decision_rhythm.application import advisor_services

REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_MODULE = "apps.decision_rhythm.application.advisor_services"
OWNER_MODULES = (
    "apps.decision_rhythm.application.advisor_serialization",
    "apps.decision_rhythm.application.advisor_contracts",
    "apps.decision_rhythm.application.advisor_intents",
    "apps.decision_rhythm.application.advisor_execution",
    "apps.decision_rhythm.application.advisor_performance",
    "apps.decision_rhythm.application.advisor_providers",
    "apps.decision_rhythm.application.advisor_sheet",
)
INTERNAL_MODULES = (
    "apps.decision_rhythm.application.advisor_sheet_context",
    "apps.decision_rhythm.application.advisor_sheet_intents",
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


def test_advisor_services_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep every moved symbol available from the established module path."""
    owner_exports: set[str] = set()
    for module_name in OWNER_MODULES:
        owner_module = import_module(module_name)
        exports = set(owner_module.__all__)
        owner_exports.update(exports)
        for export_name in exports:
            assert getattr(advisor_services, export_name) is getattr(owner_module, export_name)

    assert set(advisor_services.__all__) == owner_exports


def test_generate_advisor_sheet_use_case_has_focused_owner() -> None:
    """Keep the public decision-sheet use case in its dedicated owner module."""
    owner_module = import_module("apps.decision_rhythm.application.advisor_sheet")
    context_module = import_module("apps.decision_rhythm.application.advisor_sheet_context")
    intents_module = import_module("apps.decision_rhythm.application.advisor_sheet_intents")
    assert (
        advisor_services.GenerateAdvisorDecisionSheetUseCase
        is owner_module.GenerateAdvisorDecisionSheetUseCase
    )
    assert issubclass(
        owner_module.GenerateAdvisorDecisionSheetUseCase,
        context_module.AdvisorSheetContextMixin,
    )
    assert issubclass(
        owner_module.GenerateAdvisorDecisionSheetUseCase,
        intents_module.AdvisorSheetIntentMixin,
    )


def test_advisor_service_modules_stay_bounded_and_one_way() -> None:
    """Prevent owner modules from regrowing or importing the aggregator."""
    owner_files = (*OWNER_MODULES, *INTERNAL_MODULES)
    budgets = {AGGREGATOR_MODULE: 300, **dict.fromkeys(owner_files, 800)}
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
