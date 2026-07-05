"""Utilities for TUI/classic entry routing."""

from __future__ import annotations

from urllib.parse import urlparse

from django.http import HttpResponse

UI_MODE_COOKIE = "agom_ui_mode"
UI_MODE_CLASSIC = "classic"
UI_MODE_TUI = "tui"
VALID_UI_MODES = {UI_MODE_CLASSIC, UI_MODE_TUI}

DEFAULT_TUI_PATH = "/tui/"
CLASSIC_DASHBOARD_PATH = "/dashboard/"
UI_MODE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def normalize_local_path(candidate: str, *, default_path: str) -> str:
    """Return a safe local redirect path."""

    normalized = str(candidate or "").strip()
    if not normalized:
        return default_path

    parsed = urlparse(normalized)
    if parsed.scheme or parsed.netloc or not normalized.startswith("/"):
        return default_path
    return normalized


def infer_ui_mode_from_path(path: str) -> str | None:
    """Infer the preferred UI mode from a local path."""

    normalized = str(path or "").strip()
    if normalized in {"/tui", DEFAULT_TUI_PATH} or normalized.startswith(f"{DEFAULT_TUI_PATH}?"):
        return UI_MODE_TUI
    if normalized in {"/dashboard", CLASSIC_DASHBOARD_PATH} or normalized.startswith(
        f"{CLASSIC_DASHBOARD_PATH}?"
    ):
        return UI_MODE_CLASSIC
    return None


def set_ui_mode_cookie(response: HttpResponse, *, mode: str | None) -> HttpResponse:
    """Persist one reviewed UI mode on the response when applicable."""

    if mode not in VALID_UI_MODES:
        return response

    response.set_cookie(
        UI_MODE_COOKIE,
        mode,
        max_age=UI_MODE_COOKIE_MAX_AGE,
        samesite="Lax",
    )
    return response
