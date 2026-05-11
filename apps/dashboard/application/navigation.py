"""Shared Dashboard navigation and status-label helpers."""

from __future__ import annotations

from urllib.parse import urlencode


def normalize_exit_user_action(value: object) -> str:
    """Normalize recommendation user_action values for UI and API consumers."""

    return str(value or "").strip().upper()


def build_exit_user_action_label(value: object) -> str:
    """Return the localized label for an exit recommendation user_action."""

    return {
        "PENDING": "待决策",
        "WATCHING": "观察中",
        "ADOPTED": "已采纳",
        "IGNORED": "已忽略",
    }.get(normalize_exit_user_action(value), "")


def build_decision_workspace_url(
    *,
    security_code: str | None,
    source: str = "",
    step: int | None = None,
    account_id: int | str | None = None,
    action: str | None = None,
) -> str:
    """Build the canonical deep link into Decision Workspace."""

    params: list[tuple[str, str | int]] = []

    normalized_source = str(source or "").strip()
    if normalized_source:
        params.append(("source", normalized_source))

    normalized_security_code = str(security_code or "").strip().upper()
    if normalized_security_code:
        params.append(("security_code", normalized_security_code))

    if step not in (None, ""):
        params.append(("step", int(step)))

    if account_id not in (None, ""):
        params.append(("account_id", int(account_id)))

    normalized_action = str(action or "").strip().upper()
    if normalized_action:
        params.append(("action", normalized_action))

    query = urlencode(params, doseq=True)
    base_url = "/decision/workspace/"
    return f"{base_url}?{query}" if query else base_url
