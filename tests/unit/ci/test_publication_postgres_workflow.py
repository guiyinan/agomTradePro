"""Publication PostgreSQL evidence gate must follow the shared test inventory."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github/workflows/ci-publication-postgres.yml"
VALIDATOR_PATH = ROOT / "scripts/validate_release_rehearsal.py"
EVIDENCE_ARTIFACT = "publication-postgres-evidence"


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
        "tests.component.data_center.test_audited_price_sync_transaction": 5,
        "tests.component.data_center.test_audited_macro_sync_transaction": 3,
        "tests.component.config_center.test_aud05_atomic_activation": 18,
        "tests.component.data_center.test_audited_quote_sync_transaction": 7,
        "tests.component.data_center.test_current_publication_staging": 30,
        "tests.component.data_center.test_financial_source_time_audit_claim": 2,
    }
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
    """The current six-module 65-case scope passes its exact cleanup evidence gate."""
    _write_authority_flush_gate_fixture(tmp_path)
    source = _authority_flush_gate_source()
    monkeypatch.chdir(tmp_path)
    exec(compile(source, "authority-generation-flush-gate", "exec"), {})


@pytest.mark.parametrize(
    "mutation",
    [
        "old_aba_scope",
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
    source = _authority_flush_gate_source()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError):
        exec(compile(source, "authority-generation-flush-gate", "exec"), {})
