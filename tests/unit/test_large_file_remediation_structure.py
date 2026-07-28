"""Structure contracts for the 2026-07-28 large-file remediation batch."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path
from types import ModuleType

from apps.ai_capability.application import use_cases as ai_use_cases
from apps.broker_execution.infrastructure import repositories as broker_repositories
from apps.simulated_trading.infrastructure import repositories as simulated_repositories
from apps.strategy.infrastructure import repositories as strategy_repositories
from apps.terminal.application.tui_workbench_result_models import (
    TuiWorkbenchResultModelMixin,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _non_empty_lines(module: ModuleType) -> int:
    """Return the number of non-empty source lines in a module."""

    source_path = Path(module.__file__ or "")
    source = source_path.read_text(encoding="utf-8")
    return sum(bool(line.strip()) for line in source.splitlines())


def _imports_module(module: ModuleType, module_name: str) -> bool:
    """Return whether a module imports one exact compatibility facade."""

    source_path = Path(module.__file__ or "")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == module_name:
            return True
    return False


def _assert_owner_contract(
    *,
    facade_name: str,
    owner_budgets: dict[str, int],
) -> dict[str, ModuleType]:
    """Import owner modules and enforce one-way dependencies and size budgets."""

    owners: dict[str, ModuleType] = {}
    for module_name, budget in owner_budgets.items():
        owner = import_module(module_name)
        owners[module_name] = owner
        assert not _imports_module(owner, facade_name)
        assert _non_empty_lines(owner) <= budget, (
            f"{module_name} has {_non_empty_lines(owner)} non-empty lines; " f"budget is {budget}"
        )
    return owners


def test_broker_execution_repository_split_is_bounded_and_compatible() -> None:
    """Keep the broker repository facade thin and compose focused owner mixins."""

    owners = _assert_owner_contract(
        facade_name="apps.broker_execution.infrastructure.repositories",
        owner_budgets={
            "apps.broker_execution.infrastructure.broker_access_repository": 1000,
            "apps.broker_execution.infrastructure.broker_agent_repository": 1000,
            "apps.broker_execution.infrastructure.broker_management_repository": 800,
            "apps.broker_execution.infrastructure.broker_reconciliation_repository": 800,
        },
    )
    repository_type = broker_repositories.DjangoBrokerExecutionRepository
    for owner in owners.values():
        mixin_type = getattr(owner, owner.__all__[0])
        assert issubclass(repository_type, mixin_type)
    assert _non_empty_lines(broker_repositories) <= 100


def test_strategy_repository_split_is_bounded_and_compatible() -> None:
    """Keep the legacy strategy import bound to the focused interface owner."""

    owners = _assert_owner_contract(
        facade_name="apps.strategy.infrastructure.repositories",
        owner_budgets={
            "apps.strategy.infrastructure.strategy_interface_repository": 550,
        },
    )
    owner = owners["apps.strategy.infrastructure.strategy_interface_repository"]
    assert strategy_repositories.StrategyInterfaceRepository is owner.StrategyInterfaceRepository
    assert _non_empty_lines(strategy_repositories) <= 1000


def test_tui_result_model_split_is_bounded_and_composed() -> None:
    """Keep result rendering owners independent and the public mixin compatible."""

    facade_name = "apps.terminal.application.tui_workbench_result_models"
    owners = _assert_owner_contract(
        facade_name=facade_name,
        owner_budgets={
            "apps.terminal.application.tui_workbench_collection_result_models": 500,
            "apps.terminal.application.tui_workbench_detail_result_models": 650,
        },
    )
    assert issubclass(
        TuiWorkbenchResultModelMixin,
        owners[
            "apps.terminal.application.tui_workbench_collection_result_models"
        ].TuiWorkbenchCollectionResultMixin,
    )
    assert issubclass(
        TuiWorkbenchResultModelMixin,
        owners[
            "apps.terminal.application.tui_workbench_detail_result_models"
        ].TuiWorkbenchDetailResultMixin,
    )
    assert _non_empty_lines(import_module(facade_name)) <= 650


def test_ai_capability_use_case_split_is_bounded_and_compatible() -> None:
    """Keep catalog services available from the established use-case facade."""

    owners = _assert_owner_contract(
        facade_name="apps.ai_capability.application.use_cases",
        owner_budgets={
            "apps.ai_capability.application.catalog_routing_services": 100,
            "apps.ai_capability.application.catalog_query_use_cases": 120,
        },
    )
    for owner in owners.values():
        for export_name in owner.__all__:
            assert getattr(ai_use_cases, export_name) is getattr(owner, export_name)
    assert _non_empty_lines(ai_use_cases) <= 1180


def test_simulated_trading_repository_split_is_bounded_and_compatible() -> None:
    """Keep inspection persistence in a focused repository owner."""

    owners = _assert_owner_contract(
        facade_name="apps.simulated_trading.infrastructure.repositories",
        owner_budgets={
            "apps.simulated_trading.infrastructure.inspection_repository": 250,
        },
    )
    owner = owners["apps.simulated_trading.infrastructure.inspection_repository"]
    assert simulated_repositories.DjangoInspectionRepository is owner.DjangoInspectionRepository
    assert _non_empty_lines(simulated_repositories) <= 1100
