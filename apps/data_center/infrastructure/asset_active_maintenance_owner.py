"""Current authenticated user and model permission adapter for asset maintenance."""

from __future__ import annotations

from typing import Protocol, cast

from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser

from apps.data_center.application.asset_active_maintenance import AssetActiveMaintenanceError
from apps.data_center.domain.asset_active_maintenance import MaintenanceOwner

_REQUIRED_PERMISSION = "data_center.change_assetmastermodel"


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
