from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from apps.dashboard.interface import macro_views


def _authenticated_request(*, user_id: object = 11) -> HttpRequest:
    request = RequestFactory().get(
        "/api/dashboard/macro-partial/",
        HTTP_HX_REQUEST="true",
    )
    request.user = SimpleNamespace(
        id=user_id,
        pk=user_id,
        is_authenticated=True,
        is_active=True,
        username="admin",
    )
    return request


@pytest.mark.parametrize(
    ("view_name", "expected_template", "expected_marker"),
    [
        ("regime_status_htmx", "components/regime_status_bar.html", "regime"),
        ("pulse_card_htmx", "components/pulse_card.html", "pulse"),
        (
            "action_recommendation_htmx",
            "components/action_recommendation.html",
            "action",
        ),
    ],
)
def test_macro_partial_views_render_typed_component_context(
    monkeypatch,
    view_name: str,
    expected_template: str,
    expected_marker: str,
) -> None:
    navigator = object()
    pulse = object()
    action = object()

    class FakeDashboardViews:
        @staticmethod
        def _load_phase1_macro_components():
            return navigator, pulse, action

        @staticmethod
        def _build_regime_status_context(received_navigator, received_pulse, received_action):
            assert (received_navigator, received_pulse, received_action) == (
                navigator,
                pulse,
                action,
            )
            return {"marker": "regime"}

        @staticmethod
        def _build_pulse_card_context(received_pulse):
            assert received_pulse is pulse
            return {"marker": "pulse"}

        @staticmethod
        def _build_action_recommendation_context(received_action):
            assert received_action is action
            return {"marker": "action"}

    def fake_render(request, template_name, context):
        return HttpResponse(f"{template_name}|{context['marker']}")

    monkeypatch.setattr(macro_views, "_dashboard_views", lambda: FakeDashboardViews())
    monkeypatch.setattr(macro_views, "render", fake_render)

    response = getattr(macro_views, view_name)(_authenticated_request())

    assert response.status_code == 200
    assert response.content.decode() == f"{expected_template}|{expected_marker}"


def test_attention_items_partial_uses_one_persisted_user_scope(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    data = object()
    positioned_data = object()
    navigator = object()
    pulse = object()

    class FakeDashboardViews:
        @staticmethod
        def _build_dashboard_data(user_id):
            calls.append(("build", user_id))
            return data

        @staticmethod
        def _ensure_dashboard_positions(received_data, user_id):
            assert received_data is data
            calls.append(("positions", user_id))
            return positioned_data

        @staticmethod
        def _load_phase1_macro_components():
            return navigator, pulse, None

        @staticmethod
        def _build_attention_items_context(
            received_data,
            received_navigator,
            received_pulse,
        ):
            assert (received_data, received_navigator, received_pulse) == (
                positioned_data,
                navigator,
                pulse,
            )
            return {"marker": "attention"}

    def fake_render(request, template_name, context):
        return HttpResponse(f"{template_name}|{context['marker']}")

    monkeypatch.setattr(macro_views, "_dashboard_views", lambda: FakeDashboardViews())
    monkeypatch.setattr(macro_views, "render", fake_render)

    response = macro_views.attention_items_htmx(_authenticated_request(user_id=27))

    assert response.status_code == 200
    assert calls == [("build", 27), ("positions", 27)]
    assert response.content.decode() == "components/attention_items.html|attention"


@pytest.mark.parametrize("user_id", [None, 0, -1, True, "11"])
def test_attention_items_requires_persisted_integer_user_id(user_id: object) -> None:
    with pytest.raises(PermissionDenied, match="persisted user"):
        macro_views._persisted_user_id(_authenticated_request(user_id=user_id))
