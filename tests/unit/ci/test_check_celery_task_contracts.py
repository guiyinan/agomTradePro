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
        "from celery import shared_task\n@shared_task\ndef governed_task():\n    return None\n",
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


def test_guard_scans_every_application_task_file(tmp_path: Path) -> None:
    """Legacy tasks outside the old governed-file list must not remain invisible."""

    source = tmp_path / "apps" / "example" / "application" / "tasks.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from celery import shared_task\n@shared_task\ndef legacy_task():\n    return None\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "governed_source_files": [],
            "tasks": [],
            "exemptions": [],
        },
    )

    violations = validate_celery_task_contracts(manifest, repo_root=tmp_path)

    assert any(
        item.code == "unregistered_application_task" and "legacy_task" in item.message
        for item in violations
    )


def test_guard_rejects_nested_shared_task_as_non_importable_contract(
    tmp_path: Path,
) -> None:
    """A nested task is discovered but cannot masquerade as a module-level symbol."""
    source = tmp_path / "apps" / "example" / "application" / "tasks.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from celery import shared_task\n"
        "def factory():\n"
        "    @shared_task\n"
        "    def nested_task():\n"
        "        return None\n"
        "    return nested_task\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_tasks.py"
    test_file.write_text("def test_nested_success():\n    pass\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "governed_source_files": [],
            "tasks": [],
            "exemptions": [],
        },
    )
    uncovered = validate_celery_task_contracts(manifest, repo_root=tmp_path)
    assert any(item.code == "nested_shared_task" for item in uncovered)
    assert any(
        item.code == "unregistered_application_task" and "nested_task" in item.message
        for item in uncovered
    )

    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "governed_source_files": [],
            "tasks": [
                {
                    "task_path": "apps.example.application.tasks.nested_task",
                    "source_file": "apps/example/application/tasks.py",
                    "criticality": "freshness_critical",
                    "required_cases": {
                        "all_success": {
                            "test_file": "test_tasks.py",
                            "test_function": "test_nested_success",
                        }
                    },
                }
            ],
            "exemptions": [],
        },
    )
    falsely_registered = validate_celery_task_contracts(manifest, repo_root=tmp_path)
    assert any(item.code == "task_path_mismatch" for item in falsely_registered)


def test_guard_accepts_auditable_compatibility_alias_exemption(tmp_path: Path) -> None:
    """A real registered target may own one explicit compatibility wrapper."""

    source = tmp_path / "apps" / "example" / "application" / "tasks.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from celery import shared_task\n"
        "@shared_task\ndef canonical_task():\n    return None\n"
        "@shared_task\ndef canonical_task_alias():\n    return canonical_task()\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_tasks.py"
    test_file.write_text("def test_canonical_success():\n    pass\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    canonical_path = "apps.example.application.tasks.canonical_task"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "governed_source_files": [],
            "tasks": [
                {
                    "task_path": canonical_path,
                    "source_file": "apps/example/application/tasks.py",
                    "criticality": "freshness_critical",
                    "required_cases": {
                        "all_success": {
                            "test_file": "test_tasks.py",
                            "test_function": "test_canonical_success",
                        }
                    },
                }
            ],
            "exemptions": [
                {
                    "task_path": "apps.example.application.tasks.canonical_task_alias",
                    "source_file": "apps/example/application/tasks.py",
                    "owner": "example",
                    "reason": "Compatibility wrapper retained for the legacy Celery route.",
                    "compatibility_target": canonical_path,
                }
            ],
        },
    )

    assert validate_celery_task_contracts(manifest, repo_root=tmp_path) == []


def test_guard_rejects_unauditable_or_dangling_exemption(tmp_path: Path) -> None:
    """Exemptions require an owner, rationale, live symbol and registered target."""

    source = tmp_path / "apps" / "example" / "application" / "tasks.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from celery import shared_task\n@shared_task\ndef legacy_alias():\n    return None\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "governed_source_files": [],
            "tasks": [],
            "exemptions": [
                {
                    "task_path": "apps.example.application.tasks.legacy_alias",
                    "source_file": "apps/example/application/tasks.py",
                    "owner": "",
                    "reason": "short",
                    "compatibility_target": "apps.example.application.tasks.missing",
                }
            ],
        },
    )

    violations = validate_celery_task_contracts(manifest, repo_root=tmp_path)
    codes = {item.code for item in violations}

    assert {"exemption_owner", "exemption_reason", "exemption_target"} <= codes


def test_guard_rejects_registered_task_path_from_the_wrong_module(tmp_path: Path) -> None:
    """A matching final symbol cannot hide a false owner module in the manifest."""

    source = tmp_path / "apps" / "example" / "application" / "tasks.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from celery import shared_task\n@shared_task\ndef governed_task():\n    return None\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_tasks.py"
    test_file.write_text("def test_governed_success():\n    pass\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "governed_source_files": [],
            "tasks": [
                {
                    "task_path": "apps.wrong.application.tasks.governed_task",
                    "source_file": "apps/example/application/tasks.py",
                    "criticality": "freshness_critical",
                    "required_cases": {
                        "all_success": {
                            "test_file": "test_tasks.py",
                            "test_function": "test_governed_success",
                        }
                    },
                }
            ],
            "exemptions": [],
        },
    )

    violations = validate_celery_task_contracts(manifest, repo_root=tmp_path)

    assert any(item.code == "task_path_mismatch" for item in violations)


def test_guard_accepts_explicit_celery_task_name(tmp_path: Path) -> None:
    """A literal decorator name is an authoritative task path despite its source module."""

    source = tmp_path / "apps" / "example" / "application" / "archive_tasks.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from celery import shared_task\n"
        "@shared_task(name='apps.example.application.tasks.verify_archive')\n"
        "def verify_archive():\n    return None\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_tasks.py"
    test_file.write_text("def test_verify_success():\n    pass\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "governed_source_files": [],
            "tasks": [
                {
                    "task_path": "apps.example.application.tasks.verify_archive",
                    "source_file": "apps/example/application/archive_tasks.py",
                    "criticality": "freshness_critical",
                    "required_cases": {
                        "all_success": {
                            "test_file": "test_tasks.py",
                            "test_function": "test_verify_success",
                        }
                    },
                }
            ],
            "exemptions": [],
        },
    )

    assert validate_celery_task_contracts(manifest, repo_root=tmp_path) == []


def test_shared_task_diff_detects_a_new_task() -> None:
    """The differential guard can distinguish a newly introduced shared task."""

    before = "from celery import shared_task\n@shared_task\ndef existing_task():\n    return None\n"
    after = f"{before}@shared_task\ndef newly_added_task():\n    return None\n"

    previous_tasks = collect_shared_task_functions_from_source(
        before,
        filename="base:tasks.py",
    )
    current_tasks = collect_shared_task_functions_from_source(
        after,
        filename="head:tasks.py",
    )

    assert current_tasks - previous_tasks == {"newly_added_task"}


def test_typed_shared_task_is_governed_like_celery_shared_task() -> None:
    """The typed project wrapper must not bypass task contract governance."""

    source = (
        "from shared.infrastructure.celery_typing import typed_shared_task\n"
        "@typed_shared_task(name='example.task')\n"
        "def typed_task():\n"
        "    return None\n"
    )

    assert collect_shared_task_functions_from_source(
        source,
        filename="typed_tasks.py",
    ) == {"typed_task"}


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
    after = f"{before}@shared_task\ndef newly_added_task():\n    return None\n"

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
