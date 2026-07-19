"""Structure contracts for the split strategy interface views module."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
INTERFACE_FACADE = "apps.strategy.interface.views"
INTERFACE_OWNERS = (
    "apps.strategy.interface.page_views",
    "apps.strategy.interface.execution_views",
    "apps.strategy.interface.strategy_api_views",
    "apps.strategy.interface.rule_api_views",
    "apps.strategy.interface.assignment_api_views",
    "apps.strategy.interface.execution_log_api_views",
)

INTERFACE_EXPORT_OWNER = {
    "strategy_list": "apps.strategy.interface.page_views",
    "strategy_create": "apps.strategy.interface.page_views",
    "strategy_detail": "apps.strategy.interface.page_views",
    "strategy_edit": "apps.strategy.interface.page_views",
    "strategy_toggle_status": "apps.strategy.interface.page_views",
    "strategy_execute": "apps.strategy.interface.execution_views",
    "execution_evaluate": "apps.strategy.interface.execution_views",
    "test_script": "apps.strategy.interface.execution_views",
    "test_strategy": "apps.strategy.interface.execution_views",
    "StrategyViewSet": "apps.strategy.interface.strategy_api_views",
    "ScriptConfigViewSet": "apps.strategy.interface.strategy_api_views",
    "AIStrategyConfigViewSet": "apps.strategy.interface.strategy_api_views",
    "PositionManagementRuleViewSet": "apps.strategy.interface.rule_api_views",
    "RuleConditionViewSet": "apps.strategy.interface.rule_api_views",
    "PortfolioStrategyAssignmentViewSet": "apps.strategy.interface.assignment_api_views",
    "bind_strategy": "apps.strategy.interface.assignment_api_views",
    "unbind_strategy": "apps.strategy.interface.assignment_api_views",
    "StrategyExecutionLogViewSet": "apps.strategy.interface.execution_log_api_views",
}

# ORM model aliases kept on the facade as the legacy monkeypatch surface.
MODEL_ALIAS_NAMES = (
    "AIStrategyConfigModel",
    "PortfolioStrategyAssignmentModel",
    "PositionManagementRuleModel",
    "RuleConditionModel",
    "ScriptConfigModel",
    "StrategyExecutionLogModel",
    "StrategyModel",
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


def test_strategy_view_exports_resolve_to_owner_modules() -> None:
    """Keep established view imports available from the legacy module path."""
    facade = import_module(INTERFACE_FACADE)

    for export_name, owner_name in INTERFACE_EXPORT_OWNER.items():
        owner_module = import_module(owner_name)
        assert export_name in owner_module.__all__
        assert getattr(facade, export_name) is getattr(owner_module, export_name)

    expected_all = {*INTERFACE_EXPORT_OWNER, *MODEL_ALIAS_NAMES}
    assert set(facade.__all__) == expected_all


def test_strategy_view_facade_preserves_model_patch_surface() -> None:
    """ORM model aliases stay identical to the runtime models they alias."""
    from django.apps import apps as django_apps

    facade = import_module(INTERFACE_FACADE)

    for alias_name in MODEL_ALIAS_NAMES:
        assert getattr(facade, alias_name) is django_apps.get_model(
            "strategy", alias_name
        )

    # The exact legacy dotted patch path used by the binding-consistency
    # integration suite must keep resolving on the facade module.
    with patch(
        f"{INTERFACE_FACADE}.PortfolioStrategyAssignmentModel._default_manager.select_for_update"
    ) as mocked:
        assert (
            facade.PortfolioStrategyAssignmentModel._default_manager.select_for_update
            is mocked
        )


def test_strategy_split_modules_stay_bounded_and_one_way() -> None:
    """Prevent owner modules from regrowing or importing their facade."""
    budgets = {
        INTERFACE_FACADE: 150,
        "apps.strategy.interface.page_views": 600,
        "apps.strategy.interface.execution_views": 500,
        "apps.strategy.interface.strategy_api_views": 400,
        "apps.strategy.interface.rule_api_views": 200,
        "apps.strategy.interface.assignment_api_views": 300,
        "apps.strategy.interface.execution_log_api_views": 200,
    }
    for module_name, budget in budgets.items():
        relative_path = Path(*module_name.split(".")).with_suffix(".py")
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())
        assert (
            non_empty_lines <= budget
        ), f"{relative_path} has {non_empty_lines} non-empty lines; budget is {budget}"
        if module_name != INTERFACE_FACADE:
            assert not _imports_module(
                source, INTERFACE_FACADE
            ), f"{relative_path} must not import the compatibility facade"
