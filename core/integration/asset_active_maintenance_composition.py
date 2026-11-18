"""Core composition root for the isolated AssetMaster maintenance command."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from apps.audit.system_audit_event_outbox_composition import (
    build_system_audit_event_outbox_coordinator,
)
from apps.data_center.application.asset_active_maintenance import (
    AssetActiveMaintenance,
    AssetActiveMaintenanceError,
)
from apps.data_center.application.data02_task_authority import (
    preflight_data02_task_authority,
)
from apps.data_center.asset_active_maintenance_composition import (
    compose_asset_active_maintenance,
    create_asset_maintenance_owner_port,
)
from apps.data_center.domain.asset_active_maintenance import (
    MaintenanceAuthorityContext,
    MaintenanceOwner,
)
from core.integration.asset_active_maintenance_audit import DjangoAssetMaintenanceSystemAuditAdapter
from core.integration.data_center_audit import SystemAuditReaderContext

_AUTHORITY_WINDOW = timedelta(minutes=5)


class DjangoAssetMaintenanceOwnerPort:
    """Delegate credential and permission reads through the Data Center public port."""

    __slots__ = ("_delegate",)

    def __init__(self, *, authenticated_user: AbstractBaseUser) -> None:
        """Bind the actual password-authenticated user through the owning App."""

        self._delegate = create_asset_maintenance_owner_port(authenticated_user=authenticated_user)

    def current_owner(self) -> MaintenanceOwner:
        """Reload the actual current identity and exact model permission."""

        return self._delegate.current_owner()

    def is_current(self, expected: MaintenanceOwner) -> bool:
        """Check the same credential and current permission through its public port."""

        return self._delegate.is_current(expected)


class DjangoAssetMaintenanceAuthorityPort:
    """Reuse current provider-issued DATA02 authority and its bounded revalidator."""

    __slots__ = ("_audit_context",)

    def __init__(self) -> None:
        """Start without an authority until a real current preflight succeeds."""

        self._audit_context: SystemAuditReaderContext | None = None

    def current_context(
        self,
        owner: MaintenanceOwner,
        *,
        as_of: datetime,
    ) -> MaintenanceAuthorityContext:
        """Resolve the existing SystemAudit-backed DATA02 scope for this real user."""

        context, failure = preflight_data02_task_authority(
            as_of=as_of,
            minimum_window=_AUTHORITY_WINDOW,
            expected_actor=owner.actor_id,
        )
        if context is None or failure is not None or not context.can_read_at(as_of):
            raise AssetActiveMaintenanceError("data02_authority_unavailable")
        self._audit_context = context
        return MaintenanceAuthorityContext(
            actor_id=context.actor_id,
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            owner_id=context.owner_id,
            authority_content_hash=context.authority_content_hash,
            valid_until=context.authority_valid_until.astimezone(UTC),
        )

    def is_current(self, context: MaintenanceAuthorityContext, *, as_of: datetime) -> bool:
        """Revalidate the original authority snapshot rather than trusting a CLI actor."""

        reader_context = self._audit_context
        if reader_context is None:
            return False
        current, failure = preflight_data02_task_authority(
            as_of=as_of,
            minimum_window=_AUTHORITY_WINDOW,
            expected_actor=reader_context.actor_id,
        )
        return (
            failure is None
            and current is not None
            and current == reader_context
            and current.can_read_at(as_of)
            and reader_context.actor_id == context.actor_id
            and reader_context.user_id == context.user_id
            and reader_context.tenant_id == context.tenant_id
            and reader_context.owner_id == context.owner_id
            and reader_context.authority_content_hash == context.authority_content_hash
            and reader_context.authority_valid_until == context.valid_until
            and context.valid_until > as_of
        )


class DjangoAssetMaintenanceClock:
    """Use Django's server-side timezone-aware clock for the actual row update."""

    def now(self) -> datetime:
        """Return the current UTC-aware local maintenance timestamp."""

        return timezone.now()


def create_asset_active_maintenance_use_case(
    *,
    authenticated_user: AbstractBaseUser,
) -> AssetActiveMaintenance:
    """Compose current Owner/authority, old-table repositories, and SystemAudit UOW."""

    coordinator = build_system_audit_event_outbox_coordinator(using="default")
    audit = DjangoAssetMaintenanceSystemAuditAdapter(coordinator=coordinator)
    return compose_asset_active_maintenance(
        owner_port=DjangoAssetMaintenanceOwnerPort(authenticated_user=authenticated_user),
        authority_port=DjangoAssetMaintenanceAuthorityPort(),
        audit=audit,
        audit_writer=coordinator,
        clock=DjangoAssetMaintenanceClock(),
    )


__all__ = ["create_asset_active_maintenance_use_case"]
