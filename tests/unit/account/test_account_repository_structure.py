"""Structure and compatibility contracts for Account repository ownership."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from apps.account.infrastructure import repositories

REPO_ROOT = Path(__file__).resolve().parents[3]

OWNER_MODULES = {
    "AccountRepository": "apps.account.infrastructure.account_profile_repository",
    "AccountClassificationRepository": ("apps.account.infrastructure.account_profile_repository"),
    "PortfolioRepository": "apps.account.infrastructure.portfolio_repository",
    "PositionRepository": "apps.account.infrastructure.position_repository",
    "PortfolioApiRepository": "apps.account.infrastructure.portfolio_api_repository",
    "AssetMetadataRepository": "apps.account.infrastructure.asset_metadata_repository",
    "AccountInterfaceRepository": ("apps.account.infrastructure.account_interface_repository"),
}

MODULE_BUDGETS = {
    "apps/account/infrastructure/repositories.py": 1000,
    "apps/account/infrastructure/account_profile_repository.py": 800,
    "apps/account/infrastructure/portfolio_repository.py": 800,
    "apps/account/infrastructure/position_repository.py": 800,
    "apps/account/infrastructure/portfolio_api_repository.py": 800,
    "apps/account/infrastructure/asset_metadata_repository.py": 300,
    "apps/account/infrastructure/account_interface_repository.py": 200,
    "apps/account/infrastructure/account_interface_registration_repository.py": 800,
    "apps/account/infrastructure/account_interface_portfolio_repository.py": 800,
    "apps/account/infrastructure/account_interface_administration_repository.py": 800,
}


def _imports_module(source: str, module_name: str) -> bool:
    """Return whether source imports the compatibility aggregator."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == module_name:
            return True
    return False


def test_account_repository_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep every moved class available from the established import path."""
    for class_name, module_name in OWNER_MODULES.items():
        owner_module = import_module(module_name)
        assert getattr(repositories, class_name) is getattr(owner_module, class_name)


def test_account_interface_repository_composes_focused_mixins() -> None:
    """Keep the public interface repository thin and responsibility-oriented."""
    owner_module = import_module("apps.account.infrastructure.account_interface_repository")
    registration_module = import_module(
        "apps.account.infrastructure.account_interface_registration_repository"
    )
    portfolio_module = import_module(
        "apps.account.infrastructure.account_interface_portfolio_repository"
    )
    administration_module = import_module(
        "apps.account.infrastructure.account_interface_administration_repository"
    )

    repository_type = owner_module.AccountInterfaceRepository
    assert issubclass(
        repository_type,
        registration_module.AccountInterfaceRegistrationRepositoryMixin,
    )
    assert issubclass(
        repository_type,
        portfolio_module.AccountInterfacePortfolioRepositoryMixin,
    )
    assert issubclass(
        repository_type,
        administration_module.AccountInterfaceAdministrationRepositoryMixin,
    )


def test_account_repository_modules_stay_bounded_and_one_way() -> None:
    """Prevent owner modules from regrowing or importing the aggregator."""
    aggregator = "apps.account.infrastructure.repositories"
    for relative_path, budget in MODULE_BUDGETS.items():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())
        assert (
            non_empty_lines <= budget
        ), f"{relative_path} has {non_empty_lines} non-empty lines; budget is {budget}"
        if relative_path != "apps/account/infrastructure/repositories.py":
            assert not _imports_module(
                source, aggregator
            ), f"{relative_path} must not import the compatibility aggregator"


def test_system_settings_repository_reads_asset_proxy_from_config_center(monkeypatch) -> None:
    """Asset proxy reads must use the Config Center public port, not the legacy singleton."""

    monkeypatch.setattr(
        "apps.account.infrastructure.repositories.get_runtime_asset_proxy_map",
        lambda: {"equity": "510300.SH"},
    )
    assert not hasattr(
        repositories.SystemSettingsModel,
        "get_runtime_asset_proxy_code",
    )

    repository = repositories.SystemSettingsRepository()

    assert repository.get_runtime_asset_proxy_code("equity", "fallback") == "510300.SH"
    assert repository.get_runtime_asset_proxy_code("unknown", "fallback") == "fallback"
