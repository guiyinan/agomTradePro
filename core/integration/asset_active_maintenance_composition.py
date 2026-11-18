"""Core composition root for the isolated AssetMaster maintenance command."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.data_center.application.asset_active_maintenance import (
    AssetActiveMaintenance,
    AssetActiveMaintenanceError,
)
from apps.data_center.application.data02_task_authority import (
    preflight_data02_task_authority,
)
from apps.data_center.application.sync_transaction import DataCenterSyncAuditWriter
from apps.data_center.domain.asset_active_maintenance import (
    MaintenanceAuthorityContext,
    MaintenanceOwner,
)
from apps.data_center.infrastructure.asset_active_maintenance import (
    DjangoAssetMasterMaintenanceRepository,
    DjangoAssetMasterMaintenanceSourceReader,
)
from apps.data_center.infrastructure.audited_sync_runtime import DjangoDataCenterSyncUnitOfWork
from core.integration.asset_active_maintenance_audit import DjangoAssetMaintenanceSystemAuditAdapter
from core.integration.data_center_audit import SystemAuditReaderContext

_REQUIRED_PERMISSION = "data_center.change_assetmastermodel"
_AUTHORITY_WINDOW = timedelta(minutes=5)


class _MaintenancePermissionUser(Protocol):
    """Narrow the configured auth model's permission interface at the ORM boundary."""

    is_active: bool

    def get_username(self) -> str:
        """Return the exact persisted login identity."""

    def has_perm(self, perm: str) -> bool:
        """Check the current configured backend for one exact model permission."""


class DjangoAssetMaintenanceOwnerPort:
    """Reload the authenticated user and exact model permission at each boundary."""

    __slots__ = ("_user_id", "_username")

    def __init__(self, *, authenticated_user: AbstractBaseUser) -> None:
        """Bind the adapter to a real user returned by Django authentication."""

        if not getattr(authenticated_user, "is_authenticated", False):
            raise AssetActiveMaintenanceError("owner_authentication_or_permission_invalid")
        user_id = getattr(authenticated_user, "pk", None)
        username = getattr(authenticated_user, "get_username", lambda: "")()
        if type(user_id) is not int or user_id <= 0 or not username:
            raise AssetActiveMaintenanceError("owner_authentication_or_permission_invalid")
        self._user_id = user_id
        self._username = username

    def current_owner(self) -> MaintenanceOwner:
        """Reload the same active user and materialize current permission state."""

        try:
            user = self._load_user()
        except (LookupError, ValueError) as error:
            raise AssetActiveMaintenanceError("owner_unavailable") from error
        return MaintenanceOwner(
            user_id=self._user_id,
            username=self._username,
            actor_id=f"django-user:{self._user_id}",
            is_authenticated=True,
            is_active=bool(user.is_active),
            can_change_assetmaster=bool(user.has_perm(_REQUIRED_PERMISSION)),
        )

    def is_current(self, expected: MaintenanceOwner) -> bool:
        """Ensure the bound user still has active status and model permission."""

        try:
            current = self.current_owner()
        except (AssetActiveMaintenanceError, LookupError, ValueError):
            return False
        return (
            current.user_id == expected.user_id
            and current.username == expected.username
            and current.actor_id == expected.actor_id
            and current.is_authorized
        )

    def _load_user(self) -> _MaintenancePermissionUser:
        """Read the exact default-database auth user or fail closed."""

        model = get_user_model()
        try:
            user = model._default_manager.using("default").get(pk=self._user_id)
        except model.DoesNotExist as error:
            raise AssetActiveMaintenanceError("owner_unavailable") from error
        if user.get_username() != self._username:
            raise AssetActiveMaintenanceError("owner_identity_changed")
        if not callable(getattr(user, "has_perm", None)):
            raise AssetActiveMaintenanceError("owner_permission_interface_unavailable")
        return cast(_MaintenancePermissionUser, user)


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

    source_reader = DjangoAssetMasterMaintenanceSourceReader(using="default")
    repository = DjangoAssetMasterMaintenanceRepository(using="default")
    coordinator = DjangoSystemAuditEventOutboxCoordinator(using="default")
    audit = DjangoAssetMaintenanceSystemAuditAdapter(coordinator=coordinator)
    unit_of_work = DjangoDataCenterSyncUnitOfWork(
        participants=(repository, source_reader),
        audit_writer=cast(DataCenterSyncAuditWriter, coordinator),
        using="default",
    )
    return AssetActiveMaintenance(
        source_reader=source_reader,
        owner_port=DjangoAssetMaintenanceOwnerPort(authenticated_user=authenticated_user),
        authority_port=DjangoAssetMaintenanceAuthorityPort(),
        repository=repository,
        unit_of_work=unit_of_work,
        audit=audit,
        clock=DjangoAssetMaintenanceClock(),
    )


__all__ = ["create_asset_active_maintenance_use_case"]
