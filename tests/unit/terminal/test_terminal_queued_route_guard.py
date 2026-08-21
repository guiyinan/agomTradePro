"""Route-level fail-closed guards for the reserved TAR-01 queued API."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.agent_runtime.application.terminal_agent_run_route_guard import (
    TerminalQueuedRuntimeUnavailable,
    reject_terminal_queued_route,
)
from apps.terminal.interface.queued_runtime_views import (
    TerminalQueuedRunCancelView,
    TerminalQueuedRunEventsView,
    TerminalQueuedRunView,
)

RESERVED_ROUTES = (
    "/api/terminal/runs/",
    "/api/terminal/runs/queue/",
    "/api/terminal/runs/run-20260818-0001/",
    "/api/terminal/runs/run-20260818-0001/events/",
    "/api/terminal/runs/run-20260818-0001/cancel/",
)


def test_application_guard_is_stable_and_fail_closed() -> None:
    """The dormant application boundary raises no-I/O, stable error metadata."""

    with pytest.raises(TerminalQueuedRuntimeUnavailable) as caught:
        reject_terminal_queued_route()

    error = caught.value
    assert error.code == "DISPATCH_UNAVAILABLE"
    assert error.reason_code == "queued_runtime_not_wired"
    assert error.status_code == 503


def test_reserved_routes_resolve_to_dormant_boundary() -> None:
    """Every frozen queued path resolves to the flag-gated durable boundary."""

    expected = {
        RESERVED_ROUTES[0]: TerminalQueuedRunView,
        RESERVED_ROUTES[1]: TerminalQueuedRunView,
        RESERVED_ROUTES[2]: TerminalQueuedRunView,
        RESERVED_ROUTES[3]: TerminalQueuedRunEventsView,
        RESERVED_ROUTES[4]: TerminalQueuedRunCancelView,
    }
    assert {path: resolve(path).func.view_class for path in RESERVED_ROUTES} == expected


@pytest.mark.parametrize("path", RESERVED_ROUTES)
def test_reserved_routes_return_redacted_503_without_agent_composition(path: str) -> None:
    """Authenticated calls never reach the legacy service or a future adapter."""

    factory = APIRequestFactory()
    method = "post" if path.endswith("/runs/") or path.endswith("/cancel/") else "get"
    request = getattr(factory, method)(path, data={}) if method == "post" else factory.get(path)
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True, pk=41))

    response = TerminalQueuedRunView.as_view()(request)

    assert response.status_code == 503
    assert response.data == {
        "error": "Queued terminal runtime is not available.",
        "code": "DISPATCH_UNAVAILABLE",
        "reason_code": "queued_runtime_not_wired",
        "retryable": True,
    }
    assert response["Retry-After"] == "60"


def test_dormant_view_has_no_legacy_or_infrastructure_dependency() -> None:
    """The route guard cannot accidentally invoke inline Agent infrastructure."""

    source_path = Path("apps/terminal/interface/queued_runtime_views.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert all("infrastructure" not in name for name in imported_names)
    assert all("celery" not in name.casefold() for name in imported_names)
    assert "OpenAIAgentsTerminalService" not in source
    assert "_get_terminal_agent_service" not in source
    assert ".objects" not in source
