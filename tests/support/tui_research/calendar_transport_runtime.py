"""Candidate test-only bridge for the managed M5 calendar read fixture."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import cast

from django.conf import settings
from django.http import HttpRequest, HttpResponseBase
from django.urls import Resolver404, resolve

from apps.data_center.domain.model_market_data import (
    ModelMarketDataPort,
    TradingCalendarEvidence,
)

_M5_CALENDAR_ACTION_KEYS = frozenset(
    {
        "data-center.market-thermometer-current",
        "operator.governance.data_center_summary",
        "task-monitor.readiness",
        "dashboard.alpha-ranking",
    }
)
_M5_CALENDAR_ACTION_URL_NAME = "api-tui-action-run"


@dataclass(slots=True)
class _ActiveScope:
    """A mutable marker that expires in copied async/thread contexts too."""

    active: bool = True


_M5_CALENDAR_REQUEST_SCOPE: ContextVar[_ActiveScope | None] = ContextVar(
    "m5_synthetic_calendar_request_scope",
    default=None,
)
_CALENDAR_LOADER_ACTIVE: ContextVar[_ActiveScope | None] = ContextVar(
    "m5_synthetic_calendar_loader_active",
    default=None,
)
_INSTALL_LOCK = RLock()
_INSTALLED = False
_INSTALL_MARKER = "_m5_synthetic_calendar_transport_installed"


def _scope_is_active(scope: _ActiveScope | None) -> bool:
    """Return whether one request or loader scope has not yet expired."""

    return scope is not None and scope.active


def _calendar_request_scope_is_active() -> bool:
    """Expose the current test-only TUI request scope for focused unit checks."""

    return _scope_is_active(_M5_CALENDAR_REQUEST_SCOPE.get())


def _is_calendar_action_request(request: HttpRequest) -> bool:
    """Match only the named TUI run route and the four governed M5 actions."""

    if request.method != "POST":
        return False
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return False
    action_key = match.kwargs.get("action_key")
    return (
        match.url_name == _M5_CALENDAR_ACTION_URL_NAME
        and isinstance(action_key, str)
        and action_key in _M5_CALENDAR_ACTION_KEYS
        and request.path_info == f"/api/tui/actions/{action_key}/run/"
    )


class M5CalendarRequestScopeMiddleware:
    """Enable synthetic calendar reads only within four exact TUI action POSTs."""

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponseBase],
    ) -> None:
        """Keep the next middleware or view in the standard Django chain."""

        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        """Set a short-lived scope around an exact allowlisted action request."""

        if not _is_calendar_action_request(request):
            token = _M5_CALENDAR_REQUEST_SCOPE.set(None)
            try:
                return self.get_response(request)
            finally:
                _M5_CALENDAR_REQUEST_SCOPE.reset(token)
        scope = _ActiveScope()
        token = _M5_CALENDAR_REQUEST_SCOPE.set(scope)
        try:
            return self.get_response(request)
        finally:
            scope.active = False
            _M5_CALENDAR_REQUEST_SCOPE.reset(token)


def _validated_artifact_root() -> Path:
    """Repeat the settings guard in AppConfig.ready before installing hooks."""

    from tests.support.tui_research.calendar_transport_settings import (
        require_m5_calendar_transport_environment,
    )

    return require_m5_calendar_transport_environment(databases=settings.DATABASES)


def _synthetic_artifacts_ready(artifact_root: Path) -> bool:
    """Return whether the explicit raw fixture exists, rejecting partial state."""

    raw_path = artifact_root / "synthetic-calendar.json"
    sha256_path = artifact_root / "synthetic-calendar.json.sha256"
    if not raw_path.exists() and not sha256_path.exists():
        return False
    if not raw_path.is_file() or not sha256_path.is_file():
        raise RuntimeError("partial M5 synthetic calendar artifact detected")
    return True


def install_m5_calendar_transport() -> None:
    """Install a guarded, context-scoped test composition adapter once."""

    global _INSTALLED

    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        artifact_root = _validated_artifact_root()

        from apps.data_center import composition
        from apps.data_center.application import market_calendar
        from tests.support.tui_research.calendar_transport import (
            build_synthetic_calendar_service_from_artifacts,
        )

        current_loader = market_calendar.load_cn_market_calendar_evidence
        current_factory = composition.build_model_market_data_service
        if getattr(current_loader, _INSTALL_MARKER, False):
            if not getattr(current_factory, _INSTALL_MARKER, False):
                raise RuntimeError("partial M5 calendar transport installation detected")
            _INSTALLED = True
            return

        original_loader = current_loader
        original_factory = current_factory
        cache_clear = cast(Callable[[], None], original_loader.cache_clear)
        cache_info = cast(Callable[[], object], original_loader.cache_info)
        cache_parameters = cast(
            Callable[[], object],
            original_loader.cache_parameters,
        )
        loader_lock = RLock()

        @wraps(original_loader)
        def scoped_loader(start_date: date, end_date: date) -> TradingCalendarEvidence:
            """Use synthetic evidence only during a bounded M5 action request."""

            with loader_lock:
                if not _calendar_request_scope_is_active() or not _synthetic_artifacts_ready(
                    artifact_root
                ):
                    return original_loader(start_date, end_date)
                cache_clear()
                scope = _ActiveScope()
                token = _CALENDAR_LOADER_ACTIVE.set(scope)
                try:
                    return original_loader(start_date, end_date)
                finally:
                    scope.active = False
                    _CALENDAR_LOADER_ACTIVE.reset(token)
                    cache_clear()

        @wraps(original_factory)
        def scoped_factory() -> ModelMarketDataPort:
            """Use synthetic input only inside the request-scoped calendar loader."""

            if _calendar_request_scope_is_active() and _scope_is_active(
                _CALENDAR_LOADER_ACTIVE.get()
            ):
                service, _artifacts = build_synthetic_calendar_service_from_artifacts(
                    artifact_root=artifact_root,
                )
                return service
            return original_factory()

        def scoped_cache_clear() -> None:
            """Clear the original loader cache under the same lock."""

            with loader_lock:
                cache_clear()

        def scoped_cache_info() -> object:
            """Return the original loader cache statistics."""

            with loader_lock:
                return cache_info()

        def scoped_cache_parameters() -> object:
            """Return the original loader cache parameters."""

            with loader_lock:
                return cache_parameters()

        scoped_loader.cache_clear = scoped_cache_clear
        scoped_loader.cache_info = scoped_cache_info
        scoped_loader.cache_parameters = scoped_cache_parameters
        setattr(scoped_loader, _INSTALL_MARKER, True)
        setattr(scoped_factory, _INSTALL_MARKER, True)

        market_calendar.load_cn_market_calendar_evidence = scoped_loader
        composition.build_model_market_data_service = scoped_factory
        _INSTALLED = True
