"""Shared database isolation for MigrationExecutor tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _preserve_serialized_migration_baseline(
    django_db_serialized_rollback: None,
) -> None:
    """Use one rollback mode so transaction tests cannot pollute the next restore.

    Migration tests repeatedly move the schema away from the leaf state and then
    restore it.  Mixing serialized and ordinary ``TransactionTestCase`` teardown
    modes recreates content types between tests; the next serialized restore then
    collides with those rows.  Requesting pytest-django's serialized rollback
    fixture for the whole migration-test directory keeps teardown semantics
    consistent while preserving seed data created by data migrations.
    """
