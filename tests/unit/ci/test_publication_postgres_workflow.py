"""Publication PostgreSQL evidence gate must follow the shared test inventory."""

from __future__ import annotations

import ast
import copy
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github/workflows/ci-publication-postgres.yml"
VALIDATOR_PATH = ROOT / "scripts/validate_release_rehearsal.py"
EVIDENCE_ARTIFACT = "publication-postgres-evidence"
FLUSH_MODULES = (
    "tests/component/data_center/test_audited_price_sync_transaction.py",
    "tests/component/data_center/test_audited_macro_sync_transaction.py",
    "tests/component/config_center/test_aud05_atomic_activation.py",
    "tests/component/data_center/test_audited_quote_sync_transaction.py",
    "tests/component/data_center/test_current_publication_staging.py",
    "tests/component/data_center/test_financial_source_time_audit_claim.py",
)
FLUSH_SUPPORT = "tests.support.account_authority_generation_flush"
FLUSH_FIXTURE = "preserve_account_authority_generation"
CRITICAL_SETTINGS = "core.settings.critical_postgres_test"


def _assert_flush_fixture_loaded(source: str) -> None:
    """Require an actual unshadowed module import, not a comment or nested import."""
    module = ast.parse(source)
    names: set[str] = set()
    for statement in module.body:
        if isinstance(statement, ast.ImportFrom) and statement.module == FLUSH_SUPPORT:
            names.update(
                alias.asname or alias.name
                for alias in statement.names
                if alias.name == FLUSH_FIXTURE
            )
            continue
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.discard(statement.name)
        else:
            for node in ast.walk(statement):
                if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    names.discard(node.id)
                elif isinstance(node, ast.alias):
                    names.discard(node.asname or node.name.split(".")[0])
    assert names, "cleanup fixture must be loaded at module scope and remain unshadowed"


def _assert_pg_entry_identity(workflow: dict[str, Any]) -> int:
    """Check effective configuration at every guarded PG caller in this workflow."""
    checked = 0
    for job_name, job in workflow["jobs"].items():
        job_env = {**workflow.get("env", {}), **job.get("env", {})}
        for step in job.get("steps", []):
            run = step.get("run", "")
            relevant = any(path in run for path in FLUSH_MODULES) or (
                "scripts/run_current_data_contract_tests.py" in run
            )
            env = {**job_env, **step.get("env", {})}
            is_postgres = (
                "postgres" in job_name.lower()
                or "postgresql" in step.get("name", "").lower()
                or env.get("DATABASE_URL", "").startswith(("postgresql:", "postgres:"))
            )
            if not relevant or not is_postgres:
                continue
            label = f"{job_name}/{step.get('name', '<unnamed>')}"
            assert env.get("DJANGO_SETTINGS_MODULE") == CRITICAL_SETTINGS, label
            cli_settings = re.findall(r"--ds(?:=|\s+)([\w.]+)", run)
            assert all(value == CRITICAL_SETTINGS for value in cli_settings), label
            test_name = env.get("AGOM_CRITICAL_TEST_DB_NAME", "")
            assert test_name and test_name.strip() == test_name, label
            source_name = urlsplit(env.get("DATABASE_URL", "")).path.lstrip("/")
            assert not source_name or test_name != source_name, label
            checked += 1
    return checked


def test_guarded_transaction_modules_load_the_real_autouse_cleanup_fixture() -> None:
    """All six real module entrypoints load the module-autouse cleanup protection."""
    for relative in FLUSH_MODULES:
        _assert_flush_fixture_loaded((ROOT / relative).read_text(encoding="utf-8"))
    support = ast.parse(
        (ROOT / "tests/support/account_authority_generation_flush.py").read_text(encoding="utf-8")
    )
    fixture = next(
        node
        for node in support.body
        if isinstance(node, ast.FunctionDef) and node.name == FLUSH_FIXTURE
    )
    decorators = [
        decorator
        for decorator in fixture.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "pytest"
        and decorator.func.attr == "fixture"
    ]
    assert len(decorators) == 1
    options = {keyword.arg: ast.literal_eval(keyword.value) for keyword in decorators[0].keywords}
    assert options["autouse"] is True
    assert options["scope"] == "module"


@pytest.mark.parametrize("relative", FLUSH_MODULES)
def test_removing_a_real_cleanup_import_fails_before_database_tests(relative: str) -> None:
    """Reintroduce the omitted-import defect in memory and reject it without Django."""
    module = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    removed = [
        node
        for node in module.body
        if isinstance(node, ast.ImportFrom) and node.module == FLUSH_SUPPORT
    ]
    assert removed, "negative control must remove a real import"
    module.body = [node for node in module.body if node not in removed]
    with pytest.raises(AssertionError, match="cleanup fixture"):
        _assert_flush_fixture_loaded(ast.unparse(module))


@pytest.mark.parametrize(
    "source",
    [
        f"def unused():\n    from {FLUSH_SUPPORT} import {FLUSH_FIXTURE}\n",
        f"from {FLUSH_SUPPORT} import {FLUSH_FIXTURE}\n{FLUSH_FIXTURE} = None\n",
        f"# from {FLUSH_SUPPORT} import {FLUSH_FIXTURE}\n",
    ],
)
def test_unloaded_or_shadowed_fixture_name_is_not_accepted(source: str) -> None:
    """A familiar identifier alone cannot satisfy the entrypoint wiring check."""
    with pytest.raises(AssertionError, match="cleanup fixture"):
        _assert_flush_fixture_loaded(source)


def test_all_guarded_postgres_workflow_callers_bind_isolated_identity() -> None:
    """Check both shared nightly and standalone Publication callers before PG runs."""
    for filename, minimum_callers in (
        ("nightly-tests.yml", 2),
        ("ci-publication-postgres.yml", 1),
    ):
        workflow = yaml.load(
            (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        assert _assert_pg_entry_identity(workflow) >= minimum_callers
        if filename == "nightly-tests.yml":
            step = next(
                step
                for job in workflow["jobs"].values()
                for step in job.get("steps", [])
                if step.get("name")
                == "Run full-registry transaction cleanup regressions on PostgreSQL"
            )
            assert all(relative in step["run"] for relative in FLUSH_MODULES)
            assert (
                "--junitxml=reports/quality/postgres/authority-generation-flush.xml" in step["run"]
            )
            assert "authority_generation_flushes" in step["run"]


def _assert_preflight_order(
    workflow: dict[str, Any], job_name: str, first_database_step: str
) -> None:
    """Require the existing contract file to execute before guarded database work."""
    steps = workflow["jobs"][job_name]["steps"]
    preflight_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Check PostgreSQL test entrypoint contracts"
    )
    preflight = steps[preflight_index]
    assert preflight.get("env", {}).get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1"
    assert "tests/unit/ci/test_publication_postgres_workflow.py" in preflight["run"]
    assert "-c /dev/null" in preflight["run"]
    assert "--confcutdir=tests/unit/ci" in preflight["run"]
    assert "-p no:cacheprovider" in preflight["run"]
    assert "if" not in preflight
    assert preflight.get("continue-on-error", "false") == "false"
    first_database_work = next(
        index for index, step in enumerate(steps) if step.get("name") == first_database_step
    )
    assert preflight_index < first_database_work, "contract preflight must precede PG work"


@pytest.mark.parametrize(
    ("filename", "job_name", "first_database_step"),
    [
        (
            "ci-publication-postgres.yml",
            "publication-postgres",
            "Prepare isolated authority contract database",
        ),
        ("nightly-tests.yml", "critical-postgres", "Record PostgreSQL runtime versions"),
    ],
)
def test_workflows_run_contract_preflight_before_database_work(
    filename: str, job_name: str, first_database_step: str
) -> None:
    """The fast static contract is a default step, not only a manually runnable test."""
    workflow = yaml.load(
        (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    _assert_preflight_order(workflow, job_name, first_database_step)
    if filename != "ci-publication-postgres.yml":
        return
    required_paths = {
        "tests/component/config_center/test_aud05_atomic_activation.py",
        "tests/support/account_authority_generation_flush.py",
        "tests/unit/ci/test_publication_postgres_workflow.py",
        "core/settings/critical_postgres_test.py",
        ".github/workflows/nightly-tests.yml",
    }
    for event in ("push", "pull_request"):
        assert required_paths <= set(workflow["on"][event]["paths"])


@pytest.mark.parametrize(
    ("filename", "job_name", "first_database_step"),
    [
        (
            "ci-publication-postgres.yml",
            "publication-postgres",
            "Prepare isolated authority contract database",
        ),
        ("nightly-tests.yml", "critical-postgres", "Record PostgreSQL runtime versions"),
    ],
)
def test_moving_preflight_after_database_work_is_rejected(
    filename: str, job_name: str, first_database_step: str
) -> None:
    """Reintroducing a late check cannot silently consume a PG validation window."""
    workflow = yaml.load(
        (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    mutated = copy.deepcopy(workflow)
    steps = mutated["jobs"][job_name]["steps"]
    preflight = next(
        step for step in steps if step.get("name") == "Check PostgreSQL test entrypoint contracts"
    )
    steps.remove(preflight)
    steps.append(preflight)
    with pytest.raises(AssertionError, match="must precede PG"):
        _assert_preflight_order(mutated, job_name, first_database_step)


@pytest.mark.parametrize(
    "defect", ["missing-name", "source-name", "wrong-settings", "cli-override"]
)
def test_standalone_publication_identity_regression_is_rejected(defect: str) -> None:
    """Mutate the real caller, including its CLI override, and fail before a DB launch."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    mutated = copy.deepcopy(workflow)
    step = next(
        step
        for step in mutated["jobs"]["publication-postgres"]["steps"]
        if step.get("name") == "Exercise PostgreSQL control plane and valuation lineage staging"
    )
    if defect == "missing-name":
        del step["env"]["AGOM_CRITICAL_TEST_DB_NAME"]
    elif defect == "source-name":
        step["env"]["AGOM_CRITICAL_TEST_DB_NAME"] = urlsplit(
            step["env"]["DATABASE_URL"]
        ).path.lstrip("/")
    elif defect == "wrong-settings":
        step["env"]["DJANGO_SETTINGS_MODULE"] = "core.settings.development"
    else:
        step["run"] = step["run"].replace(
            "--ds=core.settings.critical_postgres_test", "--ds=core.settings.development"
        )
    assert mutated != workflow, "negative control must change the real workflow"
    with pytest.raises(AssertionError, match="publication-postgres/"):
        _assert_pg_entry_identity(mutated)


def _required_postgresql_tests() -> tuple[str, ...]:
    """Read the validator's literal inventory without importing an operational script."""

    module = ast.parse(VALIDATOR_PATH.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "REQUIRED_POSTGRESQL_TESTS"
            for target in node.targets
        )
    )
    value = ast.literal_eval(assignment.value)
    assert isinstance(value, tuple)
    assert all(isinstance(item, str) for item in value)
    return value


def _required_junit_files() -> set[str]:
    """Read the required JUnit filename inventory without importing operational code."""
    module = ast.parse(VALIDATOR_PATH.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "REQUIRED_JUNIT_FILES"
            for target in node.targets
        )
    )
    value = ast.literal_eval(assignment.value)
    assert isinstance(value, set)
    assert all(isinstance(item, str) for item in value)
    return value


def _evidence_gate_source() -> tuple[str, set[str]]:
    """Read the embedded validator and the official artifact's JUnit file list."""

    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["publication-postgres"]["steps"]
    evidence_step = next(
        step
        for step in steps
        if step.get("name") == "Reject missing or skipped PostgreSQL evidence"
    )
    run_script = evidence_step["run"]
    python_source = run_script.split("python - <<'PY'\n", maxsplit=1)[1].rsplit("\nPY", maxsplit=1)[
        0
    ]

    artifact_step = next(
        step
        for step in steps
        if step.get("uses") == "actions/upload-artifact@v4"
        and step.get("with", {}).get("name") == EVIDENCE_ARTIFACT
    )
    artifact_junit_files = {
        line.strip()
        for line in artifact_step["with"]["path"].splitlines()
        if line.strip().endswith(".xml")
    }
    return python_source, artifact_junit_files


def test_postgres_evidence_gate_uses_required_inventory_without_suite_counts() -> None:
    """Every retained JUnit suite is checked against the shared required identities."""

    python_source, artifact_junit_files = _evidence_gate_source()
    ast.parse(python_source)

    assert (
        "from scripts.validate_release_rehearsal import REQUIRED_POSTGRESQL_TESTS" in python_source
    )
    assert "set(REQUIRED_POSTGRESQL_TESTS) - observed_tests" in python_source
    assert "path.is_file() and path.stat().st_size > 0" in python_source
    assert "assert file_cases" in python_source
    assert "case.find('skipped') is None" in python_source
    assert "case.find('failure') is None and case.find('error') is None" in python_source
    assert "case.get('classname')" in python_source
    assert "case.get('name')" in python_source

    assert re.search(r"\blen\s*\([^)]*cases[^)]*\)\s*==\s*\d+\b", python_source) is None
    assert artifact_junit_files
    assert all(filename in python_source for filename in artifact_junit_files)


def test_postgres_evidence_gate_accepts_additional_testcases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """New observed JUnit cases pass when all shared required identities are present."""

    python_source, artifact_junit_files = _evidence_gate_source()
    extra_case = "tests.extra.test_future_publication_case::test_added_case"
    required_postgresql_tests = _required_postgresql_tests()

    def testcase(identity: str) -> str:
        classname, name = identity.rsplit("::", maxsplit=1)
        return f'<testcase classname="{classname}" name="{name}" />'

    for filename in artifact_junit_files:
        identities = (
            (*required_postgresql_tests, extra_case)
            if filename == "publication-postgres.xml"
            else (extra_case,)
        )
        case_elements = "".join(testcase(identity) for identity in identities)
        (tmp_path / filename).write_text(
            f"<testsuite>{case_elements}</testsuite>",
            encoding="utf-8",
        )
    (tmp_path / "sqlite-snapshot-rehearsal-report.json").write_text(
        json.dumps(
            {
                "outcome": "success",
                "fixture_row_count": 1,
                "source_serialized_row_count": 1,
                "source_row_count": 1,
                "mismatches": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    exec(compile(python_source, "publication-postgres-evidence-gate", "exec"), {})


def test_publication_workflow_keeps_standard_dispatch_behavior() -> None:
    """The ordinary publication workflow keeps its dispatch and concurrency contract."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    events = workflow["on"]
    assert "workflow_dispatch" in events
    assert events["workflow_dispatch"] == ""
    assert set(workflow["jobs"]) == {"publication-postgres"}
    assert "if" not in workflow["jobs"]["publication-postgres"]
    assert workflow["concurrency"]["group"] == (
        "publication-postgres-${{ github.workflow }}-${{ github.ref }}"
    )
    assert workflow["concurrency"]["cancel-in-progress"] == "true"


EVID06_AUTHORITY_NODEIDS = (
    "tests/component/account/test_current_account_ownership_postgres.py::test_live_owner_change_missing_and_inactive_never_fall_back",
    "tests/component/account/test_current_account_ownership_postgres.py::test_transaction_isolation_source_clocks_and_lock_contention",
    "tests/component/account/test_owner_tenant_authority_v2_composition.py::test_new_actual_session_after_assignment_expiry_reads_decision_then_revokes",
    "tests/component/account/test_owner_tenant_physical_row_v2.py::test_cross_app_reader_preserves_live_source_and_exact_alias",
    "tests/component/account/test_account_owner_assignment_evidence_v4_composition.py::test_facade_register_approve_replay_and_current_use_one_alias",
    "tests/component/account/test_account_owner_assignment_evidence_v4_composition.py::test_facade_outer_rollback_and_committed_policy_revocation_fail_closed",
    "tests/component/account/test_account_owner_assignment_evidence_v4_repository.py::test_root_mapping_cas_and_expired_head_never_allow_second_root",
    "tests/component/account/test_account_owner_assignment_evidence_v4_repository.py::test_committed_policy_revocation_rejects_new_approval_without_erasing_subject",
    "tests/component/account/test_account_owner_assignment_provenance_receipt_v4_repository.py::test_parent_tamper_breaks_even_unrelated_selector",
    "tests/component/account/test_receipt_v4_locked_composition.py::test_locked_replay_rechecks_committed_policy_revocation",
    "tests/component/account/test_receipt_v4_parent_row_locks.py::test_actor_and_binding_for_update_exclude_issuance_and_replay",
    "tests/component/account/test_single_owner_policy_actor_composition.py::test_real_actor_and_policy_read_then_revocation_rejects_the_same_binding",
    "tests/component/research/test_owner_tenant_evidence_scope_v2_postgres.py::test_actual_current_owner_reads_historical_evidence_and_live_owner_loss_denies",
    "tests/component/research/test_owner_tenant_evidence_scope_v3_postgres.py::test_authenticated_admin_materializes_owner_scope_and_denies_substitution",
)

FINANCIAL_SLICE_NODEIDS = (
    "tests/unit/data_center/test_akshare_financial_capture.py::test_akshare_financial_capture_retains_independent_exact_body_pair",
    "tests/unit/data_center/test_akshare_financial_capture.py::test_akshare_adapter_builds_typed_facts_from_two_retained_raw_bodies",
    "tests/unit/data_center/test_akshare_financial_capture.py::test_akshare_financial_capture_provider_failure_does_not_retain_any_artifact",
    "tests/unit/data_center/test_akshare_financial_capture.py::test_akshare_financial_slice_sync_uses_exact_approved_route_and_one_atomic_write",
    "tests/unit/data_center/test_akshare_financial_capture.py::test_akshare_financial_slice_sync_evidence_rejection_writes_zero_facts",
    "tests/unit/data_center/test_akshare_financial_capture.py::test_akshare_financial_slice_sync_scale_gate_counts_two_requests_per_pair",
    "tests/unit/data_center/test_akshare_financial_capture.py::test_akshare_financial_slice_sync_partial_provider_failure_writes_zero_facts",
    "tests/unit/data_center/test_akshare_financial_capture.py::test_akshare_financial_slice_budget_is_contract_bound_and_fails_closed",
    "tests/unit/data_center/test_financial_publication_capacity_workflow.py::test_django_checkpoint_repository_resumes_after_workflow_reconstruction",
    "tests/unit/data_center/test_financial_publication_capacity_workflow.py::test_django_checkpoint_repository_consumes_receipt_once_even_after_reapproval",
    "tests/unit/data_center/test_financial_publication_capacity_workflow.py::test_django_concurrent_duplicate_observes_live_claim_without_database_mutation",
    "tests/unit/data_center/test_financial_capacity_manifest.py::test_formal_manifest_uses_asset_subquery_for_5572_active_assets",
)

AI_PROVIDER_MIGRATION_FILE = "tests/component/test_ai_provider_plaintext_removal_migration.py"
AI_PROVIDER_MIGRATION_REQUIRED_IDENTITIES = (
    "tests.component.test_ai_provider_plaintext_removal_migration::test_failed_removal_preserves_schema_and_credential_values[plaintext]",
    "tests.component.test_ai_provider_plaintext_removal_migration::test_failed_removal_preserves_schema_and_credential_values[mixed]",
    "tests.component.test_ai_provider_plaintext_removal_migration::test_failed_removal_preserves_schema_and_credential_values[unprefixed]",
    "tests.component.test_ai_provider_plaintext_removal_migration::test_failed_removal_preserves_schema_and_credential_values[wrong-key]",
    "tests.component.test_ai_provider_plaintext_removal_migration::test_failed_removal_preserves_schema_and_credential_values[corrupt]",
    "tests.component.test_ai_provider_plaintext_removal_migration::test_failed_removal_preserves_schema_and_credential_values[empty-decryption]",
    "tests.component.test_ai_provider_plaintext_removal_migration::test_failed_removal_preserves_schema_and_credential_values[missing-key]",
    "tests.component.test_ai_provider_plaintext_removal_migration::test_empty_provider_state_migrates_without_encryption_key[absent-row]",
    "tests.component.test_ai_provider_plaintext_removal_migration::test_empty_provider_state_migrates_without_encryption_key[empty-row]",
    "tests.component.test_ai_provider_plaintext_removal_migration::test_valid_removal_is_idempotent_and_preserves_decryptable_ciphertext",
)
AI_PROVIDER_MIGRATION_JUNIT = "ai-provider-plaintext-removal-postgres.xml"


def _pytest_nodeids(command: str) -> tuple[str, ...]:
    """Return explicit file::test selectors from a workflow step command."""

    return tuple(
        re.findall(
            r"(tests/(?:component|unit)/[A-Za-z0-9_./-]+::test_[A-Za-z0-9_]+)",
            command,
        )
    )


def test_financial_slice_step_uses_the_strict_isolated_postgres_settings() -> None:
    """The slice suite must use the guarded TEST.NAME and keep its exact selection."""

    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["publication-postgres"]["steps"]
    step = next(
        item
        for item in steps
        if item.get("name") == "Exercise governed AKShare financial capture and slice sync"
    )

    assert _pytest_nodeids(step["run"]) == FINANCIAL_SLICE_NODEIDS
    assert step["env"]["DJANGO_SETTINGS_MODULE"] == "core.settings.critical_postgres_test"
    assert step["env"]["AGOM_CRITICAL_TEST_DB_NAME"] == "test_agom_release_rehearsal_ci"
    assert "--ds=core.settings.critical_postgres_test" in step["run"]
    assert "--create-db" in step["run"]


def test_ai_provider_plaintext_migration_step_is_a_required_postgres_gate() -> None:
    """The migration preservation and success cases run under isolated PostgreSQL."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    events = workflow["on"]
    for event_name in ("pull_request", "push"):
        paths = events[event_name]["paths"]
        assert "apps/ai_provider/migrations/**" in paths
        assert "apps/ai_provider/infrastructure/models.py" in paths
        assert AI_PROVIDER_MIGRATION_FILE in paths
        assert "apps/ai_provider/**" not in paths

    steps = workflow["jobs"]["publication-postgres"]["steps"]
    step = next(
        item
        for item in steps
        if item.get("name") == "Exercise AI-provider plaintext removal on PostgreSQL"
    )
    command = step["run"].split()
    assert tuple(command[:4]) == (
        "python",
        "-m",
        "pytest",
        AI_PROVIDER_MIGRATION_FILE,
    )
    assert step["env"]["DJANGO_SETTINGS_MODULE"] == CRITICAL_SETTINGS
    assert step["env"]["AGOM_CRITICAL_TEST_DB_NAME"] == "test_ref06_ai_provider_migration"
    assert step["env"]["DATABASE_URL"].endswith("/agom_release_rehearsal_ci")
    assert "--ds=core.settings.critical_postgres_test" in step["run"]
    assert "--confcutdir=tests/component" in step["run"]
    assert "--create-db" in step["run"]
    assert "-o addopts=''" in step["run"]
    assert "--no-migrations" not in step["run"]
    assert f"--junitxml={AI_PROVIDER_MIGRATION_JUNIT}" in step["run"]
    assert set(AI_PROVIDER_MIGRATION_REQUIRED_IDENTITIES) <= set(_required_postgresql_tests())
    assert AI_PROVIDER_MIGRATION_JUNIT in _required_junit_files()
    _, artifact_junit_files = _evidence_gate_source()
    assert AI_PROVIDER_MIGRATION_JUNIT in artifact_junit_files


def test_ash05_hold_lease_rollback_runs_on_a_distinct_postgres_test_database() -> None:
    """The post-insert expiry counterexample must execute and retain non-skipped SQL evidence."""

    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["publication-postgres"]["steps"]
    step = next(
        item for item in steps if item.get("name") == "Exercise ASH-05 native hold lease rollback"
    )
    assert _pytest_nodeids(step["run"]) == (
        "tests/component/simulated_trading/test_transition_plan_execution_native.py::test_native_hold_rolls_back_when_plan_expires_after_insert_before_commit",
    )
    assert step["env"]["DATABASE_URL"].endswith("/agom_release_rehearsal_ci")
    assert step["env"]["AGOM_CRITICAL_TEST_DB_NAME"] == "ash05_lease_test"
    assert "--ds=core.settings.critical_postgres_test" in step["run"]
    assert "--confcutdir=tests/component" in step["run"]
    assert "--create-db" in step["run"]
    assert "--no-migrations" not in step["run"]
    assert "--junitxml=ash05-lease-postgres.xml" in step["run"]
    evidence_source, artifact_files = _evidence_gate_source()
    assert "'ash05-lease-postgres.xml'" in evidence_source
    assert "ash05-lease-postgres.xml" in artifact_files


def test_ash05_corporate_action_ledger_runs_on_isolated_migrated_postgres() -> None:
    """Run cash, grant and immutable tax evidence contracts on migrated PostgreSQL."""

    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["publication-postgres"]["steps"]
    step = next(
        item
        for item in steps
        if item.get("name") == "Exercise ASH-05 native corporate-action ledger"
    )
    assert _pytest_nodeids(step["run"]) == (
        "tests/component/simulated_trading/test_corporate_action_posting_postgres.py::test_postgres_concurrent_entitlement_replay_writes_one_receivable",
        "tests/component/simulated_trading/test_corporate_action_posting_postgres.py::test_postgres_payment_waits_for_szse_date_and_settles_exact_receivable",
        "tests/component/simulated_trading/test_corporate_action_posting_postgres.py::test_postgres_audited_cash_payment_commits_and_replays_with_one_audit_pair",
        "tests/component/simulated_trading/test_owner_granted_corporate_action_postgres.py::test_native_nonstaff_owner_stage_commits_exact_grant_audit_and_replays",
        "tests/component/simulated_trading/test_owner_granted_corporate_action_postgres.py::test_native_owner_withdrawal_blocks_stage_and_its_exact_replay",
        "tests/component/simulated_trading/test_owner_granted_corporate_action_postgres.py::test_native_owner_authority_failure_rolls_back_financial_audit_and_outbox",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_owner_consent_http_prepare_confirm_retry_and_readonly_withdraw",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_expired_grant_source_and_policy_can_still_prepare_exact_owner_withdrawal",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_rotated_issuer_key_does_not_prevent_owner_withdrawal_or_restore_permission",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_nonstaff_owner_consent_is_sealed_and_exact_retry_is_idempotent",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_missing_csrf_cannot_append_owner_grant",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_other_authenticated_user_cannot_consent_for_account",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_credential_revocation_before_commit_rolls_grant_back",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_read_only_owner_cannot_issue_service_write_grant",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_policy_or_source_change_cannot_be_signed_as_original_scope",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_read_only_owner_can_withdraw_after_policy_is_disabled",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_final_grant_expiry_check_runs_after_credential_revalidation",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_get_method_cannot_issue_consent_through_csrf_safe_method",
        "tests/component/account/test_simulated_corporate_action_write_issuance_postgres.py::test_native_issuer_holds_credential_and_owner_locks_until_commit",
        "tests/component/simulated_trading/test_corporate_action_posting_postgres.py::test_postgres_wrong_owner_account_or_security_scope_blocks_without_writes",
        "tests/component/account/test_simulated_corporate_action_write_grant_repository.py::test_repository_appends_replays_and_reads_one_exact_root",
        "tests/component/account/test_simulated_corporate_action_write_grant_repository.py::test_repository_successor_replaces_exact_head_without_old_version_fallback",
        "tests/component/account/test_simulated_corporate_action_write_grant_repository.py::test_repository_rejects_wrong_predecessor_and_preserves_the_old_head",
        "tests/component/account/test_simulated_corporate_action_write_grant_repository.py::test_repository_persists_a_separate_revocation_and_application_fails_closed",
        "tests/component/account/test_simulated_corporate_action_write_grant_repository.py::test_exact_selector_absence_does_not_fallback_to_an_available_root",
        "tests/component/account/test_simulated_corporate_action_write_grant_repository.py::test_scope_reader_preserves_owner_conflicts_and_never_falls_back_from_expired_head",
        "tests/component/account/test_simulated_corporate_action_write_grant_repository.py::test_orm_paths_cannot_bypass_the_repository_append_claim",
        "tests/component/data_center/test_szse_distribution_window_ingestion.py::test_multi_asset_cohort_commits_all_proofs_and_audits_at_shared_clocks",
        "tests/component/data_center/test_szse_distribution_window_ingestion.py::test_second_asset_audit_failure_rolls_back_entire_cohort",
        "tests/component/data_center/test_szse_distribution_window_ingestion.py::test_cohort_source_proof_at_lease_expiry_blocks_all_writes",
        "tests/component/data_center/test_statutory_source_repository.py::test_real_body_and_metadata_roundtrip_replays_exact_capture",
        "tests/component/data_center/test_statutory_source_repository.py::test_same_revision_changed_bytes_and_capture_facts_are_rejected",
        "tests/component/data_center/test_statutory_source_repository.py::test_metadata_append_requires_retained_matching_body_and_valid_clock",
        "tests/component/data_center/test_statutory_source_repository.py::test_bundle_preserves_both_hashes_and_requires_exact_retained_members",
        "tests/component/data_center/test_statutory_source_repository.py::test_bundle_member_failure_rolls_back_entire_metadata_batch",
        "tests/component/data_center/test_statutory_source_repository.py::test_orm_write_shortcuts_cannot_modify_source_facts",
        "tests/component/data_center/test_statutory_source_repository.py::test_postgres_native_mutation_guards_reject_even_raw_sql",
        "tests/component/data_center/test_statutory_source_repository.py::test_postgres_concurrent_revision_conflict_has_one_immutable_winner",
        "tests/component/data_center/test_statutory_source_repository.py::test_postgres_concurrent_capture_uuid_is_one_exact_replay",
        "tests/component/data_center/test_statutory_source_repository.py::test_postgres_unsupported_isolation_blocks_before_metadata_write",
        "tests/component/data_center/test_statutory_source_capture_composition.py::test_native_configured_document_retains_exact_server_observation",
        "tests/component/data_center/test_statutory_source_capture_composition.py::test_native_invalid_configuration_blocks_before_fetch",
        "tests/component/data_center/test_statutory_source_capture_composition.py::test_native_configuration_drift_preserves_unqualified_capture",
        "tests/component/data_center/test_statutory_source_capture_composition.py::test_native_old_observation_is_retained_but_rejected_for_capture_window",
        "tests/component/data_center/test_statutory_source_capture_composition.py::test_native_capture_rejects_ambient_transaction_before_network",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_assessment_and_retry_keep_one_header_allocation_audit_outbox_set",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_new_observation_and_nonce_return_first_persisted_manifest",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_changed_facts_require_explicit_successor_and_preserve_history",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_authority_change_at_exit_rolls_back_all_four_writes",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_late_outbox_verification_failure_rolls_back_all_writes",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_missing_original_outbox_is_blocked_without_repair",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_source_action_alias_cannot_create_another_tax_stream",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_concurrent_first_writes_keep_one_complete_set",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_always_guards_reject_raw_mutation_even_in_replica_mode",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_later_partial_sale_has_its_own_fifo_assessment_and_audit_stream",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_allocation_insert_failure_rolls_back_header_and_all_audit_writes",
        "tests/component/simulated_trading/test_corporate_action_tax_assessment_postgres.py::test_native_physical_account_owner_cannot_be_substituted_by_consistent_dtos",
        "tests/component/account/test_simulated_corporate_action_grant_capabilities_postgres.py::test_native_v1_roundtrip_keeps_cash_only_scope_and_null_v2_columns",
        "tests/component/account/test_simulated_corporate_action_grant_capabilities_postgres.py::test_native_v1_to_v2_selects_one_head_without_resurrecting_v1",
        "tests/component/account/test_simulated_corporate_action_grant_capabilities_postgres.py::test_native_v2_retry_narrowing_and_conflict_preserve_one_chain",
        "tests/component/account/test_simulated_corporate_action_grant_capabilities_postgres.py::test_native_v2_whole_revocation_retains_expired_exact_withdrawal_metadata",
        "tests/component/account/test_simulated_corporate_action_grant_capabilities_postgres.py::test_native_database_check_rejects_null_v2_terms",
        "tests/component/account/test_simulated_corporate_action_grant_capabilities_postgres.py::test_native_v2_cannot_downgrade_to_a_new_v1_head",
        "tests/component/account/test_simulated_corporate_action_grant_capabilities_postgres.py::test_native_concurrent_v2_root_replay_retains_one_record",
        "tests/component/account/test_simulated_corporate_action_capability_issuance_postgres.py::test_native_v2_session_owner_issues_only_selected_capability_and_retries_exactly",
        "tests/component/account/test_simulated_corporate_action_capability_issuance_postgres.py::test_native_v2_owner_upgrade_and_withdraw_survive_role_policy_and_key_loss",
        "tests/component/account/test_simulated_corporate_action_capability_issuance_postgres.py::test_native_v2_missing_csrf_or_another_owner_cannot_issue",
        "tests/component/account/test_simulated_corporate_action_capability_issuance_postgres.py::test_native_v2_changed_locked_policy_terms_reject_original_confirmation",
        "tests/component/account/test_simulated_corporate_action_capability_issuance_postgres.py::test_native_v2_cannot_select_a_capability_outside_current_policy",
        "tests/component/account/test_simulated_corporate_action_consent_capabilities_http.py::test_native_http_selected_capabilities_replace_same_chain_and_withdraw_after_policy_loss",
        "tests/component/account/test_simulated_corporate_action_consent_capabilities_http.py::test_native_http_current_policy_change_blocks_prepared_capability_confirmation",
        "tests/component/account/test_simulated_corporate_action_consent_capabilities_http.py::test_native_http_unknown_historical_terms_can_still_be_withdrawn",
        "tests/component/account/test_simulated_corporate_action_capability_issuance_postgres.py::test_native_v3_full_grant_is_exactly_retried_and_reads_all_five_capabilities",
        "tests/component/account/test_simulated_corporate_action_capability_issuance_postgres.py::test_native_v3_csrf_foreign_owner_or_changed_terms_cannot_append",
        "tests/component/account/test_simulated_corporate_action_capability_issuance_postgres.py::test_native_v3_owner_can_withdraw_after_role_policy_and_issuer_key_loss",
        "tests/component/account/test_simulated_corporate_action_consent_capabilities_http.py::test_native_http_v3_selected_share_rights_consent_reads_exact_capabilities_and_withdraws",
        "tests/component/account/test_simulated_corporate_action_consent_capabilities_http.py::test_native_http_v3_changed_policy_terms_block_prepared_confirmation",
        "tests/component/simulated_trading/test_owner_granted_corporate_action_capabilities_postgres.py::test_native_v2_cash_grant_posts_replays_and_withdrawal_blocks",
        "tests/component/simulated_trading/test_owner_granted_corporate_action_capabilities_postgres.py::test_native_tax_only_v2_current_head_denies_cash_without_v1_fallback",
        "tests/component/simulated_trading/test_corporate_action_posting_repository.py::test_correction_replay_requires_complete_set_and_survives_later_payment",
        "tests/component/simulated_trading/test_corporate_action_posting_repository.py::test_replay_resolution_requires_complete_correction_but_allows_later_posting",
        "tests/component/simulated_trading/test_simulated_tax_date_convention_postgres.py::test_native_date_rule_uses_actual_profile_clocks_and_never_falls_back",
        "tests/component/simulated_trading/test_simulated_tax_policy_postgres.py::test_native_tax_policy_exact_current_profile_scope_and_disable",
        "tests/component/simulated_trading/test_owner_tax_assessment_scope_postgres.py::test_native_tax_assess_owner_commits_one_verified_set_and_exact_retry",
        "tests/component/simulated_trading/test_owner_tax_assessment_scope_postgres.py::test_native_owner_final_tax_fact_change_rolls_back_all_four_writes",
        "tests/component/simulated_trading/test_owner_tax_assessment_scope_postgres.py::test_native_withholding_only_grant_cannot_assess_tax",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_partial_collection_and_exact_retry_keep_one_complete_financial_set",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_recognition_retains_unpaid_tax_without_cash_movement",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_new_operation_recovers_remaining_tax_after_later_funding",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_explicit_successor_refunds_only_actual_overcollection",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_late_owner_failure_rolls_back_cash_journal_audit_and_outbox",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_late_journal_failure_rolls_back_cash_audit_and_outbox",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_missing_original_financial_outbox_is_blocked_without_repair",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_same_operation_id_changed_action_cannot_write_again",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_concurrent_exact_operations_collect_only_once",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_financial_journal_always_guard_blocks_raw_replica_mutations",
        "tests/component/simulated_trading/test_corporate_action_tax_liability_postgres.py::test_native_partial_dispositions_can_reuse_revision_labels_without_cross_readback",
        "tests/component/simulated_trading/test_owner_tax_liability_scope_postgres.py::test_native_current_withholding_grant_cannot_collect_without_audited_payment",
        "tests/component/simulated_trading/test_owner_tax_liability_scope_postgres.py::test_native_nonstaff_withholding_and_old_source_retry_preserve_original_evidence",
        "tests/component/simulated_trading/test_owner_tax_liability_scope_postgres.py::test_native_withholding_retry_still_requires_current_consent_and_role",
        "tests/component/simulated_trading/test_owner_tax_liability_scope_postgres.py::test_native_old_source_replay_cannot_authorize_a_different_financial_operation",
        "tests/component/simulated_trading/test_owner_tax_liability_scope_postgres.py::test_native_final_current_tax_change_rolls_back_all_financial_effects",
        "tests/component/simulated_trading/test_owner_tax_liability_scope_postgres.py::test_native_assessment_only_current_grant_cannot_collect_tax",
        "tests/component/simulated_trading/test_simulated_tax_history_native_postgres.py::test_native_simulated_history_uses_explicit_tax_dates_and_only_reads_persisted_sources",
        "tests/component/simulated_trading/test_corporate_action_tax_settlement_history_repository.py::test_adapter_returns_only_an_exact_current_event_with_its_original_clock",
        "tests/component/simulated_trading/test_corporate_action_tax_settlement_history_repository.py::test_adapter_blocks_changed_current_event_instead_of_using_receipt_metadata",
        "tests/component/simulated_trading/test_corporate_action_tax_settlement_history_repository.py::test_adapter_rejects_a_source_reader_row_outside_the_requested_cutoff",
        "tests/component/simulated_trading/test_owner_granted_cash_correction_postgres.py::test_native_owner_cash_correction_replays_complete_batch_after_payment",
        "tests/component/simulated_trading/test_owner_granted_cash_correction_postgres.py::test_native_owner_cash_correction_second_audit_failure_rolls_back_batch",
        "tests/component/simulated_trading/test_audited_corporate_action_posting_composition.py::test_audited_cash_correction_normalizes_appends_and_replays_the_full_batch",
        "tests/component/simulated_trading/test_audited_corporate_action_posting_composition.py::test_audited_cash_correction_rejects_partial_and_mixed_source_batches",
        "tests/component/simulated_trading/test_audited_corporate_action_posting_composition.py::test_second_audit_append_failure_rolls_back_entire_cash_correction",
        "tests/component/simulated_trading/test_audited_corporate_action_posting_composition.py::test_second_correction_outbox_failure_rolls_back_audit_and_ledger_batch",
        "tests/component/simulated_trading/test_corporate_action_posting_repository.py::test_source_record_identity_may_change_only_between_source_revisions",
        "tests/component/simulated_trading/test_corporate_action_posting_repository.py::test_corrected_revision_blocks_duplicate_posting_but_allows_payment_and_full_replay",
        "tests/component/simulated_trading/test_corporate_action_posting_repository.py::test_current_source_head_does_not_repeat_an_existing_rights_no_effect_stage",
        "tests/component/simulated_trading/test_official_disclosure_action_qualification.py::test_exact_source_revision_and_gross_terms_are_qualified",
        "tests/component/simulated_trading/test_current_simulated_tax_qualification_postgres.py::test_current_tax_qualification_rebuilds_real_persisted_owner_facts",
        "tests/component/simulated_trading/test_current_simulated_tax_qualification_postgres.py::test_real_paid_cash_stage_keeps_exact_current_audit_and_withholding_grants",
        "tests/component/simulated_trading/test_current_simulated_tax_qualification_postgres.py::test_tax_collection_requires_reached_audited_cash_payment",
        "tests/component/simulated_trading/test_corporate_action_tax_balance_postgres.py::test_native_readonly_debt_and_partial_collection_preserve_controlled_net_assets",
        "tests/component/simulated_trading/test_corporate_action_tax_balance_postgres.py::test_native_new_unapplied_assessment_blocks_order_cash_without_any_repair",
        "tests/component/simulated_trading/test_corporate_action_tax_balance_postgres.py::test_native_independent_dispositions_sum_and_cash_book_preserves_gross_cash",
        "tests/component/simulated_trading/test_corporate_action_tax_balance_postgres.py::test_native_missing_original_tax_outbox_blocks_read_without_repair",
        "tests/component/simulated_trading/test_corporate_action_tax_balance_postgres.py::test_native_new_cash_debits_cannot_spend_verified_tax",
    )
    assert step["env"]["DATABASE_URL"].endswith("/agom_release_rehearsal_ci")
    assert step["env"]["AGOM_CRITICAL_TEST_DB_NAME"] == "ash05_cash_posting_test"
    assert "--ds=core.settings.critical_postgres_test" in step["run"]
    assert "--confcutdir=tests/component" in step["run"]
    assert "--create-db" in step["run"]
    assert "--no-migrations" not in step["run"]
    assert "--junitxml=ash05-cash-posting-postgres.xml" in step["run"]
    evidence_source, artifact_files = _evidence_gate_source()
    assert "'ash05-cash-posting-postgres.xml'" in evidence_source
    assert "ash05-cash-posting-postgres.xml" in artifact_files


def test_ash05_full_qualifier_uses_a_bounded_real_redis_limiter() -> None:
    """The real egress qualifier retains its Redis dependency in native CI."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["publication-postgres"]
    redis = job["services"]["redis"]
    assert re.fullmatch(r"redis@sha256:[0-9a-f]{64}", redis["image"])
    assert redis["ports"] == ["6379:6379"]
    assert "--cpus 0.25" in redis["options"]
    assert "--memory 64m" in redis["options"]
    assert "redis-cli ping" in redis["options"]
    step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Exercise ASH-05 native corporate-action ledger"
    )
    endpoint = urlsplit(step["env"]["REDIS_URL"])
    assert endpoint.scheme == "redis"
    assert endpoint.hostname in {"127.0.0.1", "localhost", "::1"}
    assert endpoint.port == 6379 and endpoint.path == "/0"


def test_account_research_authority_step_checks_scope_and_exact_junit_identities() -> None:
    """The selected EVID-06 cases use the isolated DB and a strict independent XML check."""

    from urllib.parse import urlsplit

    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["publication-postgres"]
    step = next(
        item
        for item in job["steps"]
        if item.get("name") == "Exercise required Account and Research EVID-06 authority fixtures"
    )
    command = step["run"]
    parent_url = urlsplit(job["env"]["AGOM_EVID06_POSTGRES_TEST_DATABASE_URL"])
    step_url = urlsplit(step["env"]["AGOM_EVID06_POSTGRES_TEST_DATABASE_URL"])

    assert job["env"]["AGOM_EVID06_POSTGRES_TEST"] == "1"
    assert step["env"]["AGOM_EVID06_POSTGRES_TEST"] == "1"
    assert parent_url.scheme in {"postgres", "postgresql"}
    assert parent_url.hostname in {"127.0.0.1", "localhost", "::1"}
    assert parent_url.path == "/agom_release_rehearsal_ci"
    assert step_url.scheme in {"postgres", "postgresql"}
    assert step_url.hostname in {"127.0.0.1", "localhost", "::1"}
    assert step_url.netloc == parent_url.netloc
    assert step_url.port == 5432
    assert step_url.path == "/evid06_authority_test"
    assert _pytest_nodeids(command) == EVID06_AUTHORITY_NODEIDS

    continuation = "python -m pytest " + "\\" + "\n"
    assert continuation in command
    pytest_command = command.split(continuation, maxsplit=1)[1].split(
        "\npytest_status=$?", maxsplit=1
    )[0]
    assert all(
        line.rstrip().endswith("\\") for line in pytest_command.splitlines() if "::test_" in line
    )
    assert "--ds=core.settings.development_sqlite " + "\\" in command
    assert "--confcutdir=tests/component " + "\\" in command
    assert "--junitxml=account-research-authority-postgres.xml" in command
    assert "--create-db" not in command
    assert "pg_stat_activity" in command and "pid <> pg_backend_pid()" in command
    assert "pg_class" in command and "current_database()" in command
    assert command.count("assert_evid06_database_empty_and_unconnected") == 3
    assert 'exit "$pytest_status"' in command
    assert 'exit "$identity_status"' in command
    assert 'exit "$postflight_status"' in command

    xml_check = command.split("python - <<'PY'\n", maxsplit=1)[1].split("\nPY", maxsplit=1)[0]
    tree = ast.parse(xml_check)
    expected_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "expected" for target in node.targets)
    )
    expected_ids = ast.literal_eval(expected_assignment.value)
    expected_module_ids = {
        f"{node.split('::', maxsplit=1)[0].removesuffix('.py').replace('/', '.')}::{node.split('::', maxsplit=1)[1]}"
        for node in EVID06_AUTHORITY_NODEIDS
    }
    assert expected_ids == expected_module_ids
    assert 'case.find("skipped") is None' in xml_check
    assert 'case.find("failure") is None' in xml_check
    assert 'case.find("error") is None' in xml_check
    assert "len(cases)" not in xml_check
    assert "from scripts.validate_release_rehearsal" not in xml_check

    evidence_source, artifact_files = _evidence_gate_source()
    junit_name = "account-research-authority-postgres.xml"
    assert junit_name in artifact_files
    assert f"'{junit_name}'" in evidence_source


def _authority_flush_gate_source() -> str:
    """Read the exact inline cleanup gate, independently of publication suites."""
    workflow = yaml.load(
        (ROOT / ".github/workflows/nightly-tests.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    step = next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "Run full-registry transaction cleanup regressions on PostgreSQL"
    )
    source = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    ast.parse(source)
    return source


def _write_authority_flush_gate_fixture(tmp_path: Path, mutation: str = "") -> None:
    """Build explicit synthetic JUnit for gate rejection tests, without a database."""
    counts = {
        "tests.component.data_center.test_audited_price_sync_transaction": 20,
        "tests.component.data_center.test_audited_macro_sync_transaction": 3,
        "tests.component.config_center.test_aud05_atomic_activation": 18,
        "tests.component.data_center.test_audited_quote_sync_transaction": 7,
        "tests.component.data_center.test_current_publication_staging": 30,
        "tests.component.data_center.test_financial_source_time_audit_claim": 2,
    }
    if mutation in {"old_aba_scope", "old_11e_scope"}:
        counts["tests.component.data_center.test_audited_price_sync_transaction"] = 5
    if mutation == "old_aba_scope":
        counts["tests.component.data_center.test_audited_quote_sync_transaction"] = 5
        counts["tests.component.data_center.test_current_publication_staging"] = 24
    races = (
        "test_postgresql_bootstrap_race_has_one_first_winner",
        "test_postgresql_successor_race_has_one_first_winner",
    )
    cases: list[str] = []
    properties: list[str] = []
    for module, count in counts.items():
        for index in range(count):
            name = races[index] if "atomic_activation" in module and index < 2 else f"test_{index}"
            if mutation == "missing_race" and name == races[0]:
                name = "test_unrelated"
            classname = "tests.wrong_module" if mutation == "wrong_module" and not cases else module
            outcome = (
                f"<{mutation}/>"
                if mutation in {"failure", "error", "skipped"} and not cases
                else ""
            )
            cases.append(f'<testcase classname="{classname}" name="{name}">{outcome}</testcase>')
        pairs = [[index, index + 1] for index in range(count)]
        if not properties:
            if mutation == "missing_flush":
                pairs.pop()
            elif mutation == "decreasing_flush":
                pairs[0] = [2, 1]
            elif mutation == "bool_flush":
                pairs[0] = [False, 1]
        value = json.dumps(pairs).replace('"', "&quot;")
        properties.append(f'<property name="authority_generation_flushes" value="{value}"/>')
    destination = tmp_path / "reports/quality/postgres/authority-generation-flush.xml"
    destination.parent.mkdir(parents=True)
    destination.write_text(
        "<testsuite><properties>"
        + "".join(properties)
        + "</properties>"
        + "".join(cases)
        + "</testsuite>",
        encoding="utf-8",
    )


def test_authority_flush_gate_accepts_exact_current_module_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The current six-module 80-case scope passes its exact cleanup evidence gate."""
    _write_authority_flush_gate_fixture(tmp_path)
    source = _authority_flush_gate_source()
    monkeypatch.chdir(tmp_path)
    exec(compile(source, "authority-generation-flush-gate", "exec"), {})


@pytest.mark.parametrize(
    "mutation",
    [
        "old_aba_scope",
        "old_11e_scope",
        "wrong_module",
        "failure",
        "error",
        "skipped",
        "missing_flush",
        "decreasing_flush",
        "bool_flush",
        "missing_race",
    ],
)
def test_authority_flush_gate_rejects_incomplete_or_invalid_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """Case distribution, native races and every valid flush remain mandatory."""
    _write_authority_flush_gate_fixture(tmp_path, mutation)
    if mutation in {"old_aba_scope", "old_11e_scope"}:
        fixture_path = tmp_path / "reports/quality/postgres/authority-generation-flush.xml"
        actual_count = len(list(ET.parse(fixture_path).iter("testcase")))
        expected_count = 57 if mutation == "old_aba_scope" else 65
        assert actual_count == expected_count
    source = _authority_flush_gate_source()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError):
        exec(compile(source, "authority-generation-flush-gate", "exec"), {})
