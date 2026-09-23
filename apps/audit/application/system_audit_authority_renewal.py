"""Application contract for renewing the scoped System Audit authority bundle.

The renewal flow is deliberately small and append-only.  It captures a fresh
Account actor source, appends an owner/tenant authority successor through the
existing Account facade, and returns the exact selector that may be bound to a
Config Center successor.  Authentication and persistence remain composition
responsibilities; this module never reads a request or ORM model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.owner_tenant_authority_v3 import (
    SupersedeOwnerTenantAuthorityV3Command,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.owner_tenant_authority_v3 import OwnerTenantAuthorityV3
from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_authority_schema import (
    SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
)


class SystemAuditAuthorityRenewalUnavailable(RuntimeError):
    """A renewal cannot produce a current, bounded authority bundle."""

    def __init__(self, reason_code: str) -> None:
        """Keep the public failure reason stable and secret-free."""

        if (
            type(reason_code) is not str
            or not reason_code
            or len(reason_code) > 64
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in reason_code
            )
        ):
            raise ValueError("reason_code must be a canonical token")
        super().__init__("system audit authority renewal is unavailable")
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class SystemAuditAuthorityRenewalRequest:
    """Bind one actor capture and one exact owner successor request."""

    actor_capture: CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command
    owner_successor: SupersedeOwnerTenantAuthorityV3Command
    minimum_window: timedelta

    def __post_init__(self) -> None:
        """Validate the closed command graph before opening a write boundary."""

        if (
            type(self.actor_capture)
            is not CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command
        ):
            raise TypeError("actor_capture must be an exact capture command")
        if type(self.owner_successor) is not SupersedeOwnerTenantAuthorityV3Command:
            raise TypeError("owner_successor must be an exact successor command")
        self.actor_capture.__post_init__()
        self.owner_successor.__post_init__()
        if type(self.minimum_window) is not timedelta or self.minimum_window <= timedelta(0):
            raise ValueError("minimum_window must be a positive timedelta")


@dataclass(frozen=True, slots=True)
class RenewedSystemAuditAuthority:
    """Return the exact actor/scope selector and its bounded validity."""

    actor: AccountOwnerAssignmentActorAuthoritySourceV3
    scope: OwnerTenantAuthorityV3
    selector: SystemAuditAuthorityBundleSelector
    valid_until: datetime
    renewed_at: datetime

    def __post_init__(self) -> None:
        """Validate the returned immutable bundle before configuration binding."""

        if type(self.actor) is not AccountOwnerAssignmentActorAuthoritySourceV3:
            raise TypeError("actor must be an exact actor authority source")
        if type(self.scope) is not OwnerTenantAuthorityV3:
            raise TypeError("scope must be an exact owner authority")
        if type(self.selector) is not SystemAuditAuthorityBundleSelector:
            raise TypeError("selector must be an exact audit selector")
        self.actor.__post_init__()
        self.scope.__post_init__()
        self.selector.__post_init__()
        _aware(self.valid_until, "valid_until")
        _aware(self.renewed_at, "renewed_at")
        if self.renewed_at >= self.valid_until:
            raise ValueError("renewed authority validity is empty")
        if self.actor.source_id != self.selector.actor_source_id:
            raise ValueError("actor selector identity differs")
        if self.actor.source_version != self.selector.actor_source_version:
            raise ValueError("actor selector version differs")
        if self.actor.content_hash != self.selector.actor_content_hash:
            raise ValueError("actor selector hash differs")
        if self.scope.authority_id != self.selector.scope_source_id:
            raise ValueError("scope selector identity differs")
        if self.scope.authority_version != self.selector.scope_source_version:
            raise ValueError("scope selector version differs")
        if self.scope.content_hash != self.selector.scope_content_hash:
            raise ValueError("scope selector hash differs")
        if self.selector.scope_schema != SYSTEM_AUDIT_SCOPE_SCHEMA_V3:
            raise ValueError("renewal requires the V3 scope schema")
        if (
            self.actor.actor_id != self.scope.actor_id
            or self.actor.user_id != self.scope.actor_user_id
        ):
            raise ValueError("actor and scope principals differ")
        if self.valid_until != min(self.actor.valid_until, self.scope.valid_until):
            raise ValueError("renewed validity is not the minimum source validity")


class ActorAuthorityCapturePort(Protocol):
    """Capture one fresh actor source from server-owned upstream facts."""

    def execute(
        self, command: CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3: ...


class OwnerAuthoritySuccessorPort(Protocol):
    """Append one owner/tenant authority successor with predecessor CAS."""

    def successor(
        self, command: SupersedeOwnerTenantAuthorityV3Command
    ) -> OwnerTenantAuthorityV3: ...


class OwnerAuthoritySuccessorFactory(Protocol):
    """Build the owner successor facade after the fresh actor source exists."""

    def build(
        self, actor: AccountOwnerAssignmentActorAuthoritySourceV3
    ) -> OwnerAuthoritySuccessorPort: ...


class RenewSystemAuditAuthority:
    """Orchestrate append-only authority renewal without minting credentials."""

    def __init__(
        self,
        *,
        actor_capture: ActorAuthorityCapturePort,
        owner_factory: OwnerAuthoritySuccessorFactory,
        clock: Callable[[], datetime],
    ) -> None:
        """Bind the existing Account writers and one timezone-aware clock."""

        if not callable(getattr(actor_capture, "execute", None)):
            raise TypeError("actor_capture must expose execute")
        if not callable(getattr(owner_factory, "build", None)):
            raise TypeError("owner_factory must expose build")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._actor_capture = actor_capture
        self._owner_factory = owner_factory
        self._clock = clock

    def execute(self, request: SystemAuditAuthorityRenewalRequest) -> RenewedSystemAuditAuthority:
        """Capture, append, and validate one exact authority bundle.

        The caller owns the surrounding database transaction.  If the later
        Config Center successor fails, that transaction can roll back both
        authority appends together; no old row is edited or extended.
        """

        if type(request) is not SystemAuditAuthorityRenewalRequest:
            raise TypeError("request must be an exact renewal request")
        request.__post_init__()
        actor = self._capture(request.actor_capture)
        actor_observed_at = _aware(self._clock(), "actor renewal clock")
        if not actor.is_temporally_current_at(actor_observed_at):
            raise SystemAuditAuthorityRenewalUnavailable("actor_authority_not_current")
        scope = self._successor(request.owner_successor, actor)
        renewed_at = _aware(self._clock(), "renewal clock")
        if scope.status != "active" or not scope.is_current_at(renewed_at):
            raise SystemAuditAuthorityRenewalUnavailable("owner_authority_not_current")
        valid_until = min(actor.valid_until, scope.valid_until)
        if valid_until < renewed_at + request.minimum_window:
            raise SystemAuditAuthorityRenewalUnavailable("authority_window_too_short")
        selector = SystemAuditAuthorityBundleSelector(
            actor_source_id=actor.source_id,
            actor_source_version=actor.source_version,
            actor_content_hash=actor.content_hash,
            scope_source_id=scope.authority_id,
            scope_source_version=scope.authority_version,
            scope_content_hash=scope.content_hash,
            scope_schema=SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
        )
        return RenewedSystemAuditAuthority(
            actor=actor,
            scope=scope,
            selector=selector,
            valid_until=valid_until,
            renewed_at=renewed_at,
        )

    def _capture(
        self, command: CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3:
        """Capture and type-check the fresh actor source."""

        try:
            actor = self._actor_capture.execute(command)
        except SystemAuditAuthorityRenewalUnavailable:
            raise
        except (TypeError, ValueError) as error:
            raise SystemAuditAuthorityRenewalUnavailable("actor_capture_rejected") from error
        if type(actor) is not AccountOwnerAssignmentActorAuthoritySourceV3:
            raise SystemAuditAuthorityRenewalUnavailable("actor_capture_type_invalid")
        try:
            actor.__post_init__()
        except (TypeError, ValueError) as error:
            raise SystemAuditAuthorityRenewalUnavailable("actor_capture_corrupt") from error
        return actor

    def _successor(
        self,
        command: SupersedeOwnerTenantAuthorityV3Command,
        actor: AccountOwnerAssignmentActorAuthoritySourceV3,
    ) -> OwnerTenantAuthorityV3:
        """Append and validate the exact owner successor for the actor."""

        try:
            facade = self._owner_factory.build(actor)
            scope = facade.successor(command)
        except SystemAuditAuthorityRenewalUnavailable:
            raise
        except (TypeError, ValueError) as error:
            raise SystemAuditAuthorityRenewalUnavailable("owner_successor_rejected") from error
        if type(scope) is not OwnerTenantAuthorityV3:
            raise SystemAuditAuthorityRenewalUnavailable("owner_successor_type_invalid")
        try:
            scope.__post_init__()
        except (TypeError, ValueError) as error:
            raise SystemAuditAuthorityRenewalUnavailable("owner_successor_corrupt") from error
        if scope.authority_version != command.authority_version:
            raise SystemAuditAuthorityRenewalUnavailable("owner_successor_identity_mismatch")
        return scope


def _aware(value: object, name: str) -> datetime:
    """Require one timezone-aware timestamp without normalization."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


__all__ = [
    "ActorAuthorityCapturePort",
    "OwnerAuthoritySuccessorFactory",
    "OwnerAuthoritySuccessorPort",
    "RenewSystemAuditAuthority",
    "RenewedSystemAuditAuthority",
    "SystemAuditAuthorityRenewalRequest",
    "SystemAuditAuthorityRenewalUnavailable",
]
