"""Public Config Center application ports for regional egress endpoints."""

from __future__ import annotations

from collections.abc import Mapping

from apps.config_center.domain.egress import (
    EgressEndpoint,
    EgressEndpointInput,
    EgressEndpointRepositoryProtocol,
    EgressEndpointSummary,
)

_repository: EgressEndpointRepositoryProtocol | None = None


def configure_egress_endpoint_repository(repository: EgressEndpointRepositoryProtocol) -> None:
    """Install the Config Center infrastructure implementation at composition time."""

    global _repository
    _repository = repository


def _get_repository() -> EgressEndpointRepositoryProtocol:
    """Return the configured repository or fail closed before app startup."""

    if _repository is None:
        raise RuntimeError("config_center_egress_repository_unconfigured")
    return _repository


def _input(payload: Mapping[str, object], *, partial: bool) -> EgressEndpointInput:
    """Convert an untrusted API mapping into the endpoint input boundary."""

    def optional_text(key: str) -> str | None:
        value = payload.get(key)
        if value is None and partial:
            return None
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError(f"invalid_egress_{key}")
        return value

    def optional_int(key: str) -> int | None:
        value = payload.get(key)
        if value is None and partial:
            return None
        if value is None:
            raise ValueError(f"invalid_egress_{key}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"invalid_egress_{key}")
        return value

    def optional_bool(key: str) -> bool | None:
        value = payload.get(key)
        if value is None and partial:
            return None
        if value is None:
            return False
        if not isinstance(value, bool):
            raise ValueError(f"invalid_egress_{key}")
        return value

    clear = payload.get("clear_credentials", False)
    if not isinstance(clear, bool):
        raise ValueError("invalid_egress_clear_credentials")
    return EgressEndpointInput(
        name=optional_text("name"),
        region=optional_text("region"),
        protocol=optional_text("protocol"),
        host=optional_text("host"),
        port=optional_int("port"),
        username=optional_text("username"),
        password=optional_text("password"),
        enabled=optional_bool("enabled"),
        concurrency_limit=optional_int("concurrency_limit"),
        clear_credentials=clear,
    )


def list_egress_endpoints(*, include_disabled: bool = True) -> tuple[EgressEndpointSummary, ...]:
    """List Config Center-owned egress metadata without decrypting credentials."""

    return _get_repository().list(include_disabled=include_disabled)


def get_egress_endpoint(endpoint_id: int) -> EgressEndpoint | None:
    """Resolve one endpoint for an infrastructure transport composition root."""

    return _get_repository().get(endpoint_id, resolve_credentials=True)


def get_egress_endpoint_summary(endpoint_id: int) -> EgressEndpointSummary | None:
    """Read one endpoint without resolving credentials."""

    return _get_repository().get_summary(endpoint_id)


def create_egress_endpoint(payload: Mapping[str, object]) -> EgressEndpointSummary:
    """Create one endpoint and return only its redacted projection."""

    endpoint = _get_repository().create(_input(payload, partial=False))
    return _summary_from_resolved(endpoint)


def update_egress_endpoint(
    endpoint_id: int, payload: Mapping[str, object]
) -> EgressEndpointSummary | None:
    """Update endpoint metadata while retaining omitted or blank credentials."""

    endpoint = _get_repository().update(endpoint_id, _input(payload, partial=True))
    return _summary_from_resolved(endpoint) if endpoint is not None else None


def delete_egress_endpoint(endpoint_id: int) -> bool:
    """Delete endpoint metadata and its encrypted credential references."""

    return _get_repository().delete(endpoint_id)


def _summary_from_resolved(endpoint: EgressEndpoint) -> EgressEndpointSummary:
    """Project a resolved endpoint into the public non-secret DTO."""

    return EgressEndpointSummary(
        id=endpoint.id,
        name=endpoint.name,
        region=endpoint.region,
        protocol=endpoint.protocol,
        host=endpoint.host,
        port=endpoint.port,
        enabled=endpoint.enabled,
        concurrency_limit=endpoint.concurrency_limit,
        username_configured=endpoint.username_configured,
        password_configured=endpoint.password_configured,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


__all__ = [
    "EgressEndpoint",
    "EgressEndpointSummary",
    "configure_egress_endpoint_repository",
    "create_egress_endpoint",
    "delete_egress_endpoint",
    "get_egress_endpoint",
    "get_egress_endpoint_summary",
    "list_egress_endpoints",
    "update_egress_endpoint",
]
