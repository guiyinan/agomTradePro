"""Data Center-owned PIT provider registry.

Point-in-time manifests are canonical data evidence, so their provider
registry belongs to Data Center rather than ``core.integration``.  Consumers
depend on these application functions and never construct the ORM view.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

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


@dataclass(frozen=True, slots=True)
class PITManifestBinding:
    """Verified exact-version identity, excluding payloads and outcome values."""

    manifest_id: str
    manifest_hash: str
    calendar_version: str
    as_of_time: datetime
    knowledge_scope: str
    coverage: tuple[tuple[str, float], ...]
    versions_sha256: str


@runtime_checkable
class _BindingView(Protocol):
    def get_manifest_binding(self) -> PITManifestBinding:
        """Expose an exact-version identity already verified by the provider."""
        ...


def get_verified_pit_manifest_binding(manifest_id: str) -> PITManifestBinding:
    """Verify exact retained versions through the configured manifest-bound view."""
    view: object = make_manifest_bound_pit_view(manifest_id)
    if not isinstance(view, _BindingView):
        raise ValueError("PIT manifest binding provider is unavailable")
    binding = view.get_manifest_binding()
    if not isinstance(binding, PITManifestBinding) or binding.manifest_id != manifest_id:
        raise ValueError("PIT manifest binding identity differs")
    return binding


__all__ = [
    "configure_pit_providers",
    "get_pit_manifest_evidence",
    "make_manifest_bound_pit_view",
    "PITManifestBinding",
    "get_verified_pit_manifest_binding",
]
