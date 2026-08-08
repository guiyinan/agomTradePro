"""Tests for incremental quality target selection."""

import subprocess
from unittest.mock import patch

from scripts.select_quality_targets import (
    get_changed_files,
    select_domain_coverage_targets,
    select_lint_targets,
    select_typecheck_targets,
)


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
