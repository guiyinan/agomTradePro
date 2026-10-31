"""An explicit test database identity is required before guarded PG cleanup."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from django.core.exceptions import ImproperlyConfigured

SETTINGS_PATH = Path(__file__).resolve().parents[3] / "core/settings/critical_postgres_test.py"
WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github/workflows/nightly-tests.yml"


def _load_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str | None,
    engine: str = "django.db.backends.postgresql",
    source: str = "critical_source",
) -> dict[str, Any]:
    """Execute the real adapter with an isolated inherited settings module."""
    inherited = ModuleType("core.settings.development")
    vars(inherited)["DATABASES"] = {"default": {"ENGINE": engine, "NAME": source}}
    monkeypatch.setitem(sys.modules, inherited.__name__, inherited)
    if name is None:
        monkeypatch.delenv("AGOM_CRITICAL_TEST_DB_NAME", raising=False)
    else:
        monkeypatch.setenv("AGOM_CRITICAL_TEST_DB_NAME", name)
    return runpy.run_path(
        str(SETTINGS_PATH), run_name="core.settings._critical_postgres_test_probe"
    )


def test_explicit_postgres_test_identity_keeps_source_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter identifies the disposable test target without switching NAME."""
    values = _load_settings(monkeypatch, name="test_critical_source")

    assert values["DATABASES"]["default"] == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "critical_source",
        "TEST": {"NAME": "test_critical_source"},
    }


@pytest.mark.parametrize("name", [None, "", " ", " test_critical_source", "test_critical_source "])
def test_missing_or_ambiguous_test_name_fails_before_database_use(
    monkeypatch: pytest.MonkeyPatch,
    name: str | None,
) -> None:
    """A test name is never inferred from a missing or whitespace input."""
    with pytest.raises(ImproperlyConfigured, match="must name the isolated"):
        _load_settings(monkeypatch, name=name)


def test_test_database_cannot_equal_source_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly repeated source identity remains a configuration error."""
    with pytest.raises(ImproperlyConfigured, match="must differ from the source"):
        _load_settings(monkeypatch, name="critical_source")


def test_non_postgres_engine_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guarded PostgreSQL job cannot silently run with SQLite settings."""
    with pytest.raises(ImproperlyConfigured, match="require PostgreSQL"):
        _load_settings(
            monkeypatch,
            name="test_critical_source",
            engine="django.db.backends.sqlite3",
        )


def test_critical_step_binds_the_precreated_database() -> None:
    """The guarded test identity matches the clone created by the same job."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["critical-postgres"]["steps"]
    prepare = next(
        step
        for step in steps
        if step.get("name") == "Prepare pre-migrated PostgreSQL test database"
    )
    critical = next(
        step for step in steps if step.get("name") == "Run PostgreSQL critical reliability tests"
    )
    assert critical["env"]["DJANGO_SETTINGS_MODULE"] == "core.settings.critical_postgres_test"
    test_name = critical["env"]["AGOM_CRITICAL_TEST_DB_NAME"]
    assert test_name == "test_agomtradepro_critical"
    assert f"CREATE DATABASE {test_name} TEMPLATE " in prepare["run"]

    for step_name, expected_name in (
        ("Run PostgreSQL migration integrity tests", test_name),
        (
            "Run full-registry transaction cleanup regressions on PostgreSQL",
            "test_agomtradepro_critical_aud05_flush",
        ),
        (
            "Run current-data contract manifest on PostgreSQL",
            "test_agomtradepro_critical_aud05",
        ),
        (
            "Run backfill coverage and retention control-plane evidence on PostgreSQL",
            test_name,
        ),
        ("Run PostgreSQL retention and Qlib admission concurrency evidence", test_name),
    ):
        step = next(step for step in steps if step.get("name") == step_name)
        assert step["env"]["DJANGO_SETTINGS_MODULE"] == ("core.settings.critical_postgres_test")
        assert step["env"]["AGOM_CRITICAL_TEST_DB_NAME"] == expected_name
        if "aud05" in expected_name:
            assert step["env"]["AGOM_AUD05_PG_CONCURRENCY_EVIDENCE"] == "1"
            assert "--create-db" in step["run"]

    browser_install_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Install Python browser runtime for current-data contracts"
    )
    current_data_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Run current-data contract manifest on PostgreSQL"
    )
    cleanup_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Run full-registry transaction cleanup regressions on PostgreSQL"
    )
    assert browser_install_index < cleanup_index < current_data_index
    assert (
        steps[browser_install_index]["run"].strip()
        == "python -m playwright install --with-deps chromium"
    )

    cleanup = next(
        step
        for step in steps
        if step.get("name") == "Run full-registry transaction cleanup regressions on PostgreSQL"
    )
    cleanup_run = cleanup["run"]
    assert cleanup["timeout-minutes"] == "10"
    assert cleanup["env"]["PYTHONFAULTHANDLER"] == "1"
    assert "-o faulthandler_timeout=0" in cleanup_run
    assert "--timeout=300" in cleanup_run
    assert "--timeout-method=thread" in cleanup_run
    assert "--create-db --reuse-db --maxfail=1" in cleanup_run
    assert "authority-generation-flush.xml" in cleanup_run
    cleanup_test_files = tuple(
        line.strip().removesuffix("\\").strip()
        for line in cleanup_run.splitlines()
        if line.strip().startswith("tests/")
    )
    assert cleanup_test_files == (
        "tests/component/data_center/test_audited_price_sync_transaction.py",
        "tests/component/data_center/test_audited_macro_sync_transaction.py",
        "tests/component/config_center/test_aud05_atomic_activation.py",
        "tests/component/data_center/test_audited_quote_sync_transaction.py",
        "tests/component/data_center/test_current_publication_staging.py",
        "tests/component/data_center/test_financial_source_time_audit_claim.py",
    )


def test_nightly_component_step_keeps_full_suite_and_fixed_two_worker_contract() -> None:
    """The component suite parallelizes within its original bounded nightly step."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["nightly"]["steps"]
    component = next(step for step in steps if step.get("name") == "Run Component Tests")
    run = component["run"]

    assert component["timeout-minutes"] == "45"
    assert "python -m pytest tests/component/ -vv -ra" in run
    assert "-n 2" in run
    assert "--dist=load" in run
    assert "--max-worker-restart=0" in run
    assert "-p no:cacheprovider" in run
    assert "-o faulthandler_timeout=0" in run
    assert "--timeout=300" in run
    assert "--timeout-method=thread" in run
    assert "--durations=20" in run
    assert "--cov" in run
    assert "--cov-config=.coveragerc" in run
    assert "--cov-append" in run
    assert "--cov-report=term-missing" in run
    assert "--junitxml=reports/quality/nightly-component.xml" in run
    assert "--no-migrations" not in run
    assert "--dist=loadfile" not in run


def test_nightly_api_migrations_keep_bounded_xdist_and_junit_contract() -> None:
    """API/migration parallelism stays inside its current budget and quality artifact."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["nightly"]["steps"]
    api_migrations = next(
        step for step in steps if step.get("name") == "Run API And Migration Tests"
    )
    run = api_migrations["run"]

    assert api_migrations["timeout-minutes"] == "35"
    pytest_django = run.find("-p django")
    api_plugin = run.find("-p tests.support.api_migrations_xdist")
    assert pytest_django >= 0 and api_plugin > pytest_django
    assert "-p pytest_django.plugin" not in run
    assert "tests/api/ tests/migrations/ -v -ra" in run
    assert "-n 2" in run
    assert "--dist=load" in run
    assert "--max-worker-restart=0" in run
    assert "-p no:cacheprovider" in run
    assert "-o faulthandler_timeout=180" in run
    assert "--timeout=300" in run
    assert "--timeout-method=thread" in run
    assert "--durations=20" in run
    assert "--cov" in run
    assert "--cov-config=.coveragerc" in run
    assert "--cov-append" in run
    assert "--cov-report=term-missing" in run
    assert "--junitxml=reports/quality/nightly-api-migrations.xml" in run
    assert "--no-migrations" not in run
    assert "--dist=loadfile" not in run

    quality_upload = next(step for step in steps if step.get("name") == "Upload Quality Report")
    assert quality_upload["with"]["path"] == "reports/quality/"


def test_data02_closure_step_uses_an_isolated_loopback_database_and_required_junit() -> None:
    """DATA-02 PostgreSQL evidence runs without the migrated critical database."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["critical-postgres"]["steps"]
    step = next(
        step
        for step in steps
        if step.get("name") == "Run DATA-02 closure evidence on isolated PostgreSQL"
    )
    prepare_index = next(
        index
        for index, candidate in enumerate(steps)
        if candidate.get("name") == "Prepare pre-migrated PostgreSQL test database"
    )
    data02_index = steps.index(step)
    critical_index = next(
        index
        for index, candidate in enumerate(steps)
        if candidate.get("name") == "Run PostgreSQL critical reliability tests"
    )
    run = step["run"]

    assert step["timeout-minutes"] == "10"
    assert prepare_index < data02_index < critical_index
    assert step["env"]["DJANGO_SETTINGS_MODULE"] == "core.settings.critical_postgres_test"
    assert step["env"]["AGOM_CRITICAL_TEST_DB_NAME"] == "test_agomtradepro_critical"
    assert step["env"]["AGOM_DATA02_POSTGRES_TEST"] == "1"
    assert step["env"]["AGOM_DATA02_SCALE_TEST"] == "1"
    assert "127.0.0.1:5432/agomtradepro_critical" in run
    assert "CREATE DATABASE data02_closure_test TEMPLATE template0 OWNER agomtradepro" in run
    assert '"${DATABASE_URL%/*}/data02_closure_test"' in run
    assert "tests/component/data_center/test_data02_postgres_closure.py" in run
    assert "--timeout=300" in run
    assert "--timeout-method=thread" in run
    assert "--junitxml=reports/quality/postgres/data02-closure.xml" in run
    assert "required_tests" in run
    assert "data_center.core_current_publication_rebuild" in run
    assert '("skipped", "failure", "error")' in run
    assert "--create-db" not in run
    assert "--reuse-db" not in run
    assert "--no-migrations" not in run

    quality_upload = next(
        candidate
        for candidate in steps
        if candidate.get("name") == "Upload PostgreSQL backup and restore evidence"
    )
    assert "reports/quality/postgres/" in quality_upload["with"]["path"]
