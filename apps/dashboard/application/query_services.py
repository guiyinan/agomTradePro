"""Application-level dashboard query helpers for TUI/runtime consumers."""

from __future__ import annotations

from typing import Any

from apps.dashboard.application.queries import get_alpha_homepage_query


def has_dashboard_alpha_history(user: Any | None) -> bool:
    """Return whether the current user has Alpha history rows for same-screen drilldown."""

    if user is None or not bool(getattr(user, "is_authenticated", False)):
        return False
    return bool(get_alpha_homepage_query().list_history(user_id=int(user.id)))
