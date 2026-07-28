"""
Terminal Interface Permissions.

DRF 权限类定义。
"""

from typing import Protocol, cast

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class _GroupMembershipQueryProtocol(Protocol):
    """Minimal group query result needed by Terminal permissions."""

    def exists(self) -> bool:
        """Return whether the governed group membership exists."""
        ...


class _GroupMembershipManagerProtocol(Protocol):
    """Minimal group manager needed by Terminal permissions."""

    def filter(self, *, name: str) -> _GroupMembershipQueryProtocol:
        """Filter memberships by the governed Django group name."""
        ...


class _TerminalPermissionUserProtocol(Protocol):
    """Authenticated user surface required by Terminal permissions."""

    @property
    def is_authenticated(self) -> bool:
        """Return whether authentication succeeded."""
        ...

    @property
    def is_staff(self) -> bool:
        """Return whether the user has staff access."""
        ...

    @property
    def is_superuser(self) -> bool:
        """Return whether the user has unrestricted access."""
        ...

    @property
    def groups(self) -> _GroupMembershipManagerProtocol:
        """Return the user's Django group relation manager."""
        ...


def _permission_user(request: Request) -> _TerminalPermissionUserProtocol:
    """Narrow DRF's dynamic user boundary to the permission contract."""

    return cast(_TerminalPermissionUserProtocol, request.user)


class IsStaffOrAdmin(BasePermission):
    """仅允许 staff 或 superuser 访问"""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = _permission_user(request)
        return user.is_authenticated is True and (
            user.is_staff is True or user.is_superuser is True
        )


class IsStaffOrOperator(BasePermission):
    """Allow authenticated staff or members of the operator group."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = _permission_user(request)
        if user.is_authenticated is not True:
            return False
        if user.is_staff is True or user.is_superuser is True:
            return True
        return user.groups.filter(name="operator").exists() is True
