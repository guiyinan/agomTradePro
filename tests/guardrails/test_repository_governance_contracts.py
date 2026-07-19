"""Repository-level contracts for documentation inventory and generated artifacts."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_agents_app_inventory_matches_machine_governance_source() -> None:
    """Keep the human-facing AGENTS module tree aligned with the machine baseline."""

    agents_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    apps_tree = agents_text.split("├── apps/", maxsplit=1)[1].split("├── shared/", maxsplit=1)[0]
    documented_modules = set(re.findall(r"│   [├└]── ([a-z][a-z0-9_]*)/", apps_tree))
    baseline = json.loads(
        (REPO_ROOT / "governance" / "governance_baseline.json").read_text(encoding="utf-8")
    )
    expected_modules = set(baseline["module_shape_minimums"])

    assert documented_modules == expected_modules
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


def test_mypy_debt_budgets_only_shrink() -> None:
    """Prevent resolved modules and errors from returning to broad debt buckets."""

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
    baseline_error_count = sum(
        sum(error_counts.values()) for error_counts in error_baseline.values()
    )
    assert baseline_error_count == 0
    assert error_baseline == {}
    assert "apps/task_monitor/application/interface_services.py" not in error_baseline


def test_fast_feedback_installs_node_playwright_browser() -> None:
    """Keep Node browser tests runnable on a clean GitHub Actions runner."""

    workflow_text = (REPO_ROOT / ".github" / "workflows" / "ci-fast-feedback.yml").read_text(
        encoding="utf-8"
    )
    verify_step = workflow_text.split("- name: Verify TUI Runtime bundles", maxsplit=1)[1].split(
        "- name:", maxsplit=1
    )[0]

    install_position = verify_step.index("npx playwright install --with-deps chromium")
    test_position = verify_step.index("npm run test:tui-js")
    assert install_position < test_position


def test_fast_feedback_production_check_has_postgres_configuration() -> None:
    """Keep production checks aligned with the mandatory PostgreSQL policy."""

    workflow_text = (REPO_ROOT / ".github" / "workflows" / "ci-fast-feedback.yml").read_text(
        encoding="utf-8"
    )
    production_step = workflow_text.split("- name: Production static sanity check", maxsplit=1)[1]

    assert "DJANGO_SETTINGS_MODULE: core.settings.production" in production_step
    assert "DATABASE_URL: postgresql://" in production_step
