"""Admin-facing live server log views."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Concatenate, ParamSpec, cast

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from .log_buffer import dump_as_text, get_entries

P = ParamSpec("P")
LogView = Callable[Concatenate[HttpRequest, P], HttpResponse]


@staff_member_required
def server_logs_page(request: HttpRequest) -> HttpResponse:
    return render(request, "admin/server_logs.html")


@staff_member_required
def server_logs_stream(request: HttpRequest) -> JsonResponse:
    try:
        since = int(request.GET.get("since", "0"))
    except ValueError:
        since = 0
    try:
        limit = int(request.GET.get("limit", "200"))
    except ValueError:
        limit = 200

    entries, last_id = get_entries(since_id=since, limit=limit)
    return JsonResponse({"entries": entries, "last_id": last_id, "count": len(entries)})


@staff_member_required
def server_logs_export(request: HttpRequest) -> HttpResponse:
    content = dump_as_text()
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    response = HttpResponse(content, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="server_logs_{stamp}.txt"'
    return response


def _extract_token(request: HttpRequest) -> str:
    auth_value = request.META.get("HTTP_AUTHORIZATION", "")
    auth = auth_value.strip() if isinstance(auth_value, str) else ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token_value = request.META.get("HTTP_X_DEBUG_TOKEN", "")
    return token_value.strip() if isinstance(token_value, str) else ""


def _client_ip(request: HttpRequest) -> str:
    forwarded_value = request.META.get("HTTP_X_FORWARDED_FOR", "")
    xff = forwarded_value if isinstance(forwarded_value, str) else ""
    if xff:
        return xff.split(",")[0].strip()
    remote_value = request.META.get("REMOTE_ADDR", "")
    return remote_value if isinstance(remote_value, str) else ""


def _require_debug_api_auth(view_func: LogView[P]) -> LogView[P]:
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> HttpResponse:
        if not getattr(settings, "AUTOMATION_DEBUG_API_ENABLED", False):
            return JsonResponse({"detail": "debug api disabled"}, status=404)

        allowlist = {
            str(item) for item in getattr(settings, "AUTOMATION_DEBUG_API_IP_ALLOWLIST", []) if item
        }
        if allowlist:
            ip = _client_ip(request)
            if ip not in allowlist:
                return JsonResponse({"detail": "ip not allowed"}, status=403)

        provided = _extract_token(request)
        configured = [
            str(token) for token in getattr(settings, "AUTOMATION_DEBUG_API_TOKENS", []) if token
        ]
        authorized = any(hmac.compare_digest(provided, token) for token in configured)
        if not authorized:
            response = JsonResponse({"detail": "invalid token"}, status=401)
            response["WWW-Authenticate"] = "Bearer"
            return response

        return view_func(request, *args, **kwargs)

    return cast(LogView[P], _wrapped)


@_require_debug_api_auth
def automation_server_logs_stream(request: HttpRequest) -> JsonResponse:
    try:
        since = int(request.GET.get("since", "0"))
    except ValueError:
        since = 0
    try:
        limit = int(request.GET.get("limit", "200"))
    except ValueError:
        limit = 200

    max_limit = int(getattr(settings, "AUTOMATION_DEBUG_API_MAX_LIMIT", 1000))
    limit = max(1, min(limit, max_limit))

    entries, last_id = get_entries(since_id=since, limit=limit)
    return JsonResponse({"entries": entries, "last_id": last_id, "count": len(entries)})


@_require_debug_api_auth
def automation_server_logs_export(request: HttpRequest) -> HttpResponse:
    content = dump_as_text()
    return HttpResponse(content, content_type="text/plain; charset=utf-8")
