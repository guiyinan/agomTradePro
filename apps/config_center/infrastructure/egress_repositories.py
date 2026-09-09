"""Config Center repository for outbound egress endpoints."""

from __future__ import annotations

import ipaddress
import re

from django.db import transaction

from apps.config_center.domain.egress import (
    EgressEndpoint,
    EgressEndpointInput,
    EgressEndpointSummary,
)

from .egress_models import EgressEndpointModel
from .secret_store import ConfigCenterSecretStore

_HOSTNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,253}[A-Za-z0-9])?$")


def _secret_ref(endpoint_id: int, field_name: str) -> str:
    """Build a stable Config Center-owned reference for one credential."""

    return f"config_center.egress.endpoint.{endpoint_id}.{field_name}"


def _valid_proxy_host(value: str) -> bool:
    """Validate a proxy host without resolving it or rejecting Docker names."""

    if not value or len(value) > 255 or any(character in value for character in "@/?#"):
        return False
    candidate = value[1:-1] if value.startswith("[") and value.endswith("]") else value
    if not candidate or any(character.isspace() for character in candidate):
        return False
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return bool(_HOSTNAME_PATTERN.fullmatch(candidate))
    return True


class EgressEndpointRepository:
    """Persist endpoint metadata and delegate credential encryption to the store."""

    def __init__(self, *, secret_store: ConfigCenterSecretStore | None = None) -> None:
        self._secret_store = secret_store or ConfigCenterSecretStore()

    @staticmethod
    def _validate_metadata(
        *,
        name: str,
        region: str,
        protocol: str,
        host: str,
        port: int,
        concurrency_limit: int,
    ) -> tuple[str, str, str, str, int, int]:
        normalized_name = str(name or "").strip()
        normalized_region = str(region or "").strip().lower()
        normalized_protocol = str(protocol or "").strip().lower()
        normalized_host = str(host or "").strip()
        if not normalized_name or len(normalized_name) > 120:
            raise ValueError("invalid_egress_name")
        if not normalized_region or len(normalized_region) > 40:
            raise ValueError("invalid_egress_region")
        if normalized_protocol not in {"http", "https"}:
            raise ValueError("invalid_egress_protocol")
        if not _valid_proxy_host(normalized_host):
            raise ValueError("invalid_egress_host")
        if isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("invalid_egress_port")
        if isinstance(concurrency_limit, bool) or not 1 <= concurrency_limit <= 512:
            raise ValueError("invalid_egress_concurrency_limit")
        return (
            normalized_name,
            normalized_region,
            normalized_protocol,
            normalized_host,
            port,
            concurrency_limit,
        )

    def list(self, *, include_disabled: bool = True) -> tuple[EgressEndpointSummary, ...]:
        """Return redacted endpoints ordered by name and identifier."""

        queryset = EgressEndpointModel._default_manager.all()
        if not include_disabled:
            queryset = queryset.filter(enabled=True)
        return tuple(self._summary(model) for model in queryset)

    def get(self, endpoint_id: int, *, resolve_credentials: bool = True) -> EgressEndpoint | None:
        """Read one endpoint, optionally resolving its encrypted credentials."""

        model = EgressEndpointModel._default_manager.filter(pk=endpoint_id).first()
        if model is None:
            return None
        username = (
            self._secret_store.resolve(model.username_secret_ref)
            if resolve_credentials and model.username_secret_ref
            else ""
        )
        password = (
            self._secret_store.resolve(model.password_secret_ref)
            if resolve_credentials and model.password_secret_ref
            else ""
        )
        return EgressEndpoint(
            id=int(model.pk),
            name=model.name,
            region=model.region,
            protocol=model.protocol,
            host=model.host,
            port=int(model.port),
            username=username,
            password=password,
            enabled=bool(model.enabled),
            concurrency_limit=int(model.concurrency_limit),
            username_configured=bool(model.username_secret_ref),
            password_configured=bool(model.password_secret_ref),
            created_at=model.created_at.isoformat(),
            updated_at=model.updated_at.isoformat(),
        )

    def get_summary(self, endpoint_id: int) -> EgressEndpointSummary | None:
        """Read one endpoint as a redacted projection."""

        model = EgressEndpointModel._default_manager.filter(pk=endpoint_id).first()
        return self._summary(model) if model is not None else None

    def create(self, payload: EgressEndpointInput) -> EgressEndpoint:
        """Create an endpoint and encrypt supplied credentials."""

        required = (
            payload.name,
            payload.region,
            payload.protocol,
            payload.host,
            payload.port,
            payload.concurrency_limit,
        )
        if any(value is None for value in required):
            raise ValueError("egress_endpoint_fields_required")
        assert payload.name is not None
        assert payload.region is not None
        assert payload.protocol is not None
        assert payload.host is not None
        assert payload.port is not None
        assert payload.concurrency_limit is not None
        metadata = self._validate_metadata(
            name=payload.name,
            region=payload.region,
            protocol=payload.protocol,
            host=payload.host,
            port=payload.port,
            concurrency_limit=payload.concurrency_limit,
        )
        with transaction.atomic():
            model = EgressEndpointModel._default_manager.create(
                name=metadata[0],
                region=metadata[1],
                protocol=metadata[2],
                host=metadata[3],
                port=metadata[4],
                enabled=bool(payload.enabled),
                concurrency_limit=metadata[5],
            )
            self._persist_credentials(model, payload, creating=True)
        result = self.get(int(model.pk))
        if result is None:  # pragma: no cover - transaction guarantees the row
            raise RuntimeError("egress_endpoint_create_failed")
        return result

    def update(self, endpoint_id: int, payload: EgressEndpointInput) -> EgressEndpoint | None:
        """Apply a partial metadata update and preserve omitted credentials."""

        with transaction.atomic():
            model = (
                EgressEndpointModel._default_manager.select_for_update()
                .filter(pk=endpoint_id)
                .first()
            )
            if model is None:
                return None
            name = payload.name if payload.name is not None else model.name
            region = payload.region if payload.region is not None else model.region
            protocol = payload.protocol if payload.protocol is not None else model.protocol
            host = payload.host if payload.host is not None else model.host
            port = payload.port if payload.port is not None else int(model.port)
            concurrency_limit = (
                payload.concurrency_limit
                if payload.concurrency_limit is not None
                else int(model.concurrency_limit)
            )
            metadata = self._validate_metadata(
                name=name,
                region=region,
                protocol=protocol,
                host=host,
                port=port,
                concurrency_limit=concurrency_limit,
            )
            model.name, model.region, model.protocol, model.host = metadata[:4]
            model.port, model.concurrency_limit = metadata[4], metadata[5]
            if payload.enabled is not None:
                model.enabled = payload.enabled
            model.save(
                update_fields=[
                    "name",
                    "region",
                    "protocol",
                    "host",
                    "port",
                    "concurrency_limit",
                    "enabled",
                    "updated_at",
                ]
            )
            self._persist_credentials(model, payload, creating=False)
        return self.get(endpoint_id)

    def delete(self, endpoint_id: int) -> bool:
        """Delete endpoint metadata and its encrypted credential records."""

        model = EgressEndpointModel._default_manager.filter(pk=endpoint_id).first()
        if model is None:
            return False
        with transaction.atomic():
            model.delete()
            for field_name in ("username", "password"):
                self._secret_store.persist(_secret_ref(endpoint_id, field_name), "")
        return True

    def _persist_credentials(
        self, model: EgressEndpointModel, payload: EgressEndpointInput, *, creating: bool
    ) -> None:
        """Persist write-only credentials without ever returning them."""

        if payload.clear_credentials:
            self._secret_store.persist(_secret_ref(int(model.pk), "username"), "")
            self._secret_store.persist(_secret_ref(int(model.pk), "password"), "")
            model.username_secret_ref = ""
            model.password_secret_ref = ""
        if creating:
            username_ref = _secret_ref(int(model.pk), "username")
            password_ref = _secret_ref(int(model.pk), "password")
            self._secret_store.persist(username_ref, payload.username or "")
            self._secret_store.persist(password_ref, payload.password or "")
            model.username_secret_ref = username_ref if payload.username else ""
            model.password_secret_ref = password_ref if payload.password else ""
        elif not payload.clear_credentials:
            # Blank write-only form inputs preserve the previous value.  The
            # explicit clear_credentials flag is the only way to remove it.
            if payload.username:
                username_ref = _secret_ref(int(model.pk), "username")
                self._secret_store.persist(username_ref, payload.username)
                model.username_secret_ref = username_ref
            if payload.password:
                password_ref = _secret_ref(int(model.pk), "password")
                self._secret_store.persist(password_ref, payload.password)
                model.password_secret_ref = password_ref
        model.save(update_fields=["username_secret_ref", "password_secret_ref", "updated_at"])

    def _summary(self, model: EgressEndpointModel) -> EgressEndpointSummary:
        """Convert a model to an API-safe summary."""

        return EgressEndpointSummary(
            id=int(model.pk),
            name=model.name,
            region=model.region,
            protocol=model.protocol,
            host=model.host,
            port=int(model.port),
            enabled=bool(model.enabled),
            concurrency_limit=int(model.concurrency_limit),
            username_configured=bool(model.username_secret_ref),
            password_configured=bool(model.password_secret_ref),
            created_at=model.created_at.isoformat(),
            updated_at=model.updated_at.isoformat(),
        )


__all__ = [
    "EgressEndpoint",
    "EgressEndpointInput",
    "EgressEndpointRepository",
    "EgressEndpointSummary",
]
