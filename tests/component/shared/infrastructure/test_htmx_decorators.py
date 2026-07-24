"""Behavioral regression tests for shared HTMX view decorators."""

from __future__ import annotations

from types import SimpleNamespace

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.test import RequestFactory

from shared.infrastructure.htmx.decorators import (
    ajax_required,
    cache_per_user,
    htmx_only,
    htmx_redirect,
    htmx_trigger,
    htmx_view,
)


def _response_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok")


def test_htmx_only_rejects_plain_request_and_accepts_htmx() -> None:
    view = htmx_only(_response_view)

    rejected = view(RequestFactory().get("/fragment/"))
    accepted = view(RequestFactory().get("/fragment/", HTTP_HX_REQUEST="true"))

    assert rejected.status_code == 400
    assert accepted.status_code == 200


def test_ajax_required_accepts_xml_http_request() -> None:
    request = RequestFactory().get(
        "/fragment/",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert ajax_required(_response_view)(request).status_code == 200


def test_htmx_view_adds_default_headers_without_overwriting_trigger() -> None:
    @htmx_view
    def view(request: HttpRequest) -> HttpResponse:
        response = HttpResponse("ok")
        response["HX-Trigger"] = "customEvent"
        return response

    response = view(RequestFactory().get("/fragment/", HTTP_HX_REQUEST="true"))

    assert response["HX-Trigger"] == "customEvent"
    assert response["X-HTMX-Response"] == "true"


def test_htmx_trigger_and_redirect_write_protocol_headers() -> None:
    request = RequestFactory().get("/fragment/", HTTP_HX_REQUEST="true")
    triggered = htmx_trigger("itemsUpdated")(_response_view)(request)

    @htmx_redirect
    def redirect_view(request: HttpRequest) -> HttpResponse:
        return HttpResponseRedirect("/target/")

    redirected = redirect_view(request)

    assert triggered["HX-Trigger"] == "itemsUpdated"
    assert redirected["HX-Redirect"] == "/target/"


def test_cache_per_user_reuses_non_htmx_response() -> None:
    cache.clear()
    calls = 0

    @cache_per_user(timeout=60)
    def view(request: HttpRequest) -> HttpResponse:
        nonlocal calls
        calls += 1
        return HttpResponse(f"call:{calls}")

    request = RequestFactory().get("/page/?tab=one")
    request.user = SimpleNamespace(id=7)  # type: ignore[attr-defined]

    first = view(request)
    second = view(request)

    assert first.content == b"call:1"
    assert second.content == b"call:1"
    assert calls == 1
