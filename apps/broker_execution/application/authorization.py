"""Action-level authorization for real broker execution."""

from __future__ import annotations

from typing import Any

from apps.account.application.rbac import get_user_role

from .use_case_errors import BrokerExecutionPermissionError

_ACTION_ROLES: dict[str, frozenset[str]] = {
    "view": frozenset(
        {"admin", "owner", "investment_manager", "trader", "risk", "analyst", "read_only"}
    ),
    "create_draft": frozenset({"admin", "owner", "investment_manager", "trader"}),
    "approve": frozenset({"admin", "owner", "investment_manager", "trader"}),
    "reject": frozenset({"admin", "owner", "investment_manager", "trader", "risk"}),
    "cancel": frozenset({"admin", "owner", "investment_manager", "trader", "risk"}),
    "kill_switch": frozenset({"admin", "owner", "investment_manager", "trader", "risk"}),
    "resume": frozenset({"admin"}),
    "manage_limits": frozenset({"admin"}),
    "manage_binding": frozenset({"admin"}),
    "manage_access": frozenset({"admin"}),
    "manage_agent_credentials": frozenset({"admin"}),
    "resolve_reconciliation": frozenset({"admin", "risk"}),
}


def actor_context(user: Any) -> tuple[int, str, bool]:
    """Return validated actor identity, role, and administrator flag."""

    if not getattr(user, "is_authenticated", False) or not getattr(user, "id", None):
        raise BrokerExecutionPermissionError("Authentication is required")
    role = get_user_role(user)
    is_admin = bool(getattr(user, "is_superuser", False) or role == "admin")
    return int(user.id), role, is_admin


def require_action(user: Any, action: str) -> tuple[int, str, bool]:
    """Authorize an action and return normalized actor context."""

    user_id, role, is_admin = actor_context(user)
    if role not in _ACTION_ROLES.get(action, frozenset()):
        try:
            from .repository_provider import get_broker_execution_repository

            get_broker_execution_repository().record_permission_denial(
                user_id=user_id, action=action, role=role
            )
        except RuntimeError:
            pass
        raise BrokerExecutionPermissionError(
            f"Role {role!r} cannot perform broker execution action {action!r}"
        )
    return user_id, role, is_admin


def action_permissions(user: Any) -> dict[str, bool]:
    """Return UI hints for all stable broker-execution actions."""

    _user_id, role, _is_admin = actor_context(user)
    return {action: role in roles for action, roles in _ACTION_ROLES.items()}
