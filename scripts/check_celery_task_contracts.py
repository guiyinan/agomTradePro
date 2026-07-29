#!/usr/bin/env python
"""Validate governed Celery tasks and their focused behavioral evidence."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "governance" / "celery_task_contracts.json"
KNOWN_CASES = {
    "all_success",
    "blocked",
    "complete_failure",
    "invalid_input",
    "partial_failure",
    "zero_output",
}


@dataclass(frozen=True)
class ContractViolation:
    """One deterministic Celery task contract violation."""

    code: str
    message: str


def _load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object or raise a human-readable validation error."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: root must be an object")
    return payload


def _decorator_name(decorator: ast.expr) -> str | None:
    """Return the final callable name for one decorator expression."""

    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def collect_shared_task_functions_from_source(
    source: str,
    *,
    filename: str,
) -> set[str]:
    """Collect top-level functions decorated with ``shared_task`` from source."""

    tree = ast.parse(source, filename=filename)
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(_decorator_name(item) == "shared_task" for item in node.decorator_list)
    }


def collect_shared_task_functions(path: Path) -> set[str]:
    """Collect top-level functions decorated with ``shared_task``."""

    return collect_shared_task_functions_from_source(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )


def collect_test_functions(path: Path) -> set[str]:
    """Collect top-level pytest test function names from one file."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    }


def _registered_tasks_by_file(payload: dict[str, Any]) -> dict[str, set[str]]:
    """Index registered task function names by repository-relative source file."""

    registered: dict[str, set[str]] = {}
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list):
        return registered
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            continue
        source_file = raw_task.get("source_file")
        task_path = raw_task.get("task_path")
        if isinstance(source_file, str) and isinstance(task_path, str):
            registered.setdefault(source_file, set()).add(task_path.rsplit(".", 1)[-1])
    return registered


def _is_application_python_file(path: str) -> bool:
    """Return whether a path can contain an Application-layer Celery task."""

    parts = Path(path).parts
    return (
        len(parts) >= 4
        and parts[0] == "apps"
        and parts[2] == "application"
        and parts[-1].endswith(".py")
    )


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one read-only Git command for the differential guard."""

    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )


def _git_source(repo_root: Path, ref: str, source_file: str) -> str | None:
    """Read a source file at a Git ref, returning None when it did not exist."""

    result = _run_git(repo_root, "show", f"{ref}:{source_file}")
    if result.returncode != 0:
        return None
    return result.stdout


def validate_new_shared_tasks(
    *,
    base_ref: str,
    head_ref: str,
    manifest_path: Path = DEFAULT_MANIFEST,
    repo_root: Path = REPO_ROOT,
) -> list[ContractViolation]:
    """Require every newly added Application shared task to enter governance."""

    try:
        payload = _load_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [ContractViolation("manifest_invalid", str(exc))]

    diff = _run_git(
        repo_root,
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        f"{base_ref}...{head_ref}",
        "--",
        "apps",
    )
    if diff.returncode != 0:
        detail = diff.stderr.strip() or "git diff failed"
        return [ContractViolation("git_diff_failed", detail)]

    registered_by_file = _registered_tasks_by_file(payload)
    violations: list[ContractViolation] = []
    for raw_path in diff.stdout.splitlines():
        source_file = raw_path.strip().replace("\\", "/")
        if not _is_application_python_file(source_file):
            continue
        head_source = _git_source(repo_root, head_ref, source_file)
        if head_source is None:
            continue
        base_source = _git_source(repo_root, base_ref, source_file) or ""
        try:
            before = collect_shared_task_functions_from_source(
                base_source,
                filename=f"{base_ref}:{source_file}",
            )
            after = collect_shared_task_functions_from_source(
                head_source,
                filename=f"{head_ref}:{source_file}",
            )
        except SyntaxError as exc:
            violations.append(ContractViolation("source_parse_error", f"{source_file}: {exc}"))
            continue

        registered = registered_by_file.get(source_file, set())
        for task_name in sorted((after - before) - registered):
            violations.append(
                ContractViolation(
                    "new_task_unregistered",
                    f"{source_file}: new shared task {task_name} must be registered",
                )
            )
    return violations


def validate_celery_task_contracts(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[ContractViolation]:
    """Validate manifest shape, governed task coverage, and test evidence."""

    violations: list[ContractViolation] = []
    try:
        payload = _load_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [ContractViolation("manifest_invalid", str(exc))]

    if payload.get("schema_version") != 1:
        violations.append(ContractViolation("schema_version", "schema_version must equal 1"))

    raw_governed_files = payload.get("governed_source_files")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_governed_files, list) or not all(
        isinstance(item, str) and item for item in raw_governed_files
    ):
        violations.append(
            ContractViolation(
                "governed_source_files",
                "governed_source_files must be a non-empty string list",
            )
        )
        raw_governed_files = []
    if not isinstance(raw_tasks, list):
        violations.append(ContractViolation("tasks", "tasks must be a list"))
        raw_tasks = []

    registered_by_file: dict[str, set[str]] = {}
    seen_task_paths: set[str] = set()
    test_cache: dict[Path, set[str]] = {}

    for index, raw_task in enumerate(raw_tasks):
        label = f"tasks[{index}]"
        if not isinstance(raw_task, dict):
            violations.append(ContractViolation("task_invalid", f"{label} must be an object"))
            continue

        task_path = raw_task.get("task_path")
        source_file = raw_task.get("source_file")
        criticality = raw_task.get("criticality")
        required_cases = raw_task.get("required_cases")
        if not isinstance(task_path, str) or not task_path:
            violations.append(ContractViolation("task_path", f"{label}.task_path is required"))
            continue
        if task_path in seen_task_paths:
            violations.append(
                ContractViolation("task_duplicate", f"duplicate task_path: {task_path}")
            )
        seen_task_paths.add(task_path)

        if not isinstance(source_file, str) or not source_file:
            violations.append(
                ContractViolation("source_file", f"{task_path}: source_file is required")
            )
            continue
        registered_by_file.setdefault(source_file, set()).add(task_path.rsplit(".", 1)[-1])

        if criticality not in {"freshness_critical", "data_mutation_critical"}:
            violations.append(
                ContractViolation(
                    "criticality",
                    f"{task_path}: unsupported criticality {criticality!r}",
                )
            )
        if not isinstance(required_cases, dict) or not required_cases:
            violations.append(
                ContractViolation(
                    "required_cases",
                    f"{task_path}: required_cases must be a non-empty object",
                )
            )
            continue

        unknown_cases = sorted(set(required_cases) - KNOWN_CASES)
        if unknown_cases:
            violations.append(
                ContractViolation(
                    "unknown_case",
                    f"{task_path}: unknown cases {', '.join(unknown_cases)}",
                )
            )

        for case_name, raw_evidence in required_cases.items():
            if not isinstance(raw_evidence, dict):
                violations.append(
                    ContractViolation(
                        "evidence_invalid",
                        f"{task_path}.{case_name}: evidence must be an object",
                    )
                )
                continue
            test_file = raw_evidence.get("test_file")
            test_function = raw_evidence.get("test_function")
            if not isinstance(test_file, str) or not isinstance(test_function, str):
                violations.append(
                    ContractViolation(
                        "evidence_invalid",
                        f"{task_path}.{case_name}: test_file and test_function are required",
                    )
                )
                continue

            test_path = repo_root / test_file
            if not test_path.is_file():
                violations.append(
                    ContractViolation(
                        "test_file_missing",
                        f"{task_path}.{case_name}: missing {test_file}",
                    )
                )
                continue
            if test_path not in test_cache:
                try:
                    test_cache[test_path] = collect_test_functions(test_path)
                except (OSError, SyntaxError) as exc:
                    violations.append(ContractViolation("test_parse_error", f"{test_file}: {exc}"))
                    test_cache[test_path] = set()
            if test_function not in test_cache[test_path]:
                violations.append(
                    ContractViolation(
                        "test_function_missing",
                        f"{task_path}.{case_name}: {test_file} lacks {test_function}",
                    )
                )

    for source_file in raw_governed_files:
        source_path = repo_root / source_file
        if not source_path.is_file():
            violations.append(
                ContractViolation("source_file_missing", f"missing governed file {source_file}")
            )
            continue
        try:
            discovered = collect_shared_task_functions(source_path)
        except (OSError, SyntaxError) as exc:
            violations.append(ContractViolation("source_parse_error", f"{source_file}: {exc}"))
            continue
        registered = registered_by_file.get(source_file, set())
        for task_name in sorted(discovered - registered):
            violations.append(
                ContractViolation(
                    "unregistered_task",
                    f"{source_file}: shared task {task_name} is not registered",
                )
            )
        for task_name in sorted(registered - discovered):
            violations.append(
                ContractViolation(
                    "task_not_found",
                    f"{source_file}: registered task {task_name} is not a shared task",
                )
            )

    return violations


def main() -> int:
    """Run the repository Celery task contract guard."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    args = parser.parse_args()

    violations = validate_celery_task_contracts(args.manifest)
    if bool(args.base_ref) != bool(args.head_ref):
        parser.error("--base-ref and --head-ref must be provided together")
    if args.base_ref and args.head_ref:
        violations.extend(
            validate_new_shared_tasks(
                base_ref=args.base_ref,
                head_ref=args.head_ref,
                manifest_path=args.manifest,
            )
        )
    if violations:
        print(f"Celery task contracts failed: {len(violations)} violation(s)")
        for violation in violations:
            print(f"- [{violation.code}] {violation.message}")
        return 1

    payload = _load_json(args.manifest)
    print(
        "Celery task contracts OK: "
        f"{len(payload.get('tasks', []))} task(s), "
        f"{len(payload.get('governed_source_files', []))} governed file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
