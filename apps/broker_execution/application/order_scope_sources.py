"""Typed owner interfaces for reviewing and signing one retained Broker order."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from django.contrib.auth.models import User
from rest_framework.request import Request

from .checkpoint_authority import BrokerCheckpointIntent
from .use_case_errors import BrokerExecutionConflictError


@dataclass(frozen=True, slots=True)
class OrderArtifactRef:
    owner: str
    artifact_type: str
    artifact_id: str
    artifact_version: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class OrderMaterialSelector:
    """An untrusted lookup key; its source, exact bytes, scope and lineage must be verified."""

    output: OrderArtifactRef
    envelope_content_hash: str

    @classmethod
    def parse(cls, value: object) -> "OrderMaterialSelector":
        """Reject extra authority fields, incomplete identities and malformed digests."""
        keys = {
            "owner",
            "artifact_type",
            "artifact_id",
            "artifact_version",
            "content_hash",
            "envelope_content_hash",
        }
        if (
            type(value) is not dict
            or set(value) != keys
            or any(
                type(v) is not str or not v or len(v) > 192 or any(c.isspace() for c in v)
                for v in value.values()
            )
        ):
            raise ValueError("invalid research material selector")
        for k in ("content_hash", "envelope_content_hash"):
            v = value[k]
            if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
                raise ValueError("invalid research material hash")
        return cls(
            OrderArtifactRef(
                value["owner"],
                value["artifact_type"],
                value["artifact_id"],
                value["artifact_version"],
                value["content_hash"],
            ),
            value["envelope_content_hash"],
        )


@dataclass(frozen=True, slots=True)
class OrderScopeOwner:
    account_namespace: str
    account_id: str
    owner_user_id: int
    tenant_id: str
    owner_id: str
    physical_row_pk: int
    source_id: str
    source_version: str
    identity_hash: str
    policy_id: str
    policy_version: str
    policy_hash: str
    valid_until: datetime
    role: str


@dataclass(frozen=True, slots=True)
class OrderBenchmarkPin:
    approval_id: UUID
    approval_version: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class OrderReviewMaterials:
    benchmark: OrderBenchmarkPin
    output: OrderArtifactRef
    envelope_content_hash: str
    operator: OrderArtifactRef
    track: OrderArtifactRef
    activation_hash: str
    read_scope_hashes: tuple[str, ...]
    research_permission: str
    research_governance: str
    research_blockers: tuple[str, ...]
    linked_order_sources: tuple[OrderArtifactRef, ...]
    research_summary: dict[str, str | int | bool]
    valid_until: datetime


class OrderScopeSources(Protocol):
    """Supply same-transaction owner facts and an authenticated signing session."""

    def signer(
        self, *, request: Request, using: str, before_commit: Callable[[], None]
    ) -> AbstractContextManager[User]: ...
    def owner(
        self, *, account_namespace: str, account_id: str, owner_user_id: int, using: str
    ) -> OrderScopeOwner | None: ...
    def materials(
        self,
        *,
        intent: BrokerCheckpointIntent,
        owner: OrderScopeOwner,
        pin: OrderBenchmarkPin | None,
        selection: OrderMaterialSelector | None,
        using: str,
    ) -> OrderReviewMaterials | None: ...


_factory: Callable[[], OrderScopeSources] | None = None


def install_order_scope_sources(factory: Callable[[], OrderScopeSources]) -> None:
    """Bind the server-owned factory at startup."""
    global _factory
    if _factory is not None and _factory is not factory:
        raise RuntimeError("Broker order scope sources are already configured")
    _factory = factory


def order_scope_sources() -> OrderScopeSources:
    """Resolve the configured owner sources, failing closed if the root did not run."""
    if _factory is None:
        raise BrokerExecutionConflictError("broker_order_scope_sources_unavailable")
    return _factory()
