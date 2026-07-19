"""Structure contracts for split equity infrastructure and interface modules."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_FACADE = "apps.equity.infrastructure.repositories"
REPOSITORY_OWNERS = (
    "apps.equity.infrastructure.stock_info_repository",
    "apps.equity.infrastructure.fundamentals_repository",
    "apps.equity.infrastructure.market_data_repository",
    "apps.equity.infrastructure.intraday_repository",
    "apps.equity.infrastructure.stock_repository",
    "apps.equity.infrastructure.asset_repository",
    "apps.equity.infrastructure.config_repositories",
    "apps.equity.infrastructure.valuation_repair_repositories",
)
INTERFACE_FACADE = "apps.equity.interface.views"
INTERFACE_OWNERS = (
    "apps.equity.interface.page_views",
    "apps.equity.interface.analysis_actions",
    "apps.equity.interface.pool_actions",
    "apps.equity.interface.valuation_actions",
    "apps.equity.interface.multidim_screen_views",
    "apps.equity.interface.valuation_config_views",
)

REPOSITORY_EXPORT_OWNER = {
    "DjangoEquityAssetRepository": "apps.equity.infrastructure.asset_repository",
    "ScoringWeightConfigRepository": "apps.equity.infrastructure.config_repositories",
    "ValuationRepairConfigRepository": "apps.equity.infrastructure.config_repositories",
    "EquityBootstrapConfigRepository": "apps.equity.infrastructure.config_repositories",
    "DjangoValuationRepairRepository": (
        "apps.equity.infrastructure.valuation_repair_repositories"
    ),
    "DjangoValuationDataQualityRepository": (
        "apps.equity.infrastructure.valuation_repair_repositories"
    ),
    "compute_valuation_quality_flag": "apps.equity.infrastructure.valuation_repair_repositories",
    "build_quality_snapshot": "apps.equity.infrastructure.valuation_repair_repositories",
}

INTERFACE_EXPORT_OWNER = {
    "screen_page": "apps.equity.interface.page_views",
    "detail_page": "apps.equity.interface.page_views",
    "pool_page": "apps.equity.interface.page_views",
    "valuation_repair_page": "apps.equity.interface.page_views",
    "valuation_repair_config_page": "apps.equity.interface.page_views",
    "EquityMultiDimScreenAPIView": "apps.equity.interface.multidim_screen_views",
    "ValuationRepairConfigViewSet": "apps.equity.interface.valuation_config_views",
}

INTERFACE_PATCH_SURFACE_EXPORTS = {
    "GetValuationRepairStatusUseCase": "apps.equity.application.use_cases_valuation_repair",
    "GetValuationPercentileHistoryUseCase": "apps.equity.application.use_cases_valuation_repair",
    "ScanValuationRepairsUseCase": "apps.equity.application.use_cases_valuation_repair",
    "SyncEquityValuationUseCase": "apps.equity.application.use_cases_valuation_sync",
    "ValidateEquityValuationQualityUseCase": "apps.equity.application.use_cases_valuation_sync",
    "GetEquityValuationFreshnessUseCase": "apps.equity.application.use_cases_valuation_sync",
    "GetLatestEquityValuationQualityUseCase": "apps.equity.application.use_cases_valuation_sync",
}


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


def test_equity_repository_exports_resolve_to_owner_modules() -> None:
    """Keep established repository imports available from the legacy module path."""
    facade = import_module(REPOSITORY_FACADE)

    for export_name, owner_name in REPOSITORY_EXPORT_OWNER.items():
        owner_module = import_module(owner_name)
        assert export_name in owner_module.__all__
        assert getattr(facade, export_name) is getattr(owner_module, export_name)

    owner_stock_repository = import_module(
        "apps.equity.infrastructure.stock_repository"
    ).DjangoStockRepository
    # The facade keeps a subclass so the legacy on-demand-service monkeypatch
    # path keeps working; method patches on it remain global to all consumers.
    assert issubclass(facade.DjangoStockRepository, owner_stock_repository)
    assert facade.DjangoStockRepository.__name__ == "DjangoStockRepository"

    expected_all = {
        *REPOSITORY_EXPORT_OWNER,
        "DjangoStockRepository",
        "make_on_demand_data_center_service",
    }
    assert set(facade.__all__) == expected_all


def test_equity_repository_facade_preserves_on_demand_patch_surface() -> None:
    """Patching the facade on-demand factory must steer new repositories."""
    facade = import_module(REPOSITORY_FACADE)
    sentinel = object()

    with patch(
        f"{REPOSITORY_FACADE}.make_on_demand_data_center_service",
        return_value=sentinel,
    ):
        repository = facade.DjangoStockRepository()

    assert repository._dc_on_demand is sentinel


def test_equity_view_exports_resolve_to_owner_modules() -> None:
    """Keep established view imports and patch-surface names stable."""
    facade = import_module(INTERFACE_FACADE)

    for export_name, owner_name in INTERFACE_EXPORT_OWNER.items():
        owner_module = import_module(owner_name)
        assert export_name in owner_module.__all__
        assert getattr(facade, export_name) is getattr(owner_module, export_name)

    for export_name, source_name in INTERFACE_PATCH_SURFACE_EXPORTS.items():
        source_module = import_module(source_name)
        assert getattr(facade, export_name) is getattr(source_module, export_name)

    for mixin_owner, mixin_name in (
        ("apps.equity.interface.sdk_contract_actions", "EquitySDKContractActionsMixin"),
        ("apps.equity.interface.analysis_actions", "EquityAnalysisActionsMixin"),
        ("apps.equity.interface.pool_actions", "EquityPoolActionsMixin"),
        ("apps.equity.interface.valuation_actions", "EquityValuationActionsMixin"),
    ):
        mixin_module = import_module(mixin_owner)
        if mixin_owner in INTERFACE_OWNERS:
            assert mixin_name in mixin_module.__all__
        assert issubclass(facade.EquityViewSet, getattr(mixin_module, mixin_name))

    expected_all = {
        *INTERFACE_EXPORT_OWNER,
        *INTERFACE_PATCH_SURFACE_EXPORTS,
        "DjangoStockRepository",
        "DjangoValuationRepairRepository",
        "EquityViewSet",
    }
    assert set(facade.__all__) == expected_all


def test_equity_split_modules_stay_bounded_and_one_way() -> None:
    """Prevent owner modules from regrowing or importing their facades."""
    budgets = {
        REPOSITORY_FACADE: 150,
        "apps.equity.infrastructure.stock_info_repository": 400,
        "apps.equity.infrastructure.fundamentals_repository": 750,
        "apps.equity.infrastructure.market_data_repository": 650,
        "apps.equity.infrastructure.intraday_repository": 450,
        "apps.equity.infrastructure.stock_repository": 250,
        "apps.equity.infrastructure.asset_repository": 350,
        "apps.equity.infrastructure.config_repositories": 300,
        "apps.equity.infrastructure.valuation_repair_repositories": 350,
        INTERFACE_FACADE: 150,
        "apps.equity.interface.page_views": 150,
        "apps.equity.interface.analysis_actions": 550,
        "apps.equity.interface.pool_actions": 250,
        "apps.equity.interface.valuation_actions": 500,
        "apps.equity.interface.multidim_screen_views": 150,
        "apps.equity.interface.valuation_config_views": 250,
    }
    facade_by_owner = {
        **dict.fromkeys(REPOSITORY_OWNERS, REPOSITORY_FACADE),
        **dict.fromkeys(INTERFACE_OWNERS, INTERFACE_FACADE),
    }
    for module_name, budget in budgets.items():
        relative_path = Path(*module_name.split(".")).with_suffix(".py")
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())
        assert (
            non_empty_lines <= budget
        ), f"{relative_path} has {non_empty_lines} non-empty lines; budget is {budget}"
        facade_name = facade_by_owner.get(module_name)
        if facade_name is not None:
            assert not _imports_module(
                source, facade_name
            ), f"{relative_path} must not import the compatibility facade"
