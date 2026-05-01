"""Unified RBAC helpers shared by Django-side authorization."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SupportsAccountProfile(Protocol):
    """Minimal profile shape needed by RBAC helpers."""

    rbac_role: str


@runtime_checkable
class SupportsRBACUser(Protocol):
    """Application-layer user protocol to avoid depending on Django ORM types."""

    is_authenticated: bool
    is_superuser: bool
    account_profile: SupportsAccountProfile | None

ROLE_ALIASES: dict[str, str] = {
    "管理员": "admin",
    "admin": "admin",
    "owner": "owner",
    "所有者": "owner",
    "analyst": "analyst",
    "分析师": "analyst",
    "investment_manager": "investment_manager",
    "投资经理": "investment_manager",
    "trader": "trader",
    "交易员": "trader",
    "risk": "risk",
    "risk_manager": "risk",
    "风控": "risk",
    "readonly": "read_only",
    "read_only": "read_only",
    "viewer": "read_only",
    "只读用户": "read_only",
}

ROLE_CHOICES: list[tuple[str, str]] = [
    ("admin", "管理员"),
    ("owner", "所有者"),
    ("analyst", "分析师"),
    ("investment_manager", "投资经理"),
    ("trader", "交易员"),
    ("risk", "风控"),
    ("read_only", "只读用户"),
]


def normalize_role(raw: str | None) -> str:
    if not raw:
        return "read_only"
    return ROLE_ALIASES.get(raw.strip().lower(), raw.strip().lower())


def role_allows_by_matrix(role: str, level: str, domain: str) -> bool:
    role = normalize_role(role)
    if role == "admin":
        return True

    if level == "admin" or domain == "system":
        return False

    if role == "owner":
        return level in {"read", "write"}
    if role == "analyst":
        return level == "read"
    if role == "investment_manager":
        if level == "read":
            return True
        return domain in {"trading", "strategy", "risk", "general"}
    if role == "trader":
        if level == "read":
            return True
        return domain == "trading"
    if role == "risk":
        if level == "read":
            return True
        return domain == "risk"
    if role == "read_only":
        return level == "read"
    return False


def get_user_role(user: SupportsRBACUser | object) -> str:
    if not getattr(user, "is_authenticated", False):
        return "read_only"
    if getattr(user, "is_superuser", False):
        return "admin"
    profile = getattr(user, "account_profile", None)
    if profile is not None:
        return normalize_role(getattr(profile, "rbac_role", "read_only"))
    return "read_only"


def user_allows(user: SupportsRBACUser | object, level: str, domain: str) -> bool:
    return role_allows_by_matrix(get_user_role(user), level, domain)


def is_system_admin(user: SupportsRBACUser | object) -> bool:
    return user_allows(user, level="admin", domain="system")
