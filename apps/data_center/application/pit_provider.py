"""Data Center-owned PIT provider registry.

Point-in-time manifests are canonical data evidence, so their provider
registry belongs to Data Center rather than ``core.integration``.  Consumers
depend on these application functions and never construct the ORM view.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_view_factory: Callable[[str], Any] | None = None
_manifest_evidence_getter: Callable[[str], dict[str, Any] | None] | None = None


def configure_pit_providers(
    *,
    view_factory: Callable[[str], Any],
    manifest_evidence_getter: Callable[[str], dict[str, Any] | None],
) -> None:
    """Register Data Center PIT providers at application startup."""

    global _view_factory, _manifest_evidence_getter
    _view_factory = view_factory
    _manifest_evidence_getter = manifest_evidence_getter


def make_manifest_bound_pit_view(manifest_id: str) -> Any:
    """Return a manifest-bound point-in-time read view."""

    if _view_factory is None:
        raise RuntimeError("PIT provider is not configured")
    return _view_factory(manifest_id)


def get_pit_manifest_evidence(manifest_id: str) -> dict[str, Any] | None:
    """Return manifest evidence for audit and reproducibility checks."""

    if _manifest_evidence_getter is None:
        raise RuntimeError("PIT manifest provider is not configured")
    return _manifest_evidence_getter(manifest_id)


__all__ = [
    "configure_pit_providers",
    "get_pit_manifest_evidence",
    "make_manifest_bound_pit_view",
]
