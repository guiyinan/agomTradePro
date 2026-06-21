"""Infrastructure adapters for the standalone TUI workbench."""

from __future__ import annotations

import json
from typing import Any

from django.urls import resolve
from rest_framework.test import APIRequestFactory

from apps.ai_capability.infrastructure.collectors.api_collector import ApiCapabilityCollector


class TuiApiCapabilityProvider:
    """Normalize auto-collected API capabilities for TUI application services."""

    def collect(self) -> list[dict[str, Any]]:
        """Return API capability records without leaking domain enum objects."""

        records: list[dict[str, Any]] = []
        for capability in ApiCapabilityCollector().collect():
            target = dict(capability.execution_target or {})
            endpoint = str(target.get("path") or "").strip()
            method = str(target.get("method") or "").upper()
            if not endpoint or not method:
                continue
            endpoint = "/" + endpoint.lstrip("/")
            records.append(
                {
                    "key": capability.capability_key,
                    "name": capability.name,
                    "summary": capability.summary,
                    "category": capability.category,
                    "method": method,
                    "endpoint": endpoint,
                    "route_group": getattr(capability.route_group, "value", str(capability.route_group)),
                    "risk_level": getattr(capability.risk_level, "value", str(capability.risk_level)),
                    "visibility": getattr(capability.visibility, "value", str(capability.visibility)),
                    "requires_confirmation": capability.requires_confirmation,
                    "input_schema": dict(capability.input_schema or {}),
                    "auto_collected": capability.auto_collected,
                }
            )
        return records


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


def get_tui_api_catalog_provider() -> TuiApiCapabilityProvider:
    """Return the default TUI API catalog provider."""

    return TuiApiCapabilityProvider()


def get_tui_action_executor() -> TuiInternalActionExecutor:
    """Return the default same-process TUI action executor."""

    return TuiInternalActionExecutor()
