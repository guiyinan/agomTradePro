"""Opt-in M5 fixture layer over the standard isolated Playwright settings."""

from __future__ import annotations

import os
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured

from core.settings import playwright as _playwright_settings
from core.settings.playwright import *  # noqa: F403

if os.environ.get("AGOM_M5_SYNTHETIC_CALENDAR") == "1":
    from tests.support.tui_research.calendar_transport_settings import (
        require_m5_calendar_transport_environment,
    )

    _databases = cast(dict[str, dict[str, Any]], DATABASES)  # noqa: F405
    try:
        M5_CALENDAR_ARTIFACT_ROOT = require_m5_calendar_transport_environment(
            databases=_databases,
        )
    except ValueError as exc:
        raise ImproperlyConfigured(str(exc)) from exc
    INSTALLED_APPS = [
        *_playwright_settings.INSTALLED_APPS,
        "tests.support.tui_research.calendar_transport_app.M5CalendarTransportConfig",
    ]
    MIDDLEWARE = [
        *_playwright_settings.MIDDLEWARE,
        "tests.support.tui_research.calendar_transport_runtime." "M5CalendarRequestScopeMiddleware",
    ]
