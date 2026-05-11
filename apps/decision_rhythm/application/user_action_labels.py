"""Shared labels for Decision Workspace user_action values."""

from __future__ import annotations


def build_user_action_label(value: str) -> str:
    """Return the localized display label for a workspace user_action."""

    normalized = str(value or "").strip().upper()
    return {
        "PENDING": "待决策",
        "WATCHING": "观察中",
        "ADOPTED": "已采纳",
        "IGNORED": "已忽略",
    }.get(normalized, normalized or "待决策")
