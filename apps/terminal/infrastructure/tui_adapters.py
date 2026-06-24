"""Infrastructure adapters for the standalone TUI workbench."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.urls import resolve
from rest_framework.test import APIRequestFactory


class TuiInternalActionExecutor:
    """Execute same-process Django/DRF APIs for TUI actions."""

    def __init__(self) -> None:
        self._factory = APIRequestFactory()

    def _request_host(self) -> str:
        """Return a host accepted by Django for same-process API calls."""

        for value in getattr(settings, "ALLOWED_HOSTS", []):
            host = str(value or "").strip()
            if not host or host == "*" or "*" in host:
                continue
            parsed = urlparse(host if "://" in host else f"//{host}")
            host = parsed.netloc or parsed.path
            host = host.strip().lstrip(".")
            if host:
                return host
        return "localhost"

    def execute(
        self,
        *,
        method: str,
        endpoint: str,
        params: dict[str, Any],
        body: dict[str, Any],
        user: Any,
        session: Any | None = None,
    ) -> dict[str, Any]:
        """Execute an internal API endpoint and normalize its response."""

        method = method.upper()
        endpoint = "/" + endpoint.lstrip("/")
        request_method = getattr(self._factory, method.lower())
        request_options = {"HTTP_HOST": self._request_host()}
        if method == "GET":
            request = request_method(endpoint, data=params, **request_options)
        else:
            request = request_method(endpoint, data=body, format="json", **request_options)
        request.user = user
        if session is not None:
            request.session = session

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
