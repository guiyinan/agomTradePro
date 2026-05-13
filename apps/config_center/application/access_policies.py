"""Authorization policies for config-center owned Qlib operations."""

from __future__ import annotations


class QlibAccessDeniedError(PermissionError):
    """Raised when the actor cannot access Qlib config-center operations."""


def _is_authenticated(actor) -> bool:
    return bool(actor is not None and getattr(actor, "is_authenticated", False))


def ensure_can_view_qlib_center(actor) -> None:
    """Require authenticated staff access for Qlib config-center read operations."""

    if not _is_authenticated(actor) or not bool(getattr(actor, "is_staff", False)):
        raise QlibAccessDeniedError("需要 staff 权限。")


def ensure_can_manage_qlib_runtime(actor) -> None:
    """Require superuser access for Qlib runtime config writes."""

    ensure_can_view_qlib_center(actor)
    if not bool(getattr(actor, "is_superuser", False)):
        raise QlibAccessDeniedError("修改 Runtime 配置需要 superuser 权限。")


def ensure_can_manage_qlib_training_profiles(actor) -> None:
    """Require superuser access for Qlib training profile writes."""

    ensure_can_view_qlib_center(actor)
    if not bool(getattr(actor, "is_superuser", False)):
        raise QlibAccessDeniedError("维护训练模板需要 superuser 权限。")


def ensure_can_trigger_qlib_training(actor) -> None:
    """Require superuser access for Qlib training trigger operations."""

    ensure_can_view_qlib_center(actor)
    if not bool(getattr(actor, "is_superuser", False)):
        raise QlibAccessDeniedError("触发训练需要 superuser 权限。")
