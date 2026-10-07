"""Tests for incremental quality target selection."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.select_quality_targets import (
    get_changed_files,
    select_domain_coverage_targets,
    select_lint_targets,
    select_runtime_inputs,
    select_typecheck_targets,
)


def test_prose_only_changes_do_not_require_runtime_validation() -> None:
    assert select_runtime_inputs(["README.md", "docs/development/quick-reference.md"]) == []


@pytest.mark.parametrize(
    "path",
    [
        "apps/account/domain/entities.py",
        "apps/terminal/prompts/instructions.md",
        "docs/deployment/evidence.json",
        "governance/module_map.json",
        "AGENTS.md",
        ".agents/skills/deploy/SKILL.md",
        "pyproject.toml",
        "requirements-dev.txt",
        ".github/workflows/ci-fast-feedback.yml",
        "tests/conftest.py",
        "unknown/new-file",
    ],
)
def test_runtime_or_unknown_inputs_keep_full_validation(path: str) -> None:
    assert select_runtime_inputs(["README.md", path]) == [path]


def test_empty_diff_cannot_claim_prose_only_scope() -> None:
    assert select_runtime_inputs([])


def test_runtime_scope_includes_deleted_and_renamed_code(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Scope Test")
    (tmp_path / "source.py").write_text("pass\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "initial")
    base = git("rev-parse", "HEAD")
    git("mv", "source.py", "README.md")
    git("commit", "-m", "rename code to prose")
    with patch("scripts.select_quality_targets.Path.cwd", return_value=tmp_path):
        changed = get_changed_files(base, "HEAD", include_deleted=True)
    assert set(changed) == {"source.py", "README.md"}
    assert select_runtime_inputs(changed) == ["source.py"]


def test_invalid_diff_fails_instead_of_returning_no_targets() -> None:
    with (
        patch(
            "scripts.select_quality_targets.subprocess.run",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ),
        pytest.raises(subprocess.CalledProcessError),
    ):
        get_changed_files("missing-ref", "HEAD", include_deleted=True)


def test_get_changed_files_excludes_deleted_paths_from_quality_targets() -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="apps/account/domain/entities.py\n",
        stderr="",
    )

    with patch("scripts.select_quality_targets.subprocess.run", return_value=completed) as run:
        changed_files = get_changed_files("origin/main", "HEAD")

    assert changed_files == ["apps/account/domain/entities.py"]
    assert run.call_args.args[0] == [
        "git",
        "diff",
        "--name-only",
        "--diff-filter=ACMRT",
        "origin/main...HEAD",
    ]


def test_select_lint_targets_includes_changed_python_files_under_supported_roots() -> None:
    changed_files = [
        "apps/account/domain/entities.py",
        "core/views.py",
        "scripts/select_tests.py",
        "tests/unit/test_example.py",
        "sdk/agomtradepro/client.py",
        "README.md",
    ]

    assert select_lint_targets(changed_files) == [
        "apps/account/domain/entities.py",
        "core/views.py",
        "scripts/select_tests.py",
        "sdk/agomtradepro/client.py",
        "tests/unit/test_example.py",
    ]


def test_select_typecheck_targets_excludes_tests_and_migrations() -> None:
    changed_files = [
        "apps/account/domain/entities.py",
        "apps/account/migrations/0001_initial.py",
        "apps/account/tests/test_entities.py",
        "core/views.py",
        "shared/domain/interfaces.py",
        "scripts/select_tests.py",
    ]

    assert select_typecheck_targets(changed_files) == [
        "apps/account/domain/entities.py",
        "core/views.py",
        "shared/domain/interfaces.py",
    ]


def test_select_domain_coverage_targets_normalizes_packages() -> None:
    changed_files = [
        "apps/account/domain/entities.py",
        "apps/account/domain/services.py",
        "apps/account/domain/subpkg/__init__.py",
        "apps/account/tests/test_entities.py",
        "apps/account/application/use_cases.py",
    ]

    assert select_domain_coverage_targets(changed_files) == [
        "apps.account.domain",
    ]
