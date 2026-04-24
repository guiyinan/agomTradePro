"""DRF permissions aligned with unified RBAC matrix."""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.account.application.interface_services import (
    get_accessible_portfolios_queryset,
    has_active_observer_access,
)
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


class ObserverAccessPermission(BasePermission):
    """
    观察员访问权限检查

    允许账户拥有者和有效观察员访问投资组合和持仓数据：
    - 账户拥有者：完全访问权限
    - 观察员：只读权限（SAFE_METHODS）
    """

    def has_permission(self, request, view) -> bool:
        """基础权限检查：用户必须已认证"""
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj) -> bool:
        """
        对象级权限检查

        Args:
            request: 请求对象
            view: 视图对象
            obj: 被访问的对象（PortfolioModel 或 PositionModel）

        Returns:
            bool: 是否有权限访问
        """
        # 1. 获取关联的 PortfolioModel
        if hasattr(obj, 'portfolio'):
            # PositionModel
            portfolio = obj.portfolio
        else:
            # PortfolioModel
            portfolio = obj

        # 2. 账户拥有者：完全访问权限
        if portfolio.user == request.user:
            return True

        # 3. 观察员：只读权限
        if request.method in SAFE_METHODS:
            return has_active_observer_access(
                owner_user_id=portfolio.user_id,
                observer_user_id=request.user.id,
            )

        # 4. 其他情况：拒绝访问
        return False


def get_accessible_portfolios(user):
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
    return get_accessible_portfolios_queryset(user.id)
