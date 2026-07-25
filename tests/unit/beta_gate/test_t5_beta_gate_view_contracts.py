"""Direct interface contracts for Beta Gate API and page views."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from apps.beta_gate.interface import views as view_module
from apps.beta_gate.interface.views import (
    BetaGateJsonSuggestAPIView,
    BetaGateVersionCompareAPIView,
    GateConfigViewSet,
    GateDecisionViewSet,
    RollbackConfigView,
    VisibilityUniverseViewSet,
)


def _request(
    *,
    data: object | None = None,
    query: dict[str, object] | None = None,
    method: str = "GET",
) -> SimpleNamespace:
    return SimpleNamespace(
        data=data if data is not None else {},
        query_params=query or {},
        method=method,
        POST=data if isinstance(data, dict) else {},
        user=SimpleNamespace(id=1),
    )


def _domain_config() -> SimpleNamespace:
    constraint = SimpleNamespace(to_dict=lambda: {"ok": True})
    return SimpleNamespace(
        config_id="cfg-1",
        risk_profile=SimpleNamespace(value="balanced"),
        version=2,
        is_active=True,
        is_expired=False,
        regime_constraint=constraint,
        policy_constraint=constraint,
        portfolio_constraint=constraint,
        effective_date=date(2026, 7, 1),
        expires_at=None,
    )


def _stored_config() -> SimpleNamespace:
    return SimpleNamespace(to_domain=_domain_config)


def _render(
    _request: object,
    template: str,
    context: dict[str, object],
    **kwargs: object,
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=int(kwargs.get("status", 200)),
        template=template,
        context=context,
    )


def test_version_compare_lists_compares_missing_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MagicMock()
    service.list_recent_versions.return_value = [{"version": 1}]
    service.compare_versions.return_value = {
        "config1": {"version": 1},
        "config2": {"version": 2},
        "differences": {"field": [1, 2]},
    }
    monkeypatch.setattr(view_module, "get_beta_gate_config_query_service", lambda: service)
    view = BetaGateVersionCompareAPIView()

    assert view.get(_request()).data["results"] == [{"version": 1}]
    compared = view.get(_request(query={"version_a": "1", "version_b": "2"}))
    assert compared.data["differences"] == {"field": [1, 2]}

    service.compare_versions.return_value = None
    assert view.get(_request(query={"version1": "1", "version2": "2"})).status_code == 404
    service.list_recent_versions.side_effect = RuntimeError("db down")
    assert view.get(_request()).status_code == 500


def test_rollback_validation_state_success_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MagicMock()
    monkeypatch.setattr(view_module, "get_beta_gate_config_query_service", lambda: service)
    view = RollbackConfigView()
    assert view.post(_request(), None).status_code == 400

    service.get_config_for_edit.return_value = None
    assert view.post(_request(), "missing").status_code == 404
    service.get_config_for_edit.return_value = SimpleNamespace(is_active=True, is_expired=False)
    assert view.post(_request(), "active").status_code == 400
    service.get_config_for_edit.return_value = SimpleNamespace(is_active=False, is_expired=True)
    assert view.post(_request(), "expired").status_code == 400

    service.get_config_for_edit.return_value = SimpleNamespace(is_active=False, is_expired=False)
    service.activate_config.return_value = None
    assert view.post(_request(), "gone").status_code == 404
    service.activate_config.return_value = SimpleNamespace(
        config_id="cfg",
        risk_profile="BALANCED",
        version=3,
        is_active=True,
        effective_date=None,
    )
    assert view.post(_request(), "cfg").data["result"]["risk_profile"] == "balanced"

    service.get_config_for_edit.side_effect = RuntimeError("db down")
    assert view.post(_request(), "cfg").status_code == 500


def test_json_suggest_validates_and_parses_ai_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = BetaGateJsonSuggestAPIView()
    assert view.post(_request(data={"target": "bad", "requirement": "x"})).status_code == 400
    assert view.post(_request(data={"target": "regime", "requirement": ""})).status_code == 400

    monkeypatch.setattr(
        "apps.ai_provider.application.chat_completion.generate_chat_completion",
        lambda **_kwargs: {
            "status": "success",
            "provider_used": "test",
            "content": '{"current_regime":"Recovery"}',
        },
    )
    response = view.post(_request(data={"target": "regime", "requirement": "复苏"}))
    assert response.data["fallback"] is False
    assert response.data["json_object"] == {"current_regime": "Recovery"}

    monkeypatch.setattr(
        "apps.ai_provider.application.chat_completion.generate_chat_completion",
        lambda **_kwargs: {"status": "failed", "error_message": "down"},
    )
    assert view.post(_request(data={"target": "policy", "requirement": "保守"})).data["fallback"] is True

    monkeypatch.setattr(
        "apps.ai_provider.application.chat_completion.generate_chat_completion",
        lambda **_kwargs: {
            "status": "success",
            "content": "[]",
            "provider_used": "test",
        },
    )
    assert view.post(_request(data={"target": "portfolio", "requirement": "分散"})).data[
        "fallback"
    ] is True

    monkeypatch.setattr(
        "apps.ai_provider.application.chat_completion.generate_chat_completion",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider down")),
    )
    assert view.post(_request(data={"target": "regime", "requirement": "复苏"})).data[
        "fallback"
    ] is True


def test_json_parser_handles_plain_fenced_embedded_and_invalid_payloads() -> None:
    view = BetaGateJsonSuggestAPIView()
    assert view._parse_json_from_text("") is None
    assert view._parse_json_from_text('{"a":1}') == {"a": 1}
    assert view._parse_json_from_text('```json\n{"a":2}\n```') == {"a": 2}
    assert view._parse_json_from_text('prefix {"a":3} suffix') == {"a": 3}
    assert view._parse_json_from_text("```json\nbad\n```") is None
    messages = view._build_messages("regime", "复苏")
    assert messages[0]["role"] == "system"
    assert "复苏" in messages[1]["content"]


def test_config_viewset_lists_retrieves_and_maps_errors() -> None:
    repository = MagicMock()
    repository.get_all_active.return_value = [_stored_config()]
    repository.list_latest.return_value = [_stored_config()]
    view = GateConfigViewSet.__new__(GateConfigViewSet)
    view.config_repository = repository

    assert view.list(_request(query={"active_only": "invalid"})).status_code == 400
    assert view.list(_request()).data["results"][0]["config_id"] == "cfg-1"
    assert view.list(_request(query={"active_only": "false"})).data["count"] == 1

    assert view.retrieve(_request(), None).status_code == 400
    repository.get_by_id.return_value = None
    assert view.retrieve(_request(), "missing").status_code == 404
    repository.get_by_id.return_value = _stored_config()
    assert view.retrieve(_request(), "cfg").data["result"]["version"] == 2

    repository.get_all_active.side_effect = RuntimeError("db down")
    assert view.list(_request()).status_code == 500
    repository.get_by_id.side_effect = RuntimeError("db down")
    assert view.retrieve(_request(), "cfg").status_code == 500


def test_config_mutation_helpers_and_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Serializer:
        def __init__(self, *, data: object) -> None:
            self.validated_data = dict(data) if isinstance(data, dict) else {}

        def is_valid(self, *, raise_exception: bool) -> bool:
            return raise_exception

    monkeypatch.setattr(view_module, "GateConfigUpdateSerializer", Serializer)
    view = GateConfigViewSet.__new__(GateConfigViewSet)
    view.config_repository = MagicMock()

    assert view.partial_update(_request(data={}), None).status_code == 400
    monkeypatch.setattr(view_module, "replace_gate_config", lambda _id, _data: None)
    assert view.partial_update(_request(data={}), "missing").status_code == 404
    monkeypatch.setattr(view_module, "replace_gate_config", lambda _id, _data: {"config_id": "new"})
    assert view.update(_request(data={}), "cfg").data["result"] == {"config_id": "new"}

    assert view.destroy(_request(), None).status_code == 400
    monkeypatch.setattr(view_module, "deactivate_gate_config", lambda _id: False)
    assert view.destroy(_request(), "missing").status_code == 404
    monkeypatch.setattr(view_module, "deactivate_gate_config", lambda _id: True)
    assert view.destroy(_request(), "cfg").status_code == 204

    view.action = "create"
    assert isinstance(view.get_permissions()[0], IsAdminUser)
    view.action = "list"
    assert isinstance(view.get_permissions()[0], IsAuthenticated)


def test_decision_viewset_validates_lists_retrieves_and_isolates_errors() -> None:
    decision = SimpleNamespace(
        decision_id="d1",
        asset_code="600000.SH",
        asset_class="equity",
        status="passed",
        current_regime="Recovery",
        policy_level=2,
        regime_confidence=0.8,
        evaluated_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    repository = MagicMock()
    repository.get_recent.return_value = [decision]
    repository.get_by_id.side_effect = [None, decision]
    view = GateDecisionViewSet.__new__(GateDecisionViewSet)
    view.decision_repository = repository

    assert view.list(_request(query={"days": "bad"})).status_code == 400
    assert view.list(_request(query={"days": 7})).data["count"] == 1
    assert view.retrieve(_request(), None).status_code == 400
    assert view.retrieve(_request(), "missing").status_code == 404
    assert view.retrieve(_request(), "d1").data["result"]["decision_id"] == "d1"

    repository.get_recent.side_effect = RuntimeError("db down")
    assert view.list(_request()).status_code == 500
    repository.get_by_id.side_effect = RuntimeError("db down")
    assert view.retrieve(_request(), "d1").status_code == 500


def test_universe_viewset_validation_success_and_errors() -> None:
    repository = MagicMock()
    repository.get_history.return_value = [{"snapshot_id": "s1"}]
    repository.get_by_id.side_effect = [None, {"snapshot_id": "s1"}]
    view = VisibilityUniverseViewSet.__new__(VisibilityUniverseViewSet)
    view.universe_repository = repository

    assert view.list(_request(query={"limit": "bad"})).status_code == 400
    assert view.list(_request(query={"policy_level": "bad"})).status_code == 400
    assert view.list(_request(query={"regime": "Recovery", "policy_level": 2})).data[
        "count"
    ] == 1
    assert view.retrieve(_request(), None).status_code == 400
    assert view.retrieve(_request(), "missing").status_code == 404
    assert view.retrieve(_request(), "s1").data["result"] == {"snapshot_id": "s1"}

    repository.get_history.side_effect = RuntimeError("db down")
    assert view.list(_request()).status_code == 500
    repository.get_by_id.side_effect = RuntimeError("db down")
    assert view.retrieve(_request(), "s1").status_code == 500


def test_template_config_pages_success_not_found_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(view_module, "render", _render)
    monkeypatch.setattr(
        view_module,
        "redirect",
        lambda target: SimpleNamespace(status_code=302, url=target),
    )
    monkeypatch.setattr(view_module.messages, "error", MagicMock())
    monkeypatch.setattr(view_module.messages, "success", MagicMock())
    decision = SimpleNamespace(asset_code="600000.SH")
    service = MagicMock()
    service.get_config_page_context.return_value = {"recent_decisions": [decision]}
    service.get_version_page_context.return_value = {"versions": []}
    service.get_config_for_edit.return_value = None
    service.activate_config.return_value = None
    monkeypatch.setattr(view_module, "get_beta_gate_config_query_service", lambda: service)
    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        lambda _codes: {"600000.SH": "浦发银行"},
    )
    request = _request()

    assert view_module.beta_gate_config_view(request).status_code == 200
    assert decision.asset_name == "浦发银行"
    assert view_module.beta_gate_version_view(request).status_code == 200
    assert view_module.beta_gate_config_edit_view(request, "missing").status_code == 302
    assert view_module.beta_gate_config_activate_view(request, "cfg").status_code == 302

    service.get_config_page_context.side_effect = RuntimeError("db down")
    service.get_version_page_context.side_effect = RuntimeError("db down")
    assert view_module.beta_gate_config_view(request).status_code == 500
    assert view_module.beta_gate_version_view(request).status_code == 500


def test_template_activate_success_and_non_post_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        view_module,
        "redirect",
        lambda target: SimpleNamespace(status_code=302, url=target),
    )
    monkeypatch.setattr(view_module.messages, "success", MagicMock())
    service = SimpleNamespace(
        activate_config=lambda _id: SimpleNamespace(config_id="cfg")
    )
    monkeypatch.setattr(view_module, "get_beta_gate_config_query_service", lambda: service)
    monkeypatch.setattr(view_module.transaction, "atomic", nullcontext)

    assert view_module.beta_gate_config_activate_view(_request(), "cfg").status_code == 302
    assert view_module.beta_gate_config_activate_view(
        _request(method="POST"),
        "cfg",
    ).status_code == 302
