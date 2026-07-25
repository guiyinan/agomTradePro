"""Structure contracts for simulated-trading repository owners."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FACADE_MODULE = "apps.simulated_trading.infrastructure.repositories"
EXPORT_OWNERS = {
    "DjangoSimulatedAccountRepository": (
        "apps.simulated_trading.infrastructure.account_repository"
    ),
    "SimulatedAccountMapper": "apps.simulated_trading.infrastructure.account_repository",
    "DjangoPositionRepository": ("apps.simulated_trading.infrastructure.position_repository"),
    "DjangoPositionMutationRepository": (
        "apps.simulated_trading.infrastructure.position_repository"
    ),
    "PositionMapper": "apps.simulated_trading.infrastructure.position_repository",
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
    "position_repository.py": 450,
    "trade_repository.py": 150,
    "daily_net_value_repository.py": 150,
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


def test_simulated_repository_owners_stay_bounded_and_one_way() -> None:
    """Prevent owner growth and reverse imports into the compatibility facade."""

    infrastructure_root = REPO_ROOT / "apps" / "simulated_trading" / "infrastructure"
    for filename, budget in OWNER_BUDGETS.items():
        source = (infrastructure_root / filename).read_text(encoding="utf-8")
        assert _non_empty_line_count(source) <= budget, filename
        if filename == "repositories.py":
            continue
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "repositories" not in imported_modules, filename
