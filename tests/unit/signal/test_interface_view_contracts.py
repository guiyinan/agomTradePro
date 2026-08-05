"""HTTP presentation contracts for signal page and API views."""

from __future__ import annotations

import json
from types import SimpleNamespace

from django.test import RequestFactory
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.signal.domain.rules import Eligibility
from apps.signal.interface import views


class _StaffRequestFactory(RequestFactory):
    """Attach an authenticated staff principal to direct view requests."""

    def request(self, **request):
        result = super().request(**request)
        result.user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
        )
        return result


def _json(response) -> dict[str, object]:
    return json.loads(response.content)


def test_page_helpers_and_signal_status_actions(monkeypatch) -> None:
    """Page filters and status actions delegate without owning persistence logic."""
    request = _StaffRequestFactory().get(
        "/signals",
        {"status": "pending", "asset_class": "equity", "direction": "LONG", "search": "A"},
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        views,
        "build_signal_management_context",
        lambda **kwargs: captured.update(kwargs) or {"signals": []},
    )
    monkeypatch.setattr(views, "render", lambda request, template, context: (template, context))
    assert views.signal_manage_view(request) == ("signal/manage.html", {"signals": []})
    assert captured["status_filter"] == "pending"

    monkeypatch.setattr(
        views, "get_current_regime_payload", lambda: {"dominant_regime": "Recovery"}
    )
    monkeypatch.setattr(views, "get_recommended_assets_payload", lambda regime: [regime])
    assert views.get_current_regime()["dominant_regime"] == "Recovery"
    assert views.get_recommended_assets("Recovery") == ["Recovery"]

    monkeypatch.setattr(
        views,
        "update_investment_signal_status",
        lambda **kwargs: {"asset_code": "000001.SZ"} if kwargs["signal_id"] == "1" else None,
    )
    factory = _StaffRequestFactory()
    assert _json(views.approve_signal_view(factory.post("/", {"signal_id": "1"})))["success"]
    assert views.approve_signal_view(factory.post("/", {"signal_id": "missing"})).status_code == 404
    assert (
        "已拒绝"
        in _json(views.reject_signal_view(factory.post("/", {"signal_id": "1", "reason": "risk"})))[
            "message"
        ]
    )
    assert (
        "已证伪"
        in _json(views.invalidate_signal_view(factory.post("/", {"signal_id": "1"})))["message"]
    )

    monkeypatch.setattr(
        views,
        "delete_investment_signal_record",
        lambda signal_id: "000001.SZ" if signal_id == "1" else None,
    )
    assert _json(views.delete_signal_view(factory.delete("/"), 1))["success"]
    assert views.delete_signal_view(factory.delete("/"), 2).status_code == 404


def test_create_signal_validation_and_success_contract(monkeypatch) -> None:
    """Signal creation validates JSON, performs admission, and returns the persisted id."""
    factory = _StaffRequestFactory()
    assert views.create_signal_view(factory.get("/")).status_code == 302
    missing = views.create_signal_view(factory.post("/", {"asset_code": "000001.SZ"}))
    assert _json(missing)["success"] is False
    malformed = views.create_signal_view(
        factory.post(
            "/",
            {
                "asset_code": "000001.SZ",
                "asset_class": "equity",
                "logic_desc": "logic",
                "invalidation_rules": "{",
            },
        )
    )
    assert "格式错误" in _json(malformed)["error"]

    monkeypatch.setattr(
        views,
        "get_current_regime",
        lambda: {"dominant_regime": "Recovery", "confidence": 0.88},
    )

    class _Validator:
        def execute(self, request):
            return SimpleNamespace(is_approved=True, warnings=["reviewed"], rejection_record=None)

    monkeypatch.setattr(views, "ValidateSignalUseCase", _Validator)
    monkeypatch.setattr(
        views,
        "create_investment_signal_record",
        lambda **kwargs: {"id": 7, "rejection_reason": kwargs["rejection_reason"]},
    )
    response = views.create_signal_view(
        factory.post(
            "/",
            {
                "asset_code": "000001.SZ",
                "asset_class": "equity",
                "direction": "LONG",
                "logic_desc": "PMI expands",
                "target_regime": "Recovery",
                "invalidation_rules": json.dumps(
                    {
                        "conditions": [
                            {
                                "indicator": "PMI",
                                "condition": "lt",
                                "threshold": 50,
                                "duration": 2,
                                "compare_with": "prev_value",
                            }
                        ]
                    }
                ),
            },
        )
    )
    payload = _json(response)
    assert payload == {
        "success": True,
        "signal_id": 7,
        "is_approved": True,
        "warnings": ["reviewed"],
        "rejection_reason": None,
    }
    assert views.generate_invalidation_logic_text({}) == "未设置证伪条件"
    assert "PMI < 50 连续2期 (较前值)" in views.generate_invalidation_logic_text(
        {
            "conditions": [
                {
                    "indicator": "PMI",
                    "condition": "lt",
                    "threshold": 50,
                    "duration": 2,
                    "compare_with": "prev_value",
                }
            ]
        }
    )


def test_invalidation_eligibility_ai_and_indicator_endpoints(monkeypatch) -> None:
    """Auxiliary endpoints preserve their success and failure response shapes."""
    factory = _StaffRequestFactory()

    class _CheckService:
        def check_signal(self, signal_id):
            if signal_id == 1:
                return SimpleNamespace(
                    is_invalidated=True,
                    reason="threshold",
                    checked_conditions=[{"matched": True}],
                )
            return None

    monkeypatch.setattr(views, "InvalidationCheckService", _CheckService)
    assert _json(views.check_invalidation_view(factory.post("/"), 1))["is_invalidated"]
    assert _json(views.check_invalidation_view(factory.post("/"), 2))["success"] is False
    assert views.run_batch_check_view(factory.get("/")).status_code == 302

    import apps.signal.application.invalidation_checker as checker

    monkeypatch.setattr(checker, "check_and_invalidate_signals", lambda: {"checked": 3})
    assert _json(views.run_batch_check_view(factory.post("/")))["checked"] == 3

    assert views.signal_eligibility_info_view(factory.get("/")).status_code == 400
    monkeypatch.setattr(
        views,
        "get_eligibility_matrix",
        lambda: {"equity": {"Recovery": Eligibility.PREFERRED}},
    )
    eligible = _json(
        views.signal_eligibility_info_view(
            factory.get("/", {"asset_class": "equity", "regime": "Recovery"})
        )
    )
    assert eligible["eligible"] is True

    import apps.signal.application.ai_invalidation_helper as ai_helper

    monkeypatch.setattr(
        ai_helper,
        "ai_parse_invalidation_logic",
        lambda text: {
            "conditions": [{"indicator": "PMI"}],
            "logic": "AND",
            "explanation": text,
        },
    )
    assert (
        _json(
            views.ai_parse_logic_view(
                factory.post("/", data=b"{}", content_type="application/json")
            )
        )["success"]
        is False
    )
    parsed = views.ai_parse_logic_view(
        factory.post(
            "/", data=json.dumps({"text": "PMI below 50"}), content_type="application/json"
        )
    )
    assert _json(parsed)["confidence"] == 0.8
    assert (
        _json(
            views.ai_parse_logic_view(factory.post("/", data=b"{", content_type="application/json"))
        )["success"]
        is False
    )

    monkeypatch.setattr(
        "apps.signal.interface.views.get_available_indicators_for_frontend",
        lambda: [{"code": "PMI", "category": "growth"}, {"code": "CPI"}],
    )
    indicators = _json(views.get_indicators_view(factory.get("/")))
    assert indicators["total"] == 2
    assert set(indicators["grouped"]) == {"growth", "其他"}


def test_unified_signal_viewset_actions(monkeypatch) -> None:
    """Unified ViewSet actions validate inputs and delegate query operations."""
    import apps.signal.application.unified_service as unified

    class _Service:
        def get_unified_signals(self, **kwargs):
            return [{"id": 1}]

        def collect_all_signals(self, calc_date):
            return {"collected": calc_date.isoformat()}

        def get_signal_summary(self, **kwargs):
            return {"total": 4}

    monkeypatch.setattr(unified, "UnifiedSignalService", _Service)
    monkeypatch.setattr(views, "get_pending_unified_signals", lambda **kwargs: [kwargs])
    monkeypatch.setattr(views, "get_unified_signals_by_asset", lambda **kwargs: [kwargs])
    monkeypatch.setattr(views, "mark_unified_signal_executed", lambda pk: pk == "1")
    factory = APIRequestFactory()

    def _request(method: str, path: str = "/", data=None):
        request = getattr(factory, method)(path, data, format="json" if method == "post" else None)
        force_authenticate(
            request,
            user=SimpleNamespace(is_authenticated=True, is_staff=True, pk=1),
        )
        return request

    invalid_list = views.UnifiedSignalViewSet.as_view({"get": "list"})(
        _request("get", "/?date=invalid&source=alpha&min_priority=2")
    )
    assert invalid_list.status_code == 400
    listed = views.UnifiedSignalViewSet.as_view({"get": "list"})(
        _request("get", "/?date=2026-07-24&source=alpha&min_priority=2")
    )
    assert listed.data["count"] == 1
    invalid = views.UnifiedSignalViewSet.as_view({"post": "collect"})(
        _request("post", data={"date": "not-a-date"})
    )
    assert invalid.status_code == 400
    collected = views.UnifiedSignalViewSet.as_view({"post": "collect"})(_request("post", data={}))
    assert "collected" in collected.data["results"]
    summary = views.UnifiedSignalViewSet.as_view({"get": "summary"})(_request("get", "/?days=7"))
    assert summary.data == {"total": 4}
    pending = views.UnifiedSignalViewSet.as_view({"get": "pending"})(
        _request("get", "/?min_priority=8&type=alpha")
    )
    assert pending.data["count"] == 1
    missing = views.UnifiedSignalViewSet.as_view({"get": "by_asset"})(_request("get"))
    assert missing.status_code == 400
    by_asset = views.UnifiedSignalViewSet.as_view({"get": "by_asset"})(
        _request("get", "/?asset_code=000001.SZ&days=5")
    )
    assert by_asset.data["asset_code"] == "000001.SZ"
    execute = views.UnifiedSignalViewSet.as_view({"post": "execute"})
    assert execute(_request("post", data={}), pk="1").status_code == 200
    assert execute(_request("post", data={}), pk="missing").status_code == 404
