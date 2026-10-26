"""Structure contracts for simulated-trading repository owners."""

from __future__ import annotations

import ast
from importlib import import_module
from inspect import signature
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FACADE_MODULE = "apps.simulated_trading.infrastructure.repositories"
EXPORT_OWNERS = {
    "DjangoSimulatedAccountRepository": (
        "apps.simulated_trading.infrastructure.account_repository"
    ),
    "SimulatedAccountMapper": "apps.simulated_trading.infrastructure.account_mapper",
    "DjangoPositionRepository": ("apps.simulated_trading.infrastructure.position_repository"),
    "DjangoPositionMutationRepository": (
        "apps.simulated_trading.infrastructure.position_mutation_repository"
    ),
    "PositionMapper": "apps.simulated_trading.infrastructure.position_mapper",
    "DjangoTradeRepository": "apps.simulated_trading.infrastructure.trade_repository",
    "DjangoDailyNetValueRepository": (
        "apps.simulated_trading.infrastructure.daily_net_value_repository"
    ),
    "DjangoFeeConfigRepository": ("apps.simulated_trading.infrastructure.fee_config_repository"),
    "FeeConfigMapper": "apps.simulated_trading.infrastructure.fee_config_repository",
    "DjangoInspectionRepository": ("apps.simulated_trading.infrastructure.inspection_repository"),
}
OWNER_BUDGETS = {
    "account_repository.py": 400,
    "account_query_repository.py": 200,
    "account_mapper.py": 120,
    "position_repository.py": 450,
    "position_invalidation_repository.py": 130,
    "position_mapper.py": 120,
    "position_mutation_repository.py": 260,
    "position_cost_basis_knowledge.py": 80,
    "trade_repository.py": 150,
    "trade_ledger_write_repository.py": 350,
    "trade_history_read_repository.py": 200,
    "trade_realized_pnl_summary_repository.py": 150,
    "trade_history_repository.py": 150,
    "trade_summary_repository.py": 150,
    "daily_net_value_repository.py": 150,
    "daily_net_value_read_repository.py": 200,
    "fee_config_repository.py": 200,
    "inspection_repository.py": 220,
    "repository_helpers.py": 50,
    "repositories.py": 50,
}


def _non_empty_line_count(source: str) -> int:
    """Return the number of non-empty physical lines."""

    return sum(1 for line in source.splitlines() if line.strip())


def test_simulated_repository_facade_preserves_legacy_symbol_identity() -> None:
    """Keep every legacy repository import bound to its focused owner."""

    facade = import_module(FACADE_MODULE)

    assert set(facade.__all__) == set(EXPORT_OWNERS)
    for symbol_name, owner_module_name in EXPORT_OWNERS.items():
        owner = import_module(owner_module_name)
        assert getattr(facade, symbol_name) is getattr(owner, symbol_name)


def test_simulated_account_mapper_legacy_module_preserves_identity() -> None:
    """Keep the old repository and facade bound to the focused mapper class."""

    focused_owner = import_module("apps.simulated_trading.infrastructure.account_mapper")
    legacy_module = import_module("apps.simulated_trading.infrastructure.account_repository")
    facade = import_module(FACADE_MODULE)

    assert legacy_module.SimulatedAccountMapper is focused_owner.SimulatedAccountMapper
    assert facade.SimulatedAccountMapper is focused_owner.SimulatedAccountMapper


@pytest.mark.parametrize("filename,budget", OWNER_BUDGETS.items(), ids=OWNER_BUDGETS)
def test_simulated_repository_owners_stay_bounded_and_one_way(filename: str, budget: int) -> None:
    """Prevent owner growth and reverse imports into the compatibility facade."""

    infrastructure_root = REPO_ROOT / "apps" / "simulated_trading" / "infrastructure"
    source = (infrastructure_root / filename).read_text(encoding="utf-8")
    assert _non_empty_line_count(source) <= budget, filename
    if filename == "repositories.py":
        return
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "repositories" not in imported_modules, filename
    assert FACADE_MODULE not in imported_modules, filename


def test_position_owner_legacy_modules_preserve_symbol_identity() -> None:
    """Keep the compatibility imports bound to focused position owners."""

    mapper_owner = import_module("apps.simulated_trading.infrastructure.position_mapper")
    mutation_owner = import_module(
        "apps.simulated_trading.infrastructure.position_mutation_repository"
    )
    cost_owner = import_module(
        "apps.simulated_trading.infrastructure.position_cost_basis_knowledge"
    )
    legacy_module = import_module("apps.simulated_trading.infrastructure.position_repository")
    facade = import_module(FACADE_MODULE)

    assert legacy_module.PositionMapper is mapper_owner.PositionMapper
    assert facade.PositionMapper is mapper_owner.PositionMapper
    assert legacy_module.DjangoPositionMutationRepository is (
        mutation_owner.DjangoPositionMutationRepository
    )
    assert facade.DjangoPositionMutationRepository is (
        mutation_owner.DjangoPositionMutationRepository
    )
    assert legacy_module._COST_BASIS_ECONOMIC_FIELDS is cost_owner._COST_BASIS_ECONOMIC_FIELDS
    assert legacy_module._cost_basis_economics_changed is cost_owner._cost_basis_economics_changed
    assert legacy_module._merge_cost_basis_knowledge is cost_owner._merge_cost_basis_knowledge


def test_trade_repository_summary_methods_preserve_public_signatures() -> None:
    """Keep the focused summary owner behind the established repository API."""

    trade_owner = import_module("apps.simulated_trading.infrastructure.trade_repository")
    summary_owner = import_module("apps.simulated_trading.infrastructure.trade_summary_repository")

    for method_name in (
        "sum_realized_pnl_for_closed_trades",
        "has_incomplete_closed_trade_costs",
        "get_trade_model_summary_for_account",
    ):
        assert signature(getattr(trade_owner.DjangoTradeRepository, method_name)) == signature(
            getattr(summary_owner.DjangoTradeSummaryRepository, method_name)
        )
