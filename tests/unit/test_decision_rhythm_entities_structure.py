"""Structure contracts for split decision-rhythm domain entities."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from apps.decision_rhythm.domain import entities

REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_MODULE = "apps.decision_rhythm.domain.entities"
OWNER_MODULES = (
    "apps.decision_rhythm.domain.rhythm_entities",
    "apps.decision_rhythm.domain.valuation_entities",
    "apps.decision_rhythm.domain.recommendation_entities",
    "apps.decision_rhythm.domain.transition_entities",
    "apps.decision_rhythm.domain.model_param_entities",
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


def test_domain_entity_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep every moved entity available from the established module path."""
    owner_exports: set[str] = set()
    for module_name in OWNER_MODULES:
        owner_module = import_module(module_name)
        exports = set(owner_module.__all__)
        owner_exports.update(exports)
        for export_name in exports:
            assert getattr(entities, export_name) is getattr(owner_module, export_name)

    assert set(entities.__all__) == owner_exports


def test_high_risk_entities_have_focused_owners() -> None:
    """Keep transition plans and recommendations in dedicated owners."""
    transitions = import_module("apps.decision_rhythm.domain.transition_entities")
    recommendations = import_module("apps.decision_rhythm.domain.recommendation_entities")
    assert entities.PortfolioTransitionPlan is transitions.PortfolioTransitionPlan
    assert entities.UnifiedRecommendation is recommendations.UnifiedRecommendation


def test_domain_entity_modules_stay_bounded_and_one_way() -> None:
    """Prevent owner modules from regrowing or importing the aggregator."""
    budgets = {AGGREGATOR_MODULE: 200, **dict.fromkeys(OWNER_MODULES, 800)}
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
