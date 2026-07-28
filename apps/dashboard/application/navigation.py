"""Shared Dashboard navigation and status-label helpers."""

from __future__ import annotations

import re
from urllib.parse import urlencode

_SECURITY_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,19}$")
_SOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ACTION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{0,31}$")
_MAX_WORKSPACE_STEP = 100
_MAX_ACCOUNT_ID = 2_147_483_647


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
    security_code: object,
    source: object = "",
    step: object = None,
    account_id: object = None,
    action: object = None,
) -> str:
    """Build the canonical deep link into Decision Workspace."""

    params: list[tuple[str, str | int]] = []

    normalized_source = _normalize_token(source, _SOURCE_PATTERN, uppercase=False)
    if normalized_source is not None:
        params.append(("source", normalized_source))

    normalized_security_code = _normalize_token(
        security_code,
        _SECURITY_CODE_PATTERN,
        uppercase=True,
    )
    if normalized_security_code is not None:
        params.append(("security_code", normalized_security_code))

    normalized_step = _positive_integer(step, maximum=_MAX_WORKSPACE_STEP)
    if normalized_step is not None:
        params.append(("step", normalized_step))

    normalized_account_id = _positive_integer(account_id, maximum=_MAX_ACCOUNT_ID)
    if normalized_account_id is not None:
        params.append(("account_id", normalized_account_id))

    normalized_action = _normalize_token(action, _ACTION_PATTERN, uppercase=True)
    if normalized_action is not None:
        params.append(("action", normalized_action))

    query = urlencode(params, doseq=True)
    base_url = "/decision/workspace/"
    return f"{base_url}?{query}" if query else base_url


def _normalize_token(
    value: object,
    pattern: re.Pattern[str],
    *,
    uppercase: bool,
) -> str | None:
    """Return a canonical bounded token or None for invalid dynamic input."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    normalized = normalized.upper() if uppercase else normalized.lower()
    return normalized if pattern.fullmatch(normalized) else None


def _positive_integer(value: object, *, maximum: int) -> int | None:
    """Return a bounded positive ASCII integer without accepting bool."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate or not candidate.isascii() or not candidate.isdecimal():
            return None
        normalized = int(candidate)
    else:
        return None
    return normalized if 1 <= normalized <= maximum else None
