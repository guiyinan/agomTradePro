"""Pure contracts for Config Center-owned regional egress endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EgressEndpointInput:
    """Validated operator input for creating or updating an endpoint."""

    name: str | None = None
    region: str | None = None
    protocol: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    enabled: bool | None = None
    concurrency_limit: int | None = None
    clear_credentials: bool = False


@dataclass(frozen=True, slots=True)
class EgressEndpoint:
    """Resolved endpoint used by an infrastructure transport composition root."""

    id: int
    name: str
    region: str
    protocol: str
    host: str
    port: int
    username: str
    password: str
    enabled: bool
    concurrency_limit: int
    username_configured: bool
    password_configured: bool
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class EgressEndpointSummary:
    """Non-secret endpoint projection safe for user-facing responses."""

    id: int
    name: str
    region: str
    protocol: str
    host: str
    port: int
    enabled: bool
    concurrency_limit: int
    username_configured: bool
    password_configured: bool
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        """Return a redacted endpoint projection."""

        return {
            "id": self.id,
            "name": self.name,
            "region": self.region,
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "enabled": self.enabled,
            "concurrency_limit": self.concurrency_limit,
            "username_configured": self.username_configured,
            "password_configured": self.password_configured,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class EgressEndpointRepositoryProtocol(Protocol):
    """Application port implemented by Config Center infrastructure."""

    def list(self, *, include_disabled: bool = True) -> tuple[EgressEndpointSummary, ...]:
        """List endpoint metadata without resolving credentials."""
        ...

    def get(self, endpoint_id: int, *, resolve_credentials: bool = True) -> EgressEndpoint | None:
        """Read one endpoint with optional credential resolution."""
        ...

    def get_summary(self, endpoint_id: int) -> EgressEndpointSummary | None:
        """Read one endpoint without resolving credentials."""
        ...

    def create(self, payload: EgressEndpointInput) -> EgressEndpoint:
        """Create one endpoint."""
        ...

    def update(self, endpoint_id: int, payload: EgressEndpointInput) -> EgressEndpoint | None:
        """Update one endpoint."""
        ...

    def delete(self, endpoint_id: int) -> bool:
        """Delete one endpoint."""
        ...


__all__ = [
    "EgressEndpoint",
    "EgressEndpointInput",
    "EgressEndpointRepositoryProtocol",
    "EgressEndpointSummary",
]
