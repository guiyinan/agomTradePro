"""Direct interface contracts for Alpha Trigger API and page views."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rest_framework.exceptions import ValidationError

from apps.alpha_trigger.interface import views as view_module
from apps.alpha_trigger.interface.views import (
    AlphaCandidateViewSet,
    AlphaTriggerViewSet,
    CheckInvalidationView,
    CreateTriggerView,
    EvaluateTriggerView,
    GenerateCandidateView,
    TriggerPerformanceAPIView,
    _parse_statistics_days,
    _required_route_id,
)


def _request(
    *,
    query: dict[str, object] | None = None,
    data: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(query_params=query or {}, data=data or {})


class FakeSerializer:
    def __init__(
        self,
        instance: object | None = None,
        *,
        data: dict[str, object] | None = None,
        many: bool = False,
    ) -> None:
        del many
        self.validated_data = data or {}
        self.data = instance if instance is not None else self.validated_data
        self.fields = {
            "invalidation_conditions": SimpleNamespace(
                to_internal_value=lambda values: [
                    SimpleNamespace(to_domain=lambda value=value: value) for value in values
                ]
            )
        }

    def is_valid(self, *, raise_exception: bool) -> bool:
        return raise_exception


def _patch_serializers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AlphaCandidateSerializer",
        "AlphaTriggerSerializer",
        "CheckInvalidationRequestSerializer",
        "CreateTriggerRequestSerializer",
        "EvaluateTriggerRequestSerializer",
        "GenerateCandidateRequestSerializer",
        "UpdateCandidateStatusRequestSerializer",
        "AlphaTriggerPerformanceQuerySerializer",
    ):
        monkeypatch.setattr(view_module, name, FakeSerializer)


def _trigger_view(trigger_repo: object, candidate_repo: object | None = None) -> AlphaTriggerViewSet:
    view = AlphaTriggerViewSet.__new__(AlphaTriggerViewSet)
    view.trigger_repository = trigger_repo
    view.candidate_repository = candidate_repo or MagicMock()
    return view


def _candidate_view(repository: object) -> AlphaCandidateViewSet:
    view = AlphaCandidateViewSet.__new__(AlphaCandidateViewSet)
    view.candidate_repository = repository
    return view


def test_route_and_statistics_validation_contracts() -> None:
    assert _required_route_id(" id ", label="trigger_id") == "id"
    with pytest.raises(ValidationError):
        _required_route_id(" ", label="trigger_id")
    assert _parse_statistics_days(_request()) == 30
    assert _parse_statistics_days(_request(query={"days": "365"})) == 365
    with pytest.raises(ValidationError, match="integer"):
        _parse_statistics_days(_request(query={"days": "bad"}))
    with pytest.raises(ValidationError, match="between"):
        _parse_statistics_days(_request(query={"days": 0}))


def test_trigger_viewset_list_and_retrieve_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_serializers(monkeypatch)
    repo = MagicMock()
    repo.get_active.return_value = ["active"]
    repo.get_by_asset.return_value = ["asset"]
    repo.get_by_id.side_effect = [None, "trigger"]
    view = _trigger_view(repo)

    assert view.list(_request()).data["count"] == 1
    assert view.list(_request(query={"asset_code": "600000.SH"})).data["results"] == ["asset"]
    assert view.retrieve(_request(), pk="missing").status_code == 404
    assert view.retrieve(_request(), pk="t1").data["result"] == "trigger"

    repo.get_active.side_effect = RuntimeError("db down")
    assert view.list(_request()).status_code == 500
    repo.get_by_id.side_effect = RuntimeError("db down")
    assert view.retrieve(_request(), pk="t1").status_code == 500


def test_trigger_active_regime_and_statistics_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_serializers(monkeypatch)
    repo = MagicMock()
    repo.get_active.return_value = ["active"]
    repo.get_by_regime.return_value = ["regime"]
    repo.get_statistics.return_value = {"count": 2}
    view = _trigger_view(repo)

    assert view.active(_request(query={"min_strength": "strong"})).data["count"] == 1
    assert view.active(_request(query={"min_strength": "INVALID"})).status_code == 200
    assert view.by_regime(_request(), regime="Recovery").data["count"] == 1
    assert view.statistics(_request(query={"days": 7})).data["result"] == {"count": 2}
    assert view.statistics(_request(query={"days": "bad"})).status_code == 400

    repo.get_active.side_effect = RuntimeError("active down")
    assert view.active(_request()).status_code == 500
    repo.get_by_regime.side_effect = RuntimeError("regime down")
    assert view.by_regime(_request(), regime="Recovery").status_code == 500
    repo.get_statistics.side_effect = RuntimeError("stats down")
    assert view.statistics(_request()).status_code == 500


def test_candidate_list_retrieve_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_serializers(monkeypatch)
    repo = MagicMock()
    repo.get_actionable.return_value = ["actionable"]
    repo.get_by_asset.return_value = ["asset"]
    repo.get_by_id.side_effect = [None, "candidate"]
    view = _candidate_view(repo)

    assert view.list(_request()).data["count"] == 1
    assert (
        view.list(
            _request(query={"asset_code": "600000.SH", "status": "ACTIONABLE"})
        ).data["results"]
        == ["asset"]
    )
    assert view.list(_request(query={"asset_code": "600000.SH", "status": "BAD"})).status_code == 200
    assert view.retrieve(_request(), pk="missing").status_code == 404
    assert view.retrieve(_request(), pk="c1").data["result"] == "candidate"

    repo.get_actionable.side_effect = RuntimeError("down")
    assert view.list(_request()).status_code == 500
    repo.get_by_id.side_effect = RuntimeError("down")
    assert view.retrieve(_request(), pk="c1").status_code == 500


def test_candidate_actions_and_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_serializers(monkeypatch)
    repo = MagicMock()
    repo.get_actionable.return_value = ["actionable"]
    repo.get_watch_list.return_value = ["watch"]
    repo.update_status.return_value = "updated"
    repo.get_statistics.return_value = {"count": 1}
    view = _candidate_view(repo)

    assert view.actionable(_request(query={"min_strength": "strong"})).data["count"] == 1
    assert view.actionable(_request(query={"min_strength": "BAD"})).status_code == 200
    assert view.watch_list(_request()).data["results"] == ["watch"]
    assert view.update_status(
        _request(data={"status": "ACTIONABLE"}),
        pk="c1",
    ).data["result"] == "updated"
    assert view.statistics(_request(query={"days": 30})).data["result"] == {"count": 1}
    assert view.statistics(_request(query={"days": 400})).status_code == 400

    repo.get_actionable.side_effect = RuntimeError("actionable down")
    assert view.actionable(_request()).status_code == 500
    repo.get_watch_list.side_effect = RuntimeError("watch down")
    assert view.watch_list(_request()).status_code == 500
    repo.update_status.side_effect = RuntimeError("update down")
    assert view.update_status(
        _request(data={"status": "ACTIONABLE"}),
        pk="c1",
    ).status_code == 500
    repo.get_statistics.side_effect = RuntimeError("stats down")
    assert view.statistics(_request()).status_code == 500


def test_action_views_success_business_failure_and_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_serializers(monkeypatch)
    trigger_repo = MagicMock()
    candidate_repo = MagicMock()

    scenarios = [
        (
            CreateTriggerView,
            "CreateAlphaTriggerUseCase",
            {
                "trigger_type": "momentum_signal",
                "asset_code": "600000.SH",
                "asset_class": "equity",
                "direction": "LONG",
                "trigger_condition": {},
                "invalidation_conditions": [],
                "confidence": 0.8,
            },
            SimpleNamespace(success=True, trigger="trigger", error=None),
        ),
        (
            CheckInvalidationView,
            "CheckTriggerInvalidationUseCase",
            {
                "trigger_id": "t1",
                "current_indicator_values": {},
                "current_regime": "Recovery",
            },
            SimpleNamespace(
                success=True,
                is_invalidated=False,
                reason="valid",
                conditions_met=[],
                error=None,
            ),
        ),
        (
            EvaluateTriggerView,
            "EvaluateAlphaTriggerUseCase",
            {"trigger_id": "t1", "current_data": {}},
            SimpleNamespace(success=True, should_trigger=True, reason="matched", error=None),
        ),
        (
            GenerateCandidateView,
            "GenerateCandidateUseCase",
            {"trigger_id": "t1", "time_window_days": 30},
            SimpleNamespace(success=True, candidate="candidate", error=None),
        ),
    ]

    for view_class, use_case_name, payload, success_response in scenarios:
        use_case = MagicMock()
        use_case.execute.return_value = success_response
        monkeypatch.setattr(view_module, use_case_name, lambda *_args, _use_case=use_case: _use_case)
        view = view_class.__new__(view_class)
        view.trigger_repository = trigger_repo
        if view_class is GenerateCandidateView:
            view.candidate_repository = candidate_repo

        success = view.post(_request(data=payload))
        assert success.status_code == 200

        use_case.execute.return_value = SimpleNamespace(success=False, error="rejected")
        assert view.post(_request(data=payload)).status_code == 400

        use_case.execute.side_effect = RuntimeError("unexpected")
        assert view.post(_request(data=payload)).status_code == 500


def test_action_views_convert_serializer_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidSerializer(FakeSerializer):
        def is_valid(self, *, raise_exception: bool) -> bool:
            raise ValidationError({"field": "invalid"})

    trigger_repo = MagicMock()
    candidate_repo = MagicMock()
    for view_class, serializer_name in (
        (CreateTriggerView, "CreateTriggerRequestSerializer"),
        (CheckInvalidationView, "CheckInvalidationRequestSerializer"),
        (EvaluateTriggerView, "EvaluateTriggerRequestSerializer"),
        (GenerateCandidateView, "GenerateCandidateRequestSerializer"),
    ):
        monkeypatch.setattr(view_module, serializer_name, InvalidSerializer)
        view = view_class.__new__(view_class)
        view.trigger_repository = trigger_repo
        if view_class is GenerateCandidateView:
            view.candidate_repository = candidate_repo
        assert view.post(_request()).status_code == 400


def _render_response(
    _request: object,
    template: str,
    context: dict[str, object],
    *,
    status: int = 200,
) -> SimpleNamespace:
    return SimpleNamespace(status_code=status, template=template, context=context)


def test_template_list_edit_detail_and_candidate_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(view_module, "render", _render_response)
    trigger = SimpleNamespace(asset_code="600000.SH")
    candidate = SimpleNamespace(asset_code="000001.SZ")
    service = SimpleNamespace(
        get_list_context=lambda: {
            "active_triggers": [trigger],
            "actionable_list": [candidate],
            "watch_list": [candidate],
            "candidate_list": [candidate],
        },
        get_edit_context=lambda _id: {"trigger": trigger},
        get_detail_context=lambda _id: {"trigger": trigger, "candidates": [candidate]},
        get_candidate_detail_context=lambda _id: {"candidate": candidate},
        get_create_context=lambda: {"page": "create"},
        get_performance_context=lambda: {"page": "performance"},
    )
    monkeypatch.setattr(view_module, "get_alpha_trigger_page_query_service", lambda: service)
    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        lambda codes: {code: f"name-{code}" for code in codes},
    )
    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_name",
        lambda code: f"name-{code}",
    )
    request = SimpleNamespace()

    assert view_module.alpha_trigger_list_view(request).status_code == 200
    assert trigger.asset_name == "name-600000.SH"
    assert view_module.alpha_trigger_create_view(request).status_code == 200
    assert view_module.alpha_trigger_edit_view(request, "t1").status_code == 200
    assert view_module.alpha_trigger_detail_view(request, "t1").status_code == 200
    assert view_module.alpha_candidate_detail_view(request, "c1").status_code == 200
    assert view_module.alpha_trigger_performance_view(request).status_code == 200
    assert view_module.alpha_trigger_invalidation_builder_view(request).status_code == 200


def test_template_pages_cover_not_found_and_error_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(view_module, "render", _render_response)
    service = MagicMock()
    service.get_edit_context.return_value = None
    service.get_detail_context.return_value = None
    service.get_candidate_detail_context.return_value = None
    monkeypatch.setattr(view_module, "get_alpha_trigger_page_query_service", lambda: service)
    request = SimpleNamespace()

    assert view_module.alpha_trigger_edit_view(request, "missing").status_code == 404
    assert view_module.alpha_trigger_detail_view(request, "missing").status_code == 404
    assert view_module.alpha_candidate_detail_view(request, "missing").status_code == 404

    for function_name, service_method, args in (
        ("alpha_trigger_list_view", "get_list_context", (request,)),
        ("alpha_trigger_create_view", "get_create_context", (request,)),
        ("alpha_trigger_edit_view", "get_edit_context", (request, "t1")),
        ("alpha_trigger_detail_view", "get_detail_context", (request, "t1")),
        ("alpha_candidate_detail_view", "get_candidate_detail_context", (request, "c1")),
        ("alpha_trigger_performance_view", "get_performance_context", (request,)),
    ):
        getattr(service, service_method).side_effect = RuntimeError("page down")
        assert getattr(view_module, function_name)(*args).status_code == 500
        getattr(service, service_method).side_effect = None


def test_performance_api_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_serializers(monkeypatch)
    service = SimpleNamespace(
        get_performance_data=lambda **_kwargs: [{"trigger_id": "t1"}]
    )
    monkeypatch.setattr(view_module, "get_alpha_trigger_page_query_service", lambda: service)
    view = TriggerPerformanceAPIView()

    response = view.get(_request(query={"days": 30, "trigger_id": "t1"}))
    assert response.data["summary"]["total_triggers"] == 1

    service.get_performance_data = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("query down")
    )
    assert view.get(_request(query={"days": 30})).status_code == 500
