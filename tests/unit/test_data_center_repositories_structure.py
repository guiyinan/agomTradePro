"""Structure contracts for split data-center repositories and thermometer use cases."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from apps.data_center.application import market_thermometer
from apps.data_center.infrastructure import repositories

REPO_ROOT = Path(__file__).resolve().parents[2]
REPOSITORIES_FACADE = "apps.data_center.infrastructure.repositories"
REPOSITORY_OWNER_MODULES = (
    "apps.data_center.infrastructure._repository_helpers",
    "apps.data_center.infrastructure.provider_state_repositories",
    "apps.data_center.infrastructure.market_thermometer_repositories",
    "apps.data_center.infrastructure.catalog_repositories",
    "apps.data_center.infrastructure.catalog_runtime_repositories",
    "apps.data_center.infrastructure.macro_fact_repositories",
    "apps.data_center.infrastructure.macro_fact_storage_repository",
    "apps.data_center.infrastructure.market_data_repositories",
    "apps.data_center.infrastructure.price_bar_repository",
    "apps.data_center.infrastructure.quote_snapshot_repository",
    "apps.data_center.infrastructure.fundamental_fact_repositories",
    "apps.data_center.infrastructure.financial_availability_repository",
    "apps.data_center.infrastructure.financial_fact_repository",
    "apps.data_center.infrastructure.fund_nav_repository",
    "apps.data_center.infrastructure.valuation_fact_repository",
    "apps.data_center.infrastructure.market_breadth_repositories",
    "apps.data_center.infrastructure._market_breadth_helpers",
    "apps.data_center.infrastructure.news_repository",
    "apps.data_center.infrastructure._reconciliation_evidence_repository_helpers",
    "apps.data_center.infrastructure.reconciliation_evidence_repositories",
    "apps.data_center.infrastructure.reconciliation_evidence_unit_of_work",
)
THERMOMETER_FACADE = "apps.data_center.application.market_thermometer"
THERMOMETER_OWNER_MODULES = (
    "apps.data_center.application.market_thermometer_specs",
    "apps.data_center.application._market_thermometer_runtime",
    "apps.data_center.application.market_thermometer_config_use_cases",
    "apps.data_center.application.market_thermometer_import_use_cases",
    "apps.data_center.application.market_thermometer_sync",
    "apps.data_center.application.market_thermometer_calculate",
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


def _non_empty_lines(module_name: str) -> int:
    relative_path = Path(*module_name.split(".")).with_suffix(".py")
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    return sum(bool(line.strip()) for line in source.splitlines())


def test_repository_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep every referenced repository symbol available from the legacy path."""
    expected_owners = {
        "AssetRepository": "apps.data_center.infrastructure.catalog_repositories",
        "CapitalFlowRepository": "apps.data_center.infrastructure.market_breadth_repositories",
        "DataOwnerRegistryRepository": (
            "apps.data_center.infrastructure.catalog_runtime_repositories"
        ),
        "DatasetContractRepository": (
            "apps.data_center.infrastructure.catalog_runtime_repositories"
        ),
        "FinancialFactRepository": ("apps.data_center.infrastructure.financial_fact_repository"),
        "FundNavRepository": "apps.data_center.infrastructure.fund_nav_repository",
        "IndicatorCatalogRepository": "apps.data_center.infrastructure.catalog_repositories",
        "IndicatorUnitRuleRepository": "apps.data_center.infrastructure.catalog_repositories",
        "MacroFactRepository": ("apps.data_center.infrastructure.macro_fact_storage_repository"),
        "MacroGovernanceRepository": "apps.data_center.infrastructure.macro_fact_repositories",
        "MarketThermometerConfigRepository": (
            "apps.data_center.infrastructure.market_thermometer_repositories"
        ),
        "MarketThermometerSnapshotRepository": (
            "apps.data_center.infrastructure.market_thermometer_repositories"
        ),
        "MarketThermometerUserOverrideRepository": (
            "apps.data_center.infrastructure.market_thermometer_repositories"
        ),
        "NewsRepository": "apps.data_center.infrastructure.news_repository",
        "PriceBarRepository": "apps.data_center.infrastructure.price_bar_repository",
        "ProductionCoverageUniverseConfigRepository": (
            "apps.data_center.infrastructure.provider_state_repositories"
        ),
        "ProviderConfigRepository": "apps.data_center.infrastructure.provider_state_repositories",
        "ProviderBindingRepository": (
            "apps.data_center.infrastructure.catalog_runtime_repositories"
        ),
        "PublisherCatalogRepository": "apps.data_center.infrastructure.catalog_repositories",
        "PublicationPolicyRepository": (
            "apps.data_center.infrastructure.catalog_runtime_repositories"
        ),
        "QuoteSnapshotRepository": ("apps.data_center.infrastructure.quote_snapshot_repository"),
        "RawAuditRepository": "apps.data_center.infrastructure.provider_state_repositories",
        "ReconciliationEvidenceRepository": (
            "apps.data_center.infrastructure.reconciliation_evidence_repositories"
        ),
        "SectorMembershipRepository": (
            "apps.data_center.infrastructure.market_breadth_repositories"
        ),
        "ValuationFactRepository": ("apps.data_center.infrastructure.valuation_fact_repository"),
        "_build_asset_code_candidates": "apps.data_center.infrastructure._repository_helpers",
    }
    assert set(repositories.__all__) == set(expected_owners)
    for export_name, owner_module_name in expected_owners.items():
        owner_module = import_module(owner_module_name)
        assert getattr(repositories, export_name) is getattr(owner_module, export_name)
    compatibility_module = import_module(
        "apps.data_center.infrastructure.reconciliation_evidence_repositories"
    )
    unit_of_work_module = import_module(
        "apps.data_center.infrastructure.reconciliation_evidence_unit_of_work"
    )
    assert compatibility_module.DjangoReconciliationEvidenceUnitOfWork is (
        unit_of_work_module.DjangoReconciliationEvidenceUnitOfWork
    )
    assert not hasattr(repositories, "DataProviderSettingsRepository")


def test_repository_modules_stay_bounded_and_one_way() -> None:
    """Prevent repository owners from regrowing or importing the facade."""
    budgets = {
        REPOSITORIES_FACADE: 150,
        "apps.data_center.infrastructure._repository_helpers": 200,
        "apps.data_center.infrastructure.provider_state_repositories": 250,
        "apps.data_center.infrastructure.market_thermometer_repositories": 200,
        "apps.data_center.infrastructure.catalog_repositories": 400,
        "apps.data_center.infrastructure.catalog_runtime_repositories": 250,
        "apps.data_center.infrastructure.macro_fact_repositories": 600,
        "apps.data_center.infrastructure.macro_fact_storage_repository": 300,
        "apps.data_center.infrastructure.market_data_repositories": 50,
        "apps.data_center.infrastructure.price_bar_repository": 200,
        "apps.data_center.infrastructure.quote_snapshot_repository": 200,
        "apps.data_center.infrastructure.fundamental_fact_repositories": 50,
        "apps.data_center.infrastructure.financial_availability_repository": 100,
        "apps.data_center.infrastructure.financial_fact_repository": 200,
        "apps.data_center.infrastructure.fund_nav_repository": 150,
        "apps.data_center.infrastructure.valuation_fact_repository": 220,
        "apps.data_center.infrastructure.market_breadth_repositories": 400,
        "apps.data_center.infrastructure._market_breadth_helpers": 100,
        "apps.data_center.infrastructure.news_repository": 250,
        "apps.data_center.infrastructure._reconciliation_evidence_repository_helpers": 100,
        "apps.data_center.infrastructure.reconciliation_evidence_repositories": 100,
        "apps.data_center.infrastructure.reconciliation_evidence_unit_of_work": 100,
    }
    for module_name, budget in budgets.items():
        relative_path = Path(*module_name.split(".")).with_suffix(".py")
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())
        assert (
            non_empty_lines <= budget
        ), f"{relative_path} has {non_empty_lines} non-empty lines; budget is {budget}"
        if module_name != REPOSITORIES_FACADE:
            assert not _imports_module(
                source, REPOSITORIES_FACADE
            ), f"{relative_path} must not import the compatibility facade"


def test_market_thermometer_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep moved thermometer symbols and the monkeypatch surface stable."""
    expected_owners = {
        "CalculateMarketThermometerUseCase": (
            "apps.data_center.application.market_thermometer_calculate"
        ),
        "ImportInvestorAccountsUseCase": (
            "apps.data_center.application.market_thermometer_import_use_cases"
        ),
        "ManageMarketThermometerConfigUseCase": (
            "apps.data_center.application.market_thermometer_config_use_cases"
        ),
        "ManageMarketThermometerUserOverrideUseCase": (
            "apps.data_center.application.market_thermometer_config_use_cases"
        ),
        "SyncMarketThermometerInputsUseCase": (
            "apps.data_center.application.market_thermometer_sync"
        ),
        "build_market_thermometer_override_payload": (
            "apps.data_center.application.market_thermometer_config_use_cases"
        ),
        "resolve_market_thermometer_as_of_date": (
            "apps.data_center.application.market_thermometer_dates"
        ),
    }
    constant_names = {
        "DEFAULT_MARKET_DATA_SOURCE_TYPES",
        "DEFAULT_NEWS_SOURCE_TYPES",
        "ETF_MAIN_FLOW_CODE",
        "ETF_NET_FLOW_PROVIDER_TIMEOUT_SECONDS",
        "ETF_SIZE_FLOW_CODE",
        "MARKET_COMPONENT_SPECS",
        "MARKET_NEWS_POSITIVE_RATIO_CODE",
        "MARKET_THERMOMETER_CONSENSUS_SOURCE",
        "MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES",
        "MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS",
        "MARKET_THERMOMETER_SOURCE_TOLERANCE",
        "RECOVERABLE_THERMOMETER_EXCEPTIONS",
        "RECOVERABLE_THERMOMETER_EXCEPTION_NAMES",
    }
    assert set(market_thermometer.__all__) == set(expected_owners) | constant_names
    for export_name, owner_module_name in expected_owners.items():
        owner_module = import_module(owner_module_name)
        assert getattr(market_thermometer, export_name) is getattr(owner_module, export_name)

    specs_module = import_module("apps.data_center.application.market_thermometer_specs")
    for constant_name in constant_names:
        assert getattr(market_thermometer, constant_name) is getattr(specs_module, constant_name)

    runtime_module = import_module("apps.data_center.application._market_thermometer_runtime")
    assert runtime_module._FACADE is market_thermometer


def test_market_thermometer_modules_stay_bounded_and_one_way() -> None:
    """Prevent thermometer owners from regrowing or importing the facade."""
    budgets = {
        THERMOMETER_FACADE: 150,
        "apps.data_center.application.market_thermometer_specs": 150,
        "apps.data_center.application._market_thermometer_runtime": 120,
        "apps.data_center.application.market_thermometer_config_use_cases": 200,
        "apps.data_center.application.market_thermometer_import_use_cases": 180,
        "apps.data_center.application.market_thermometer_sync": 800,
        "apps.data_center.application.market_thermometer_calculate": 750,
    }
    for module_name, budget in budgets.items():
        relative_path = Path(*module_name.split(".")).with_suffix(".py")
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())
        assert (
            non_empty_lines <= budget
        ), f"{relative_path} has {non_empty_lines} non-empty lines; budget is {budget}"
        if module_name != THERMOMETER_FACADE:
            assert not _imports_module(
                source, THERMOMETER_FACADE
            ), f"{relative_path} must not import the compatibility facade"
