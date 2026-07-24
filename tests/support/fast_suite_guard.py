"""Pytest plugin that prevents database-bound tests from entering the fast suite."""

from __future__ import annotations

from collections.abc import Iterable
from inspect import signature

import pytest

FORBIDDEN_FIXTURES = frozenset(
    {
        "admin_client",
        "admin_user",
        "authenticated_client",
        "async_client",
        "client",
        "db",
        "django_assert_num_queries",
        "django_db_blocker",
        "django_db_reset_sequences",
        "django_user_model",
        "live_server",
        "transactional_db",
    }
)


def pytest_collection_modifyitems(items: Iterable[pytest.Item]) -> None:
    """Reject database markers and fixtures before pytest-django creates a database."""
    violations: list[str] = []
    for item in items:
        test_callable = getattr(item, "obj", None)
        fixture_names = (
            set(signature(test_callable).parameters) if callable(test_callable) else set()
        )
        forbidden = sorted(fixture_names & FORBIDDEN_FIXTURES)
        has_django_db = item.get_closest_marker("django_db") is not None
        if forbidden or has_django_db:
            details = []
            if forbidden:
                details.append(f"fixtures={','.join(forbidden)}")
            if has_django_db:
                details.append("marker=django_db")
            violations.append(f"{item.nodeid} ({'; '.join(details)})")
    if violations:
        formatted = "\n".join(f"- {violation}" for violation in violations)
        raise pytest.UsageError(f"Fast suite contains database-bound tests:\n{formatted}")
