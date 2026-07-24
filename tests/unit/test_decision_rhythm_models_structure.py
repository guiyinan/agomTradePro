"""Structure contracts for split decision-rhythm ORM models."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from django.apps import apps

from apps.decision_rhythm.infrastructure import models

REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_MODULE = "apps.decision_rhythm.infrastructure.models"
OWNER_MODULES = (
    "apps.decision_rhythm.infrastructure.input_snapshot_models",
    "apps.decision_rhythm.infrastructure.rhythm_models",
    "apps.decision_rhythm.infrastructure.valuation_models",
    "apps.decision_rhythm.infrastructure.recommendation_models",
    "apps.decision_rhythm.infrastructure.model_param_models",
)
SUPPORT_MODULES = ("apps.decision_rhythm.infrastructure.transition_models",)


def _imports_module(source: str, module_name: str) -> bool:
    """Return whether source imports one exact module."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == module_name:
            return True
    return False


def test_decision_model_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep established model imports and Django registrations stable."""
    owner_exports: set[str] = set()
    for module_name in OWNER_MODULES:
        owner_module = import_module(module_name)
        exports = set(owner_module.__all__)
        owner_exports.update(exports)
        for export_name in exports:
            exported_model = getattr(models, export_name)
            assert exported_model is getattr(owner_module, export_name)
            assert apps.get_model("decision_rhythm", export_name) is exported_model

    assert owner_exports == set(models.__all__)
    assert models.PortfolioTransitionPlanModel is apps.get_model(
        "portfolio", "PortfolioTransitionPlanModel"
    )


def test_decision_model_modules_stay_bounded_and_one_way() -> None:
    """Prevent model owners from regrowing or importing the aggregator."""
    budgets = {
        AGGREGATOR_MODULE: 100,
        "apps.decision_rhythm.infrastructure.input_snapshot_models": 100,
        "apps.decision_rhythm.infrastructure.rhythm_models": 750,
        "apps.decision_rhythm.infrastructure.valuation_models": 850,
        "apps.decision_rhythm.infrastructure.transition_models": 200,
        "apps.decision_rhythm.infrastructure.recommendation_models": 650,
        "apps.decision_rhythm.infrastructure.model_param_models": 350,
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

    assert set(SUPPORT_MODULES).issubset(budgets)
