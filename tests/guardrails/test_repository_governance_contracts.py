"""Repository-level contracts for documentation inventory and generated artifacts."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_agents_routes_app_inventory_to_machine_governance_source() -> None:
    """Keep AGENTS as a route to the machine baseline, not a second inventory."""

    agents_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    baseline = json.loads(
        (REPO_ROOT / "governance" / "governance_baseline.json").read_text(encoding="utf-8")
    )

    assert "governance/governance_baseline.json" in agents_text
    assert baseline["module_shape_minimums"]
    assert "├── apps/" not in agents_text
    assert "├── shared/" not in agents_text
    assert "Market Data 模块" not in agents_text


def test_sqlite_test_databases_are_not_written_to_repository_root() -> None:
    """Keep per-process test databases in the operating-system temp directory."""

    settings_text = (REPO_ROOT / "core" / "settings" / "development_sqlite.py").read_text(
        encoding="utf-8"
    )
    assert "tempfile.gettempdir()" in settings_text
    assert "os.path.join(BASE_DIR, f'test_db_" not in settings_text


def test_generated_workspace_artifacts_are_ignored_and_cleanable() -> None:
    """Require durable ignore rules and an explicit cleanup command."""

    ignore_lines = set((REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert {"test_db_*.sqlite3", "*.log", "/tmp", "*.stackdump"} <= ignore_lines
    assert (REPO_ROOT / "scripts" / "clean-workspace-artifacts.ps1").is_file()


def test_mypy_debt_is_precisely_governed_without_broad_ignores() -> None:
    """Keep legacy errors explicit and enforce their per-file, per-code ceiling in CI."""

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        overrides = tomllib.load(handle)["tool"]["mypy"]["overrides"]
    ignored_modules = {
        module
        for override in overrides
        if override.get("ignore_errors") is True
        for module in override["module"]
    }

    assert ignored_modules == set()

    error_baseline = json.loads(
        (REPO_ROOT / "governance" / "mypy_error_baseline.json").read_text(encoding="utf-8")
    )["modules"]
    assert all(path.endswith(".py") for path in error_baseline)
    assert all(
        error_counts
        and all(isinstance(count, int) and count > 0 for count in error_counts.values())
        for error_counts in error_baseline.values()
    )
    assert "apps/task_monitor/application/interface_services.py" not in error_baseline

    workflow_text = (REPO_ROOT / ".github" / "workflows" / "ci-fast-feedback.yml").read_text(
        encoding="utf-8"
    )
    assert "python scripts/check_mypy_regression.py" in workflow_text
    assert "python scripts/check_mypy_debt_ceiling.py" in workflow_text
    assert '--reference-ref "${{ needs.detect-tests.outputs.base-ref }}"' in workflow_text

    full_baseline = json.loads(
        (REPO_ROOT / "governance" / "mypy_debt_baseline.json").read_text(encoding="utf-8")
    )
    assert full_baseline["scope"] == {
        "targets": ["apps", "core", "shared"],
        "exclude": r"(^|[\\/])(tests|migrations)([\\/]|$)",
        "follow_imports": "skip",
    }
    governed_error_count = sum(
        sum(error_counts.values()) for error_counts in full_baseline["modules"].values()
    )
    assert full_baseline["summary"]["errors"] == governed_error_count
    assert full_baseline["summary"]["files_with_errors"] == len(full_baseline["modules"])

    nightly_text = (REPO_ROOT / ".github" / "workflows" / "nightly-tests.yml").read_text(
        encoding="utf-8"
    )
    assert "python scripts/check_mypy_debt_ceiling.py" in nightly_text


def test_fast_feedback_installs_node_playwright_browser() -> None:
    """Keep Node browser tests runnable on a clean GitHub Actions runner."""

    workflow_text = (REPO_ROOT / ".github" / "workflows" / "ci-fast-feedback.yml").read_text(
        encoding="utf-8"
    )
    verify_step = workflow_text.split("- name: Verify TUI Runtime bundles", maxsplit=1)[1].split(
        "- name:", maxsplit=1
    )[0]

    install_position = verify_step.index("npx playwright install chromium")
    assert "npx playwright install --with-deps chromium" not in verify_step
    test_position = verify_step.index("npm run test:tui-js")
    assert install_position < test_position


def test_postgres_current_data_contracts_run_with_migration_seed_evidence() -> None:
    """Recreate a migrated PostgreSQL test DB and preserve it for later evidence steps."""

    workflow_text = (REPO_ROOT / ".github" / "workflows" / "nightly-tests.yml").read_text(
        encoding="utf-8"
    )
    current_data_step = workflow_text.split(
        "- name: Run current-data contract manifest on PostgreSQL", maxsplit=1
    )[1].split("- name:", maxsplit=1)[0]

    assert "python scripts/run_current_data_contract_tests.py" in current_data_step
    assert "--pytest-arg=--create-db" in current_data_step
    assert "--pytest-arg=--reuse-db" in current_data_step
    assert "--pytest-arg=--no-migrations" not in current_data_step


def test_fast_feedback_production_check_has_postgres_configuration() -> None:
    """Keep production checks aligned with the mandatory PostgreSQL policy."""

    workflow_text = (REPO_ROOT / ".github" / "workflows" / "ci-fast-feedback.yml").read_text(
        encoding="utf-8"
    )
    production_step = workflow_text.split("- name: Production static sanity check", maxsplit=1)[1]

    assert "DJANGO_SETTINGS_MODULE: core.settings.production" in production_step
    assert "DATABASE_URL: postgresql://" in production_step
