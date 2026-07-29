"""Bounded request classification for Web-to-TUI migration telemetry."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypedDict, cast
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.urls import Resolver404, resolve

Surface = Literal["classic", "tui"]
EventType = Literal["entry", "execution", "form", "confirmation"]
Outcome = Literal[
    "success",
    "client_error",
    "server_error",
    "input_required",
    "confirmation_required",
]

_TUI_ACTION_PATH = re.compile(r"^/api/tui/actions/(?P<action_key>[^/]+)/run/$")
_TUI_SHELL_PATHS = {"/tui", "/tui/"}


class ClassicRouteRecord(TypedDict):
    """One reviewed Classic route mapping."""

    url_name: str
    task_key: str
    screen_key: str
    template_path: str


class TelemetryCatalogPayload(TypedDict):
    """Validated JSON payload used by the runtime classifier."""

    version: str
    source_matrix: str
    source_sha256: str
    classic_routes: list[ClassicRouteRecord]
    tui_task_keys: list[str]


@dataclass(frozen=True)
class UiMigrationTelemetryCatalog:
    """In-memory lookup tables with bounded Prometheus label values."""

    task_by_url_name: Mapping[str, str]
    task_keys: frozenset[str]


@dataclass(frozen=True)
class UiMigrationEvent:
    """One normalized UI migration observation."""

    surface: Surface
    event_type: EventType
    task_key: str
    outcome: Outcome


def _catalog_path() -> Path:
    """Return the checked-in telemetry catalog path."""

    return Path(settings.BASE_DIR) / "config/tui/migration/web_to_tui_telemetry.v1.json"


@lru_cache(maxsize=1)
def load_ui_migration_telemetry_catalog() -> UiMigrationTelemetryCatalog:
    """Load and validate the bounded runtime telemetry catalog once."""

    raw_payload = cast(Any, json.loads(_catalog_path().read_text(encoding="utf-8")))
    if not isinstance(raw_payload, dict):
        raise ValueError("Web-to-TUI telemetry catalog must be a JSON object")
    payload = cast(TelemetryCatalogPayload, raw_payload)
    if payload.get("version") != "web-to-tui-telemetry.v1":
        raise ValueError("Unsupported Web-to-TUI telemetry catalog version")

    route_records = payload.get("classic_routes")
    task_keys = payload.get("tui_task_keys")
    if not isinstance(route_records, list) or not isinstance(task_keys, list):
        raise ValueError("Web-to-TUI telemetry catalog is incomplete")

    task_by_url_name: dict[str, str] = {}
    for record in route_records:
        url_name = str(record.get("url_name") or "").strip()
        task_key = str(record.get("task_key") or "").strip()
        if not url_name or not task_key:
            raise ValueError("Classic telemetry route requires url_name and task_key")
        previous_task = task_by_url_name.get(url_name)
        if previous_task is not None and previous_task != task_key:
            raise ValueError(f"Classic telemetry route is ambiguous: {url_name}")
        task_by_url_name[url_name] = task_key

    bounded_task_keys = frozenset(str(value).strip() for value in task_keys if str(value).strip())
    if not bounded_task_keys:
        raise ValueError("Web-to-TUI telemetry catalog has no task keys")
    if not set(task_by_url_name.values()).issubset(bounded_task_keys):
        raise ValueError("Classic telemetry task is missing from the bounded task catalog")

    return UiMigrationTelemetryCatalog(
        task_by_url_name=task_by_url_name,
        task_keys=bounded_task_keys,
    )


def _outcome(status_code: int) -> Outcome:
    """Map one HTTP status to a fixed, low-cardinality outcome."""

    if status_code >= 500:
        return "server_error"
    if status_code >= 400:
        return "client_error"
    return "success"


def _nested_tui_status(response: HttpResponse) -> tuple[int, Mapping[str, Any]]:
    """Return the action's real status carried inside the outer TUI response."""

    response_payload = getattr(response, "data", None)
    if not isinstance(response_payload, Mapping):
        return response.status_code, {}
    nested_response = response_payload.get("response")
    if not isinstance(nested_response, Mapping):
        return response.status_code, response_payload
    raw_status = nested_response.get("status_code")
    if isinstance(raw_status, bool) or not isinstance(raw_status, int):
        return response.status_code, response_payload
    return raw_status, response_payload


def _classify_tui_action(
    *,
    action_key: str,
    response: HttpResponse,
    catalog: UiMigrationTelemetryCatalog,
) -> UiMigrationEvent | None:
    """Classify one bounded TUI action execution."""

    if action_key not in catalog.task_keys:
        return None
    status_code, payload = _nested_tui_status(response)
    missing_fields = payload.get("missing_fields")
    if status_code == 400 and isinstance(missing_fields, list) and missing_fields:
        return UiMigrationEvent(
            surface="tui",
            event_type="form",
            task_key=action_key,
            outcome="input_required",
        )
    if status_code == 409 and payload.get("confirmation_required") is True:
        return UiMigrationEvent(
            surface="tui",
            event_type="confirmation",
            task_key=action_key,
            outcome="confirmation_required",
        )
    return UiMigrationEvent(
        surface="tui",
        event_type="execution",
        task_key=action_key,
        outcome=_outcome(status_code),
    )


def _classic_task_from_referrer(
    request: HttpRequest,
    catalog: UiMigrationTelemetryCatalog,
) -> str | None:
    """Map a same-origin Classic page's API request to its reviewed task."""

    if not request.path.startswith("/api/"):
        return None
    raw_referrer = str(request.META.get("HTTP_REFERER") or "").strip()
    if not raw_referrer:
        return None

    parsed_referrer = urlsplit(raw_referrer)
    if parsed_referrer.netloc and parsed_referrer.netloc != request.get_host():
        return None
    try:
        referrer_match = resolve(parsed_referrer.path)
    except Resolver404:
        return None
    return catalog.task_by_url_name.get(str(referrer_match.view_name or ""))


def classify_ui_migration_request(
    request: HttpRequest,
    response: HttpResponse,
    *,
    catalog: UiMigrationTelemetryCatalog | None = None,
) -> UiMigrationEvent | None:
    """Classify a request without admitting unbounded label values."""

    user = getattr(request, "user", None)
    if not bool(getattr(user, "is_authenticated", False)):
        return None
    resolved_catalog = catalog or load_ui_migration_telemetry_catalog()
    action_match = _TUI_ACTION_PATH.fullmatch(request.path)
    if action_match:
        return _classify_tui_action(
            action_key=action_match.group("action_key"),
            response=response,
            catalog=resolved_catalog,
        )

    if request.path in _TUI_SHELL_PATHS and request.method == "GET":
        action_key = str(request.GET.get("action") or "").strip()
        if action_key and action_key in resolved_catalog.task_keys:
            task_key = action_key
        else:
            screen_key = str(request.GET.get("screen") or "command-center.overview").strip()
            task_key = f"screen:{screen_key}"
            if task_key not in resolved_catalog.task_keys:
                return None
        return UiMigrationEvent(
            surface="tui",
            event_type="entry",
            task_key=task_key,
            outcome=_outcome(response.status_code),
        )

    classic_referrer_task = _classic_task_from_referrer(request, resolved_catalog)
    if classic_referrer_task is not None:
        return UiMigrationEvent(
            surface="classic",
            event_type="execution",
            task_key=classic_referrer_task,
            outcome=_outcome(response.status_code),
        )

    resolver_match = request.resolver_match
    url_name = str(resolver_match.view_name or "") if resolver_match else ""
    classic_task_key = resolved_catalog.task_by_url_name.get(url_name)
    if classic_task_key is None:
        return None
    return UiMigrationEvent(
        surface="classic",
        event_type="entry" if request.method == "GET" else "execution",
        task_key=classic_task_key,
        outcome=_outcome(response.status_code),
    )
