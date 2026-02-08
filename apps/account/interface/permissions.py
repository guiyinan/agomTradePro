"""DRF permissions aligned with unified RBAC matrix."""

from __future__ import annotations

from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.account.application.rbac import user_allows


class RBACDomainPermission(BasePermission):
    domain = "general"

    def has_permission(self, request, view) -> bool:
        level = "read" if request.method in SAFE_METHODS else "write"
        return user_allows(request.user, level=level, domain=self.domain)


class TradingPermission(RBACDomainPermission):
    domain = "trading"


class GeneralPermission(RBACDomainPermission):
    domain = "general"
