"""
Terminal Interface Permissions.

DRF 权限类定义。
"""

from rest_framework.permissions import BasePermission


class IsStaffOrAdmin(BasePermission):
    """仅允许 staff 或 superuser 访问"""

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )


class IsStaffOrOperator(BasePermission):
    """Allow authenticated staff or members of the operator group."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return user.groups.filter(name="operator").exists()
