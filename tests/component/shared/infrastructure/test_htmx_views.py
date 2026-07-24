"""Behavioral regression tests for shared HTMX class-based view helpers."""

from __future__ import annotations

import json

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from shared.infrastructure.htmx.views import (
    HtmxDeleteView,
    HtmxFormView,
    HtmxPartialView,
    HtmxResponseMixin,
)


class RequiredNameForm(forms.Form):
    name = forms.CharField()


def test_htmx_form_invalid_serializes_real_error_list() -> None:
    form = RequiredNameForm(data={})
    assert form.is_valid() is False
    view = HtmxFormView()
    view.request = RequestFactory().post("/form/", HTTP_HX_REQUEST="true")

    response = view.form_invalid(form)
    payload = json.loads(response.content)

    assert response.status_code == 400
    assert payload["success"] is False
    assert isinstance(payload["errors"]["name"], str)
    assert payload["errors"]["name"]


def test_delete_view_requires_explicit_model() -> None:
    view = HtmxDeleteView()
    view.kwargs = {"pk": 1}

    with pytest.raises(ImproperlyConfigured, match="requires a model"):
        view.get_object()


def test_partial_view_requires_explicit_template() -> None:
    with pytest.raises(ImproperlyConfigured, match="requires template_name"):
        HtmxPartialView().get_template_name()


def test_response_mixin_uses_cooperative_renderer_and_adds_htmx_header() -> None:
    class BaseRenderer:
        request: HttpRequest

        def render_to_response(
            self,
            context: dict[str, object],
            **response_kwargs: object,
        ) -> HttpResponse:
            return HttpResponse(context["body"])

    class MixedView(HtmxResponseMixin, BaseRenderer):
        pass

    view = MixedView()
    view.request = RequestFactory().get("/fragment/", HTTP_HX_REQUEST="true")

    response = view.render_to_response({"body": "ok"})

    assert response.content == b"ok"
    assert response["HX-Trigger"] == "contentUpdated"
