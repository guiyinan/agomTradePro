"""Structure contracts for split account ORM models."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from django.apps import apps

from apps.account.infrastructure import models

REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_MODULE = "apps.account.infrastructure.models"
OWNER_MODULES = (
    "apps.account.infrastructure.identity_models",
    "apps.account.infrastructure.classification_models",
    "apps.account.infrastructure.portfolio_models",
    "apps.account.infrastructure.trading_config_models",
    "apps.account.infrastructure.documentation_models",
)
# Cross-app model re-exports are forbidden after the Config Center cutover.
EXTERNAL_REEXPORTS: dict[str, str] = {}


def _imports_module(source: str, module_name: str) -> bool:
    """Return whether source imports one exact module."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == module_name:
            return True
    return False


def _imports_facade_relative(source: str) -> bool:
    """Return whether source imports the facade via a relative `from .models import`."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "models":
            return True
    return False


def test_account_model_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep established model imports and Django registrations stable."""
    owner_exports: set[str] = set()
    for module_name in OWNER_MODULES:
        owner_module = import_module(module_name)
        exports = set(owner_module.__all__)
        owner_exports.update(exports)
        for export_name in exports:
            exported_model = getattr(models, export_name)
            assert exported_model is getattr(owner_module, export_name)
            assert apps.get_model("account", export_name) is exported_model

    assert owner_exports == set(models.__all__) - set(EXTERNAL_REEXPORTS)


def test_account_model_external_reexports_stay_stable() -> None:
    """Keep the account ORM facade free of cross-app owner aliases."""

    assert EXTERNAL_REEXPORTS == {}
    assert not hasattr(models, "SystemSettingsModel")


def test_account_model_modules_stay_bounded_and_one_way() -> None:
    """Prevent model owners from regrowing or importing the aggregator."""
    budgets = {
        AGGREGATOR_MODULE: 100,
        "apps.account.infrastructure.identity_models": 450,
        "apps.account.infrastructure.classification_constraints": 80,
        "apps.account.infrastructure.classification_models": 350,
        "apps.account.infrastructure.portfolio_models": 500,
        "apps.account.infrastructure.trading_config_models": 550,
        "apps.account.infrastructure.documentation_models": 100,
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
            assert not _imports_facade_relative(
                source
            ), f"{relative_path} must not import the facade via relative import"
