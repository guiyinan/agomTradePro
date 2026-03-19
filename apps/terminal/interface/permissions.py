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
