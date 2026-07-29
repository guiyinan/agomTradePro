"""Unit coverage for the versioned Celery task contract guard."""

import json
import subprocess
from pathlib import Path

import scripts.check_celery_task_contracts as celery_guard
from scripts.check_celery_task_contracts import (
    collect_shared_task_functions_from_source,
    validate_celery_task_contracts,
)


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    """Write one temporary contract manifest."""

    path.write_text(json.dumps(payload), encoding="utf-8")


def test_repository_celery_task_contract_manifest_is_valid() -> None:
    """The checked-in manifest and focused test evidence must stay coherent."""

    assert validate_celery_task_contracts() == []


def test_guard_rejects_unregistered_task_in_governed_file(tmp_path: Path) -> None:
    """Adding a shared task to a governed file requires explicit evidence."""

    source = tmp_path / "tasks.py"
    source.write_text(
        "from celery import shared_task\n"
        "@shared_task\ndef governed_task():\n    return None\n"
        "@shared_task\ndef missing_task():\n    return None\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_tasks.py"
    test_file.write_text("def test_governed_task_invalid_input():\n    pass\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "governed_source_files": ["tasks.py"],
            "tasks": [
                {
                    "task_path": "example.tasks.governed_task",
                    "source_file": "tasks.py",
                    "criticality": "freshness_critical",
                    "required_cases": {
                        "invalid_input": {
                            "test_file": "test_tasks.py",
                            "test_function": "test_governed_task_invalid_input",
                        }
                    },
                }
            ],
        },
    )

    violations = validate_celery_task_contracts(manifest, repo_root=tmp_path)

    assert any(
        item.code == "unregistered_task" and "missing_task" in item.message for item in violations
    )


def test_guard_rejects_missing_test_function(tmp_path: Path) -> None:
    """A filename alone is not sufficient contract evidence."""

    source = tmp_path / "tasks.py"
    source.write_text(
        "from celery import shared_task\n" "@shared_task\ndef governed_task():\n    return None\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_tasks.py"
    test_file.write_text("def test_something_else():\n    pass\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "governed_source_files": ["tasks.py"],
            "tasks": [
                {
                    "task_path": "example.tasks.governed_task",
                    "source_file": "tasks.py",
                    "criticality": "data_mutation_critical",
                    "required_cases": {
                        "complete_failure": {
                            "test_file": "test_tasks.py",
                            "test_function": "test_governed_task_complete_failure",
                        }
                    },
                }
            ],
        },
    )

    violations = validate_celery_task_contracts(manifest, repo_root=tmp_path)

    assert any(item.code == "test_function_missing" for item in violations)


def test_shared_task_diff_detects_a_new_task() -> None:
    """The differential guard can distinguish a newly introduced shared task."""

    before = (
        "from celery import shared_task\n"
        "@shared_task\n"
        "def existing_task():\n"
        "    return None\n"
    )
    after = f"{before}" "@shared_task\n" "def newly_added_task():\n" "    return None\n"

    previous_tasks = collect_shared_task_functions_from_source(
        before,
        filename="base:tasks.py",
    )
    current_tasks = collect_shared_task_functions_from_source(
        after,
        filename="head:tasks.py",
    )

    assert current_tasks - previous_tasks == {"newly_added_task"}


def test_differential_guard_rejects_new_unregistered_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A new Application shared task cannot bypass the versioned manifest."""

    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {"schema_version": 1, "governed_source_files": [], "tasks": []},
    )
    source_file = "apps/example/application/tasks.py"
    before = "from celery import shared_task\n"
    after = f"{before}" "@shared_task\n" "def newly_added_task():\n" "    return None\n"

    def fake_run_git(
        repo_root: Path,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        del repo_root
        if args[0] == "diff":
            return subprocess.CompletedProcess(args, 0, f"{source_file}\n", "")
        if args[0] == "show" and args[1].startswith("base:"):
            return subprocess.CompletedProcess(args, 0, before, "")
        if args[0] == "show" and args[1].startswith("head:"):
            return subprocess.CompletedProcess(args, 0, after, "")
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(celery_guard, "_run_git", fake_run_git)

    violations = celery_guard.validate_new_shared_tasks(
        base_ref="base",
        head_ref="head",
        manifest_path=manifest,
        repo_root=tmp_path,
    )

    assert [(item.code, item.message) for item in violations] == [
        (
            "new_task_unregistered",
            f"{source_file}: new shared task newly_added_task must be registered",
        )
    ]
