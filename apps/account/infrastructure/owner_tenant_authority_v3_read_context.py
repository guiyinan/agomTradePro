"""Connection-bound immutable read phases for one Authority V3 operation."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from core.exceptions import ExternalServiceError
from shared.infrastructure.immutable_read_snapshot import (
    isolated_immutable_read_snapshot,
    suspend_immutable_read_reuse,
)


class AuthorityReadConnectionError(ExternalServiceError):
    """Reject an immutable read phase without a stable physical connection."""

    default_code = "AUTHORITY_READ_CONNECTION_INVALID"


@dataclass(frozen=True, slots=True)
class _ActivePhase:
    """Record the exact context and connection active in one read phase."""

    owner: OwnerTenantAuthorityV3OperationReadContext
    connection: object


@dataclass(frozen=True, slots=True)
class _HeldSourceLocks:
    """Identify locks acquired by the enclosing composition transaction."""

    owner: OwnerTenantAuthorityV3OperationReadContext
    connection: object
    policy_id: str


_active_phase: ContextVar[_ActivePhase | None] = ContextVar(
    "owner_tenant_authority_v3_active_read_phase",
    default=None,
)
_held_source_locks: ContextVar[_HeldSourceLocks | None] = ContextVar(
    "owner_tenant_authority_v3_held_source_locks", default=None
)


class OwnerTenantAuthorityV3OperationReadContext:
    """Own short-lived cache phases shared by one composed Authority graph.

    The context is created by the Account composition root and is never a
    process-wide cache.  Each ``phase`` gets a fresh immutable-read dictionary;
    the phase is reusable by nested V5 readers only while the same alias and
    physical database connection are active. The connection provider is injected;
    a persistent Django wrapper must not be used as the connection identity.
    """

    def __init__(self, *, using: str, connection_provider: Callable[[], object]) -> None:
        """Bind the context to one exact alias and connection provider."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("Authority V3 read context alias is invalid")
        if not callable(connection_provider):
            raise TypeError("connection_provider must be callable")
        self._using = using
        self._connection_provider = connection_provider

    @contextmanager
    def source_locks(self, *, policy_id: str, acquire: Callable[[], None]) -> Iterator[None]:
        """Record successful outer locks until their owning atomic scope exits.

        The composition enters this scope inside its transaction, before any
        nested V5 savepoint, and exits before that transaction can roll back.
        This records held locks only; it neither owns a read cache nor extends
        an authority observation. Writes must still acquire exclusive locks.
        """
        before = self._connection_provider()
        acquire()
        connection = self._connection_provider()
        if connection is None or (before is not None and connection is not before):
            raise AuthorityReadConnectionError("Authority source lock connection changed.")
        token = _held_source_locks.set(_HeldSourceLocks(self, connection, policy_id))
        try:
            yield
            if self._connection_provider() is not connection:
                raise AuthorityReadConnectionError("Authority source lock connection changed.")
        finally:
            _held_source_locks.reset(token)

    def has_source_locks(self, using: str, policy_id: str) -> bool:
        """Check exact outer lock ownership without granting current authority."""
        held = _held_source_locks.get()
        return (
            using == self._using
            and held is not None
            and held.owner is self
            and held.policy_id == policy_id
            and held.connection is self._connection_provider()
        )

    @contextmanager
    def phase(self) -> Iterator[None]:
        """Start one fresh cache phase and discard it when the phase ends."""

        connection = self._connection_provider()
        if connection is None:
            raise AuthorityReadConnectionError("Authority source connection is unavailable.")
        active = _active_phase.set(_ActivePhase(self, connection))
        try:
            with suspend_immutable_read_reuse():
                with isolated_immutable_read_snapshot():
                    yield
                    if self._connection_provider() is not connection:
                        raise AuthorityReadConnectionError(
                            "Authority source connection changed during a read."
                        )
        finally:
            _active_phase.reset(active)

    def is_active(self, using: str) -> bool:
        """Return whether this context owns the current alias/connection phase."""

        if using != self._using:
            return False
        active = _active_phase.get()
        if active is None or active.owner is not self:
            return False
        try:
            return active.connection is self._connection_provider()
        except BaseException:
            return False


def _is_active_for(using: str, context: OwnerTenantAuthorityV3OperationReadContext | None) -> bool:
    """Check an optional context without exposing the ContextVar to repositories."""

    return context is not None and context.is_active(using)


__all__ = ["AuthorityReadConnectionError", "OwnerTenantAuthorityV3OperationReadContext"]
