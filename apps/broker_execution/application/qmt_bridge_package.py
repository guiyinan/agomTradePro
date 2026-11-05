"""Application boundary for downloading the versioned Windows QMT bridge package."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .authorization import require_action
from .use_case_errors import BrokerExecutionNotFoundError


@dataclass(frozen=True)
class QmtBridgePackage:
    """Verified local package metadata and its server-local file location."""

    path: Path
    version: str
    filename: str
    size_bytes: int
    sha256: str


class QmtBridgePackageProvider(Protocol):
    """Locate the current bridge package without exposing arbitrary file paths."""

    def locate(self) -> QmtBridgePackage | None:
        """Return the current verified package or None when it has not been built."""
        ...


_provider_factory: Callable[[], QmtBridgePackageProvider] | None = None


def configure_qmt_bridge_package_provider(
    factory: Callable[[], QmtBridgePackageProvider],
) -> None:
    """Configure the infrastructure package provider at application startup."""

    global _provider_factory
    _provider_factory = factory


def get_qmt_bridge_package_provider() -> QmtBridgePackageProvider:
    """Return the configured package provider."""

    if _provider_factory is None:
        raise RuntimeError("QMT bridge package provider is not configured")
    return _provider_factory()


class QmtBridgePackageService:
    """Authorize administrator package inspection and download."""

    def __init__(self, provider: QmtBridgePackageProvider | None = None) -> None:
        self.provider = provider or get_qmt_bridge_package_provider()

    def get(self, *, actor: Any) -> QmtBridgePackage:
        """Return the current package for an administrator or raise a stable 404."""

        require_action(actor, "manage_binding")
        package = self.provider.locate()
        if package is None:
            raise BrokerExecutionNotFoundError("QMT bridge package is not available")
        return package
