"""Published static read endpoints must fail closed without server errors."""

from collections.abc import Iterable
from typing import Any

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver

UNSAFE_ROUTE_TOKENS = {
    "approve",
    "batch-delete",
    "cancel",
    "clear",
    "collect",
    "commit",
    "delete",
    "execute",
    "fetch",
    "generate",
    "heartbeat",
    "import",
    "ingest",
    "lease",
    "migrate",
    "publish",
    "recalculate",
    "refresh",
    "reject",
    "repair",
    "replay",
    "reset",
    "resume",
    "revoke",
    "rollback",
    "rotate",
    "run",
    "send",
    "simulate",
    "submitting",
    "sync",
    "toggle",
    "train",
    "trigger",
    "update",
    "upload",
}

EXCLUDED_ROUTE_PREFIXES = {
    "/api/debug/server-logs/stream/",
    "/api/docs/",
    "/api/redoc/",
    "/api/schema/",
}

HTML_FRAGMENT_ROUTES = {
    "/api/dashboard/action-recommendation/",
    "/api/dashboard/attention-items/",
    "/api/dashboard/pulse-card/",
    "/api/dashboard/regime-status/",
    "/api/decision/context/step1/",
    "/api/decision/context/step2/",
    "/api/decision/context/step3/",
    "/api/decision/context/step4/",
    "/api/decision/context/step5/",
    "/api/decision/context/step6/",
}

EMPTY_STATE_REDIRECT_ROUTES = {
    "/api/dashboard/alpha/exit-panel/",
    "/api/dashboard/alpha/factor-panel/",
    "/api/dashboard/alpha/stocks/",
    "/api/dashboard/positions/",
}


def _walk_patterns(
    patterns: Iterable[URLPattern | URLResolver],
    prefix: str = "",
) -> Iterable[tuple[str, URLPattern]]:
    for item in patterns:
        route = f"{prefix}{item.pattern}"
        if isinstance(item, URLResolver):
            yield from _walk_patterns(item.url_patterns, route)
        else:
            yield route, item


def _supports_get(pattern: URLPattern) -> bool:
    callback: Any = pattern.callback
    actions = getattr(callback, "actions", None)
    if isinstance(actions, dict):
        return "get" in actions
    view_class = getattr(callback, "view_class", None) or getattr(callback, "cls", None)
    if view_class is not None:
        return callable(getattr(view_class, "get", None))
    return True


def _normalize_static_route(route: str) -> str | None:
    normalized = route.lstrip("^/").replace("^", "").rstrip("$")
    if not normalized.startswith("api/"):
        return None
    if any(marker in normalized for marker in ("<", ">", "(?P", "\\.")):
        return None
    path = f"/{normalized}"
    if any(path.startswith(prefix) for prefix in EXCLUDED_ROUTE_PREFIXES):
        return None
    segments = {segment for segment in path.lower().split("/") if segment}
    if segments & UNSAFE_ROUTE_TOKENS:
        return None
    return path


def _static_get_routes() -> list[str]:
    routes: set[str] = set()
    for raw_route, pattern in _walk_patterns(get_resolver().url_patterns):
        route = _normalize_static_route(raw_route)
        if route is not None and _supports_get(pattern):
            routes.add(route)
    return sorted(routes)


STATIC_GET_ROUTES = _static_get_routes()


@pytest.mark.django_db
@pytest.mark.parametrize("path", STATIC_GET_ROUTES)
def test_static_authenticated_get_endpoint_never_returns_5xx(
    admin_client: Client,
    path: str,
) -> None:
    """Safe static GET APIs must return a governed response, never a server error."""

    response = admin_client.get(path)

    if path in EMPTY_STATE_REDIRECT_ROUTES:
        assert response.status_code == 302, path
        assert response.headers["Location"].startswith("/dashboard/"), path
        return
    if path in HTML_FRAGMENT_ROUTES:
        assert response.status_code == 200, path
        assert response.headers["Content-Type"].startswith("text/html"), path
        return
    if path == "/api/ready/":
        assert response.status_code in {200, 503}
        assert response.headers["Content-Type"].startswith("application/json")
        return

    assert response.status_code < 500, path
    assert response.status_code not in {301, 302, 307, 308}, path
    content_type = response.headers.get("Content-Type", "")
    assert content_type.startswith(
        ("application/json", "text/plain", "text/csv", "application/octet-stream")
    ), (path, response.status_code, content_type)


def test_static_get_inventory_is_broad_and_deterministic() -> None:
    """The contract must cover the broad published read surface."""

    assert len(STATIC_GET_ROUTES) >= 150
    assert len(STATIC_GET_ROUTES) == len(set(STATIC_GET_ROUTES))
    assert "/api/health/" in STATIC_GET_ROUTES
    assert "/api/regime/navigator/" in STATIC_GET_ROUTES
    assert "/api/signal/" in STATIC_GET_ROUTES
    assert "/api/prompt/chat/models" in STATIC_GET_ROUTES
