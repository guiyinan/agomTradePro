"""Export contract for the policy infrastructure repository surface.

Locks the explicit re-export surface of
``apps.policy.infrastructure.repositories`` so that ``providers.py`` (which
star-imports it) keeps resolving every name consumed by application
composition roots.
"""

from __future__ import annotations

EXPECTED_REPOSITORY_EXPORTS = {
    "DjangoPolicyRepository",
    "HedgePositionRepository",
    "PolicyRepositoryError",
    "RSSRepository",
    "WorkbenchRepository",
    "get_policy_repository",
    "get_workbench_repository",
}


def test_policy_repositories_export_surface_is_explicit_and_complete() -> None:
    """providers.py star import must resolve every composition-root name."""
    from apps.policy.infrastructure import providers, repositories

    assert set(repositories.__all__) == EXPECTED_REPOSITORY_EXPORTS
    for name in EXPECTED_REPOSITORY_EXPORTS:
        assert getattr(providers, name) is getattr(repositories, name)
