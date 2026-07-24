"""DRF permissions aligned with unified RBAC matrix."""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from apps.account.application.interface_services import (
    get_accessible_portfolios_queryset,
    has_active_observer_access,
)
from apps.account.application.rbac import user_allows


class RBACDomainPermission(BasePermission):
    domain = "general"

    def has_permission(self, request: Request, view: Any) -> bool:
        level = "read" if request.method in SAFE_METHODS else "write"
        return user_allows(request.user, level=level, domain=self.domain)


class TradingPermission(RBACDomainPermission):
    domain = "trading"


class GeneralPermission(RBACDomainPermission):
    domain = "general"


class ObserverAccessPermission(BasePermission):
    """
    观察员访问权限检查

    允许账户拥有者和有效观察员访问投资组合和持仓数据：
    - 账户拥有者：完全访问权限
    - 观察员：只读权限（SAFE_METHODS）
    """

    def has_permission(self, request: Request, view: Any) -> bool:
        """基础权限检查：用户必须已认证"""
        return _authenticated_user_id(request.user) is not None

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        """
        对象级权限检查

        Args:
            request: 请求对象
            view: 视图对象
            obj: 被访问的对象（PortfolioModel 或 PositionModel）

        Returns:
            bool: 是否有权限访问
        """
        user_id = _authenticated_user_id(request.user)
        if user_id is None:
            return False

        # 1. 获取关联的 PortfolioModel
        portfolio = getattr(obj, "portfolio", obj)
        owner_user_id = getattr(portfolio, "user_id", None)
        if (
            isinstance(owner_user_id, bool)
            or not isinstance(owner_user_id, int)
            or owner_user_id <= 0
        ):
            return False

        # 2. 账户拥有者：完全访问权限
        if owner_user_id == user_id:
            return True

        # 3. 观察员：只读权限
        if request.method in SAFE_METHODS:
            return has_active_observer_access(
                owner_user_id=owner_user_id,
                observer_user_id=user_id,
            )

        # 4. 其他情况：拒绝访问
        return False


def _authenticated_user_id(user: Any) -> int | None:
    """Return a validated authenticated user identifier."""

    if user is None or not bool(getattr(user, "is_authenticated", False)):
        return None
    user_id = getattr(user, "pk", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        return None
    return user_id


def get_accessible_portfolios(user: Any) -> Any:
    """
    获取用户可访问的投资组合列表

    包括：
    - 用户自己的投资组合（拥有者）
    - 被授权观察的投资组合（观察员）

    Args:
        user: 用户对象

    Returns:
        QuerySet: 可访问的 PortfolioModel 查询集
    """
    user_id = _authenticated_user_id(user)
    if user_id is None:
        raise NotAuthenticated("Authentication credentials were not provided.")
    return get_accessible_portfolios_queryset(user_id)
