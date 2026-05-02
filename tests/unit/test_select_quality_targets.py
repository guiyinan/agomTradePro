"""Tests for incremental quality target selection."""

from scripts.select_quality_targets import (
    select_domain_coverage_targets,
    select_lint_targets,
    select_typecheck_targets,
)


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
        "apps.account.domain.entities",
        "apps.account.domain.services",
        "apps.account.domain.subpkg",
    ]
