from __future__ import annotations

import ast
import shlex
import textwrap
from pathlib import Path
from typing import cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci-quote-metric-postgres.yml"
JOB_ID = "quote-metric-postgres"
XML_GUARD_STEP = "Reject missing, skipped, or empty PostgreSQL evidence"
QUOTE_ROUNDTRIP_FILE = "tests/component/data_center/test_quote_metric_publication_roundtrip.py"
QUOTE_ROUNDTRIP_TEST = (
    "test_quote_metric_roundtrips_through_atomic_current_group_and_realtime_cache"
)
MANDATORY_CASES = frozenset(
    {
        QUOTE_ROUNDTRIP_TEST,
        "test_concurrent_first_creation_cannot_rewrite_quote_contract_semantics",
        "test_null_quote_metric_preserves_pre_metric_golden_hashes",
        "test_legacy_hash_bytes_remain_exactly_unchanged",
        "test_existing_nonnullable_policy_and_hashes_match_prechange_goldens",
    }
)


def _load_workflow_job() -> tuple[dict[str, object], list[dict[str, object]]]:
    """Load the actual workflow job and its steps without changing YAML scalar values."""
    document = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    jobs = document.get("jobs")
    assert isinstance(jobs, dict)
    job_value = jobs.get(JOB_ID)
    assert isinstance(job_value, dict)
    job = cast(dict[str, object], job_value)
    steps_value = job.get("steps")
    assert isinstance(steps_value, list)
    assert all(isinstance(step, dict) for step in steps_value)
    return job, cast(list[dict[str, object]], steps_value)


def _find_run_step(steps: list[dict[str, object]], *, step_name: str) -> str:
    """Return one named workflow step's shell body."""
    matches = [step for step in steps if step.get("name") == step_name]
    assert len(matches) == 1, f"Expected one workflow step named {step_name!r}"
    run_body = matches[0].get("run")
    assert isinstance(run_body, str), f"Workflow step {step_name!r} has no run body"
    return run_body


def _pytest_run_body(steps: list[dict[str, object]]) -> str:
    """Return the real workflow pytest command body."""
    matches = [
        step
        for step in steps
        if isinstance(step.get("run"), str) and "python -m pytest" in step["run"]
    ]
    assert len(matches) == 1, "Expected one quote metric PostgreSQL pytest command"
    return cast(str, matches[0]["run"])


def _extract_selected_pytest_targets(run_body: str) -> list[str]:
    """Read file and node selectors from the actual pytest command."""
    tokens = shlex.split(run_body)
    command_index = next(
        index
        for index in range(max(0, len(tokens) - 2))
        if tokens[index : index + 3] == ["python", "-m", "pytest"]
    )
    targets: list[str] = []
    for token in tokens[command_index + 3 :]:
        if token.startswith("-"):
            break
        if token.startswith("tests/"):
            targets.append(token)
    assert targets, "The PostgreSQL pytest command selected no test modules"
    assert "--create-db" in tokens, "The PostgreSQL job must use its isolated test database"
    assert "--junitxml=quote-metric-postgres.xml" in tokens
    return targets


def _base_test_name(value: str) -> str:
    """Normalize pytest node IDs to the base Python test function name."""
    return value.split("[", 1)[0].rsplit("::", 1)[-1]


def _pytest_test_functions(module: ast.Module) -> set[str]:
    """Return test functions pytest can collect from a module AST."""
    names: set[str] = set()
    for statement in module.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.name.startswith("test_"):
                names.add(statement.name)
        elif isinstance(statement, ast.ClassDef) and statement.name.startswith("Test"):
            names.update(
                member.name
                for member in statement.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and member.name.startswith("test_")
            )
    return names


def _selected_source_test_functions(targets: list[str]) -> tuple[set[str], set[str], set[str]]:
    """Resolve selected source modules and collect their real pytest functions."""
    selected_names: set[str] = set()
    source_names: set[str] = set()
    selected_paths: set[str] = set()
    for target in targets:
        parts = target.split("::")
        relative_path = parts[0]
        source_path = REPO_ROOT / relative_path
        assert source_path.is_file(), f"Selected pytest source does not exist: {relative_path}"
        source_names_for_file = _pytest_test_functions(
            ast.parse(source_path.read_text(encoding="utf-8"), filename=relative_path)
        )
        source_names.update(source_names_for_file)
        selected_paths.add(relative_path)
        if len(parts) == 1:
            selected_names.update(source_names_for_file)
            continue
        for raw_node_name in parts[1:]:
            node_name = _base_test_name(raw_node_name)
            assert (
                node_name in source_names_for_file
            ), f"Selected pytest node {node_name!r} is missing from {relative_path}"
            selected_names.add(node_name)
    return selected_names, source_names, selected_paths


def _xml_guard_ast(steps: list[dict[str, object]]) -> ast.Module:
    """Parse the inline JUnit validation program from the named workflow step."""
    guard_body = _find_run_step(steps, step_name=XML_GUARD_STEP)
    lines = guard_body.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == "python - <<'PY'"]
    assert len(starts) == 1, "Expected one Python heredoc in the JUnit validation step"
    end = next(
        (index for index in range(starts[0] + 1, len(lines)) if lines[index].strip() == "PY"),
        None,
    )
    assert end is not None, "JUnit validation Python heredoc is unterminated"
    program = textwrap.dedent("\n".join(lines[starts[0] + 1 : end]))
    return ast.parse(program, filename="quote_metric_junit_guard.py")


def _required_junit_base_names(guard: ast.Module) -> set[str]:
    """Extract required test names from the executable JUnit guard's AST."""
    assignments: list[ast.expr] = []
    for node in ast.walk(guard):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "required_names"
            for target in node.targets
        ):
            assignments.append(node.value)
    assert len(assignments) == 1, "Expected one required_names set in the JUnit guard"
    value = ast.literal_eval(assignments[0])
    assert isinstance(value, set) and all(isinstance(name, str) for name in value)
    return {_base_test_name(name) for name in value}


def test_postgres_junit_requirements_match_selected_real_test_functions() -> None:
    """Keep required XML names aligned with selected test source and isolated PG settings."""
    job, steps = _load_workflow_job()
    assert job.get("timeout-minutes") == "15"
    services = job.get("services")
    assert isinstance(services, dict)
    postgres = services.get("postgres")
    assert isinstance(postgres, dict) and postgres.get("image") == "postgres:16"
    environment = job.get("env")
    assert isinstance(environment, dict)
    assert environment.get("DJANGO_SETTINGS_MODULE") == "core.settings.critical_postgres_test"
    assert environment.get("AGOM_CRITICAL_TEST_DB_NAME") == "test_agom_quote_metric_ci"
    assert environment.get("USE_REDIS_CACHE") == "0"
    assert environment.get("REDIS_URL") == ""

    pytest_run = _pytest_run_body(steps)
    targets = _extract_selected_pytest_targets(pytest_run)
    selected_names, source_names, selected_paths = _selected_source_test_functions(targets)
    guard = _xml_guard_ast(steps)
    required_names = _required_junit_base_names(guard)

    assert required_names <= selected_names, (
        "JUnit-required cases are not selected by the workflow pytest command: "
        f"{sorted(required_names - selected_names)}"
    )
    assert required_names <= source_names, (
        "JUnit-required case names do not exist in selected source ASTs: "
        f"{sorted(required_names - source_names)}"
    )
    assert MANDATORY_CASES <= required_names, (
        "The JUnit guard must require the real roundtrip, concurrent contract race, "
        "and legacy/hash golden cases"
    )
    assert QUOTE_ROUNDTRIP_FILE in selected_paths
    quote_module = ast.parse(
        (REPO_ROOT / QUOTE_ROUNDTRIP_FILE).read_text(encoding="utf-8"),
        filename=QUOTE_ROUNDTRIP_FILE,
    )
    assert QUOTE_ROUNDTRIP_TEST in _pytest_test_functions(quote_module)

    guard_assertions = "\n".join(
        ast.unparse(node) for node in guard.body if isinstance(node, ast.Assert)
    )
    assert "report.is_file()" in guard_assertions
    assert "report.stat().st_size > 0" in guard_assertions
    assert "assert cases" in guard_assertions
    assert "case.find('skipped') is None" in guard_assertions
    assert "case.find('failure') is None" in guard_assertions
    assert "case.find('error') is None" in guard_assertions
