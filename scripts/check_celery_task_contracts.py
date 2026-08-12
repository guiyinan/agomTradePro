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
TASK_DECORATOR_NAMES = {"shared_task", "typed_shared_task"}


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


def _explicit_task_name(decorator: ast.expr) -> str | None:
    """Return one literal Celery ``name=`` override when present."""

    if (
        not isinstance(decorator, ast.Call)
        or _decorator_name(decorator) not in TASK_DECORATOR_NAMES
    ):
        return None
    for keyword in decorator.keywords:
        if (
            keyword.arg == "name"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
            and keyword.value.value
        ):
            return keyword.value.value
    return None


def collect_shared_task_functions_from_source(
    source: str,
    *,
    filename: str,
) -> set[str]:
    """Collect every function decorated with ``shared_task`` from source."""

    tree = ast.parse(source, filename=filename)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(_decorator_name(item) in TASK_DECORATOR_NAMES for item in node.decorator_list)
    }


def collect_nested_shared_task_functions_from_source(
    source: str,
    *,
    filename: str,
) -> set[str]:
    """Return decorated tasks that are not importable module-level symbols."""
    tree = ast.parse(source, filename=filename)
    top_level_node_ids = {
        id(node) for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and id(node) not in top_level_node_ids
        and any(_decorator_name(item) in TASK_DECORATOR_NAMES for item in node.decorator_list)
    }


def collect_shared_task_functions(path: Path) -> set[str]:
    """Collect every function decorated with ``shared_task``."""

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
    """Index registered and explicitly exempt task names by source file."""

    registered: dict[str, set[str]] = {}
    for collection_name in ("tasks", "exemptions"):
        raw_tasks = payload.get(collection_name)
        if not isinstance(raw_tasks, list):
            continue
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                continue
            source_file = raw_task.get("source_file")
            task_path = raw_task.get("task_path")
            if isinstance(source_file, str) and isinstance(task_path, str):
                registered.setdefault(source_file, set()).add(task_path.rsplit(".", 1)[-1])
    return registered


def _canonical_task_path(source_file: str, task_name: str) -> str:
    """Return the import path implied by one Application source file and symbol."""

    module = source_file.removesuffix(".py").replace("/", ".").replace("\\", ".")
    return f"{module}.{task_name}"


def _allowed_registered_task_paths(
    *,
    repo_root: Path,
    source_file: str,
    task_name: str,
) -> set[str]:
    """Return source-canonical plus literal decorator task paths for one symbol."""

    allowed: set[str] = set()
    source_path = repo_root / source_file
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError):
        return {_canonical_task_path(source_file, task_name)}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.name != task_name:
            continue
        allowed.add(_canonical_task_path(source_file, task_name))
        for decorator in node.decorator_list:
            explicit_name = _explicit_task_name(decorator)
            if explicit_name is not None:
                allowed.add(explicit_name)
    return allowed


def collect_application_shared_tasks(
    repo_root: Path,
    *,
    violations: list[ContractViolation] | None = None,
) -> dict[str, set[str]]:
    """Discover every shared task below every app's Application layer."""

    discovered: dict[str, set[str]] = {}
    apps_root = repo_root / "apps"
    if not apps_root.is_dir():
        return discovered
    for source_path in sorted(apps_root.glob("*/application/**/*.py")):
        try:
            source = source_path.read_text(encoding="utf-8")
            task_names = collect_shared_task_functions_from_source(
                source,
                filename=str(source_path),
            )
            nested_task_names = collect_nested_shared_task_functions_from_source(
                source,
                filename=str(source_path),
            )
        except (OSError, SyntaxError) as exc:
            if violations is not None:
                source_file = source_path.relative_to(repo_root).as_posix()
                violations.append(ContractViolation("source_parse_error", f"{source_file}: {exc}"))
            continue
        if task_names:
            source_file = source_path.relative_to(repo_root).as_posix()
            discovered[source_file] = task_names
            if violations is not None:
                for task_name in sorted(nested_task_names):
                    violations.append(
                        ContractViolation(
                            "nested_shared_task",
                            f"{source_file}: shared task {task_name} must be module-level",
                        )
                    )
    return discovered


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
    raw_exemptions = payload.get("exemptions", [])
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
    if not isinstance(raw_exemptions, list):
        violations.append(ContractViolation("exemptions", "exemptions must be a list"))
        raw_exemptions = []

    registered_by_file: dict[str, set[str]] = {}
    seen_task_paths: set[str] = set()
    seen_covered_paths: set[str] = set()
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
        seen_covered_paths.add(task_path)

        if not isinstance(source_file, str) or not source_file:
            violations.append(
                ContractViolation("source_file", f"{task_path}: source_file is required")
            )
            continue
        task_name = task_path.rsplit(".", 1)[-1]
        registered_by_file.setdefault(source_file, set()).add(task_name)
        if task_path not in _allowed_registered_task_paths(
            repo_root=repo_root,
            source_file=source_file,
            task_name=task_name,
        ):
            violations.append(
                ContractViolation(
                    "task_path_mismatch",
                    f"{task_path}: path does not match {source_file}",
                )
            )

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

    exempted_by_file: dict[str, set[str]] = {}
    exemption_targets: list[tuple[str, str]] = []
    for index, raw_exemption in enumerate(raw_exemptions):
        label = f"exemptions[{index}]"
        if not isinstance(raw_exemption, dict):
            violations.append(ContractViolation("exemption_invalid", f"{label} must be an object"))
            continue
        task_path = raw_exemption.get("task_path")
        source_file = raw_exemption.get("source_file")
        owner = raw_exemption.get("owner")
        reason = raw_exemption.get("reason")
        compatibility_target = raw_exemption.get("compatibility_target")
        if not isinstance(task_path, str) or not task_path:
            violations.append(
                ContractViolation("exemption_task_path", f"{label}.task_path is required")
            )
            continue
        if task_path in seen_covered_paths:
            violations.append(
                ContractViolation("task_duplicate", f"duplicate covered task_path: {task_path}")
            )
        seen_covered_paths.add(task_path)
        if not isinstance(source_file, str) or not source_file:
            violations.append(
                ContractViolation("exemption_source_file", f"{task_path}: source_file is required")
            )
            continue
        task_name = task_path.rsplit(".", 1)[-1]
        exempted_by_file.setdefault(source_file, set()).add(task_name)
        if task_path != _canonical_task_path(source_file, task_name) or task_path not in (
            _allowed_registered_task_paths(
                repo_root=repo_root,
                source_file=source_file,
                task_name=task_name,
            )
        ):
            violations.append(
                ContractViolation(
                    "exemption_task_path",
                    f"{task_path}: path does not match {source_file}",
                )
            )
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
            violations.append(
                ContractViolation("exemption_owner", f"{task_path}: bounded owner is required")
            )
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            violations.append(
                ContractViolation(
                    "exemption_reason",
                    f"{task_path}: auditable compatibility reason is required",
                )
            )
        if not isinstance(compatibility_target, str) or not compatibility_target:
            violations.append(
                ContractViolation(
                    "exemption_target",
                    f"{task_path}: compatibility_target is required",
                )
            )
        else:
            exemption_targets.append((task_path, compatibility_target))

    for task_path, target in exemption_targets:
        if target == task_path or target not in seen_task_paths:
            violations.append(
                ContractViolation(
                    "exemption_target",
                    f"{task_path}: compatibility target {target!r} must be a registered task",
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
        registered = registered_by_file.get(source_file, set()) | exempted_by_file.get(
            source_file, set()
        )
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

    all_discovered = collect_application_shared_tasks(repo_root, violations=violations)
    covered_by_file: dict[str, set[str]] = {}
    for source_file, task_names in registered_by_file.items():
        covered_by_file.setdefault(source_file, set()).update(task_names)
    for source_file, task_names in exempted_by_file.items():
        covered_by_file.setdefault(source_file, set()).update(task_names)
    for source_file, task_names in all_discovered.items():
        covered = covered_by_file.get(source_file, set())
        for task_name in sorted(task_names - covered):
            violations.append(
                ContractViolation(
                    "unregistered_application_task",
                    f"{source_file}: shared task {task_name} requires a contract or exemption",
                )
            )
    for source_file, task_names in covered_by_file.items():
        discovered = all_discovered.get(source_file, set())
        for task_name in sorted(task_names - discovered):
            violations.append(
                ContractViolation(
                    "covered_task_not_found",
                    f"{source_file}: covered task {task_name} is not a shared task",
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
        f"{len(payload.get('tasks', []))} registered task(s), "
        f"{len(payload.get('exemptions', []))} exemption(s), "
        f"{len(payload.get('governed_source_files', []))} governed file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
