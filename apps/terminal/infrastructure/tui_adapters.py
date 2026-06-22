"""Infrastructure adapters for the standalone TUI workbench."""

from __future__ import annotations

import json
from typing import Any

from django.urls import resolve
from rest_framework.test import APIRequestFactory


class TuiInternalActionExecutor:
    """Execute same-process Django/DRF APIs for TUI actions."""

    def __init__(self) -> None:
        self._factory = APIRequestFactory()

    def execute(
        self,
        *,
        method: str,
        endpoint: str,
        params: dict[str, Any],
        body: dict[str, Any],
        user: Any,
    ) -> dict[str, Any]:
        """Execute an internal API endpoint and normalize its response."""

        method = method.upper()
        endpoint = "/" + endpoint.lstrip("/")
        request_method = getattr(self._factory, method.lower())
        if method == "GET":
            request = request_method(endpoint, data=params)
        else:
            request = request_method(endpoint, data=body, format="json")
        request.user = user

        match = resolve(endpoint)
        request.resolver_match = match
        response = match.func(request, *match.args, **match.kwargs)
        status_code = getattr(response, "status_code", 200)
        payload = getattr(response, "data", None)
        if payload is None:
            content = getattr(response, "content", b"")
            text = content.decode("utf-8", errors="replace") if content else ""
            try:
                payload = json.loads(text) if text else ""
            except json.JSONDecodeError:
                payload = text
        return {
            "status_code": status_code,
            "payload": payload,
        }


def get_tui_action_executor() -> TuiInternalActionExecutor:
    """Return the default same-process TUI action executor."""

    return TuiInternalActionExecutor()
