"""App-neutral bridge for Config Center-owned egress endpoint ports.

Config Center owns endpoint persistence and credential resolution.  Consumers
such as Data Center depend on this narrow bridge so that application modules do
not import one another directly.  The Config Center app registers its adapter
at startup through :func:`configure_config_center_egress_port`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class EgressEndpointSummary(Protocol):
    """Redacted endpoint projection safe for user-facing responses."""

    @property
    def id(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def region(self) -> str: ...

    @property
    def protocol(self) -> str: ...

    @property
    def host(self) -> str: ...

    @property
    def port(self) -> int: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def concurrency_limit(self) -> int: ...

    @property
    def username_configured(self) -> bool: ...

    @property
    def password_configured(self) -> bool: ...

    @property
    def created_at(self) -> str: ...

    @property
    def updated_at(self) -> str: ...

    def to_dict(self) -> dict[str, object]:
        """Return the redacted endpoint projection."""
        ...


class EgressEndpoint(Protocol):
    """Resolved endpoint contract used by infrastructure transports."""

    @property
    def id(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def region(self) -> str: ...

    @property
    def protocol(self) -> str: ...

    @property
    def host(self) -> str: ...

    @property
    def port(self) -> int: ...

    @property
    def username(self) -> str: ...

    @property
    def password(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def concurrency_limit(self) -> int: ...

    @property
    def username_configured(self) -> bool: ...

    @property
    def password_configured(self) -> bool: ...

    @property
    def created_at(self) -> str: ...

    @property
    def updated_at(self) -> str: ...


class ConfigCenterEgressPort(Protocol):
    """Config Center endpoint operations exposed at the app-neutral boundary."""

    def list_endpoints(self, *, include_disabled: bool = True) -> tuple[EgressEndpointSummary, ...]:
        """List endpoint metadata without resolving credentials."""
        ...

    def get_endpoint(self, endpoint_id: int) -> EgressEndpoint | None:
        """Resolve one endpoint for an infrastructure transport."""
        ...

    def get_endpoint_summary(self, endpoint_id: int) -> EgressEndpointSummary | None:
        """Read one endpoint without resolving credentials."""
        ...

    def create_endpoint(self, payload: Mapping[str, object]) -> EgressEndpointSummary:
        """Create one endpoint and return its redacted projection."""
        ...

    def update_endpoint(
        self, endpoint_id: int, payload: Mapping[str, object]
    ) -> EgressEndpointSummary | None:
        """Update one endpoint and return its redacted projection."""
        ...

    def delete_endpoint(self, endpoint_id: int) -> bool:
        """Delete one endpoint and its encrypted credential references."""
        ...


_provider: ConfigCenterEgressPort | None = None


def configure_config_center_egress_port(provider: ConfigCenterEgressPort) -> None:
    """Register the Config Center-owned egress adapter at composition time."""

    global _provider
    _provider = provider


def _get_provider() -> ConfigCenterEgressPort:
    """Return the configured adapter or fail closed before app startup."""

    if _provider is None:
        raise RuntimeError("config_center_egress_port_unconfigured")
    return _provider


def list_egress_endpoints(*, include_disabled: bool = True) -> tuple[EgressEndpointSummary, ...]:
    """List Config Center-owned endpoint metadata."""

    return _get_provider().list_endpoints(include_disabled=include_disabled)


def get_egress_endpoint(endpoint_id: int) -> EgressEndpoint | None:
    """Resolve one endpoint for an infrastructure transport."""

    return _get_provider().get_endpoint(endpoint_id)


def get_egress_endpoint_summary(endpoint_id: int) -> EgressEndpointSummary | None:
    """Read one endpoint without resolving credentials."""

    return _get_provider().get_endpoint_summary(endpoint_id)


def create_egress_endpoint(payload: Mapping[str, object]) -> EgressEndpointSummary:
    """Create one endpoint and return its redacted projection."""

    return _get_provider().create_endpoint(payload)


def update_egress_endpoint(
    endpoint_id: int, payload: Mapping[str, object]
) -> EgressEndpointSummary | None:
    """Update one endpoint and return its redacted projection."""

    return _get_provider().update_endpoint(endpoint_id, payload)


def delete_egress_endpoint(endpoint_id: int) -> bool:
    """Delete one endpoint and its encrypted credential references."""

    return _get_provider().delete_endpoint(endpoint_id)


__all__ = [
    "ConfigCenterEgressPort",
    "EgressEndpoint",
    "EgressEndpointSummary",
    "configure_config_center_egress_port",
    "create_egress_endpoint",
    "delete_egress_endpoint",
    "get_egress_endpoint",
    "get_egress_endpoint_summary",
    "list_egress_endpoints",
    "update_egress_endpoint",
]
