"""Durable structure contracts for the completed large-file splits."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SplitModuleContract:
    """Define a local size budget and forbidden reverse dependencies."""

    path: str
    max_non_empty_lines: int
    forbidden_imports: tuple[str, ...] = ()


IDENTITY_ACCESS_AGGREGATOR = (
    "apps.terminal.infrastructure.tui_metadata_runtime_injection_identity_access"
)
ALPHA_HOMEPAGE_ENTRYPOINT = "apps.dashboard.application.alpha_homepage"
DASHBOARD_VIEWS_ENTRYPOINT = "apps.dashboard.interface.views"
ALPHA_TASKS_ENTRYPOINT = "apps.alpha.application.tasks"

CONTRACTS = (
    SplitModuleContract(
        "apps/terminal/infrastructure/tui_metadata_runtime_injection_identity_access.py",
        250,
    ),
    SplitModuleContract(
        "apps/terminal/infrastructure/tui_metadata_runtime_injection_mcp_access.py",
        800,
        (IDENTITY_ACCESS_AGGREGATOR,),
    ),
    SplitModuleContract(
        "apps/terminal/infrastructure/tui_metadata_runtime_injection_ai_user_providers.py",
        800,
        (IDENTITY_ACCESS_AGGREGATOR,),
    ),
    SplitModuleContract(
        "apps/terminal/infrastructure/tui_metadata_runtime_injection_ai_system_providers.py",
        800,
        (IDENTITY_ACCESS_AGGREGATOR,),
    ),
    SplitModuleContract(
        "apps/terminal/infrastructure/tui_metadata_runtime_injection_ai_quotas.py",
        800,
        (IDENTITY_ACCESS_AGGREGATOR,),
    ),
    SplitModuleContract("apps/dashboard/application/alpha_homepage.py", 600),
    SplitModuleContract(
        "apps/dashboard/application/alpha_homepage_candidates.py",
        800,
        (ALPHA_HOMEPAGE_ENTRYPOINT,),
    ),
    SplitModuleContract(
        "apps/dashboard/application/alpha_homepage_exit_watch.py",
        800,
        (ALPHA_HOMEPAGE_ENTRYPOINT,),
    ),
    SplitModuleContract(
        "apps/dashboard/application/alpha_homepage_history.py",
        800,
        (ALPHA_HOMEPAGE_ENTRYPOINT,),
    ),
    SplitModuleContract(
        "apps/dashboard/application/alpha_homepage_runtime.py",
        800,
        (ALPHA_HOMEPAGE_ENTRYPOINT,),
    ),
    SplitModuleContract("apps/dashboard/interface/views.py", 900),
    SplitModuleContract(
        "apps/dashboard/interface/dashboard_alpha_context.py",
        800,
        (DASHBOARD_VIEWS_ENTRYPOINT,),
    ),
    SplitModuleContract(
        "apps/dashboard/interface/dashboard_navigation_context.py",
        800,
        (DASHBOARD_VIEWS_ENTRYPOINT,),
    ),
    SplitModuleContract(
        "apps/dashboard/interface/dashboard_regime_context.py",
        800,
        (DASHBOARD_VIEWS_ENTRYPOINT,),
    ),
    SplitModuleContract("apps/alpha/application/tasks.py", 1100),
    SplitModuleContract(
        "apps/alpha/application/model_evaluation_service.py",
        100,
        (ALPHA_TASKS_ENTRYPOINT,),
    ),
    SplitModuleContract(
        "apps/alpha/application/prediction_refresh_orchestration.py",
        100,
        (ALPHA_TASKS_ENTRYPOINT,),
    ),
    SplitModuleContract(
        "apps/alpha/infrastructure/qlib_artifact_runtime.py",
        800,
        (ALPHA_TASKS_ENTRYPOINT,),
    ),
    SplitModuleContract(
        "apps/alpha/infrastructure/qlib_prediction_runtime.py",
        800,
        (ALPHA_TASKS_ENTRYPOINT,),
    ),
    SplitModuleContract(
        "apps/alpha/infrastructure/qlib_runtime_init.py",
        800,
        (ALPHA_TASKS_ENTRYPOINT,),
    ),
)


def _imported_modules(source: str) -> set[str]:
    """Return absolute module names imported by the source text."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _matches_module(imported: str, forbidden: str) -> bool:
    """Return whether an import resolves to a forbidden module namespace."""
    return imported == forbidden or imported.startswith(f"{forbidden}.")


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda item: item.path)
def test_remediated_module_respects_local_structure_contract(
    contract: SplitModuleContract,
) -> None:
    """Prevent remediated modules from regrowing or importing their entrypoint."""
    source = (REPO_ROOT / contract.path).read_text(encoding="utf-8")
    non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())

    assert non_empty_lines <= contract.max_non_empty_lines, (
        f"{contract.path} has {non_empty_lines} non-empty lines; "
        f"local budget is {contract.max_non_empty_lines}"
    )

    imported_modules = _imported_modules(source)
    reverse_dependencies = {
        imported
        for imported in imported_modules
        for forbidden in contract.forbidden_imports
        if _matches_module(imported, forbidden)
    }
    assert not reverse_dependencies, (
        f"{contract.path} imports its compatibility entrypoint: " f"{sorted(reverse_dependencies)}"
    )
