"""Direct view contracts for share API helpers and degraded paths."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404

from apps.share.interface import views as view_module
from apps.share.interface.views import (
    PublicShareViewSet,
    ShareLinkViewSet,
    ShareVisibilityMixin,
    _as_float,
    _as_iso_datetime,
    _asset_type_label,
    _authenticated_user_id,
    _direction_label,
    _non_empty,
    _normalize_portfolio_type,
    _optional_form_int,
    _required_form_int,
    _required_id,
    _required_short_code,
)


class Session(dict[str, object]):
    modified = False


def _request(
    *,
    data: dict[str, object] | None = None,
    query: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=7),
        data=data or {},
        query_params=query or {},
        session=Session(),
        META={
            "HTTP_X_FORWARDED_FOR": "203.0.113.7, 10.0.0.1",
            "HTTP_USER_AGENT": "pytest",
            "HTTP_REFERER": "https://example.test",
        },
    )


def _model(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 11,
        "short_code": "abc123",
        "title": "组合",
        "subtitle": "说明",
        "theme": "bloomberg",
        "show_amounts": False,
        "show_positions": True,
        "show_transactions": True,
        "show_decision_summary": True,
        "show_decision_evidence": False,
        "show_invalidation_logic": False,
        "owner": SimpleNamespace(
            get_full_name=lambda: "",
            username="owner",
            email="owner@example.test",
        ),
        "created_at": datetime(2026, 7, 1, tzinfo=UTC),
        "last_snapshot_at": datetime(2026, 7, 2, tzinfo=UTC),
        "requires_password": lambda: False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _entity(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 11,
        "title": "组合",
        "requires_password": lambda: False,
        "is_accessible": lambda _now: (True, SimpleNamespace(value="success")),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _snapshot() -> dict[str, object]:
    return {
        "generated_at": "2026-07-02T00:00:00+00:00",
        "source_range_start": "2026-06-01",
        "source_range_end": "2026-07-01",
        "summary": {
            "portfolio_type": "live",
            "total_value": 1000,
            "current_position": 0.8,
        },
        "performance": {
            "total_return": 0.1,
            "profit_amount": 100,
            "chart_dates": ["2020-01-01", "bad-date", date.today().isoformat()],
            "portfolio_values": [1, 2, 3],
            "benchmark_values": [1, 1.5, 2.5],
        },
        "positions": {
            "items": [{"code": "600000.SH", "market_value": 100, "weight": 0.5}],
            "summary": {
                "total_assets": 1000,
                "position_count": 1,
                "asset_allocation": [{"asset": "equity", "value": 1000, "weight": 1}],
            },
        },
        "transactions": {
            "items": [{"code": "600000.SH", "price": 10, "quantity": 100}]
        },
        "decisions": {
            "items": [{"asset_code": "600000.SH"}],
            "evidence": ["signal"],
            "invalidation_logic": "break support",
        },
    }


def test_scalar_view_helpers_cover_validation_and_labels() -> None:
    assert _normalize_portfolio_type(" 实仓 ") == "real"
    assert _normalize_portfolio_type("paper") == "simulated"
    assert _optional_form_int(12) == 12
    assert _optional_form_int("-1") is None
    assert _required_form_int("2", field_name="account") == 2
    with pytest.raises(ValueError, match="account 必须是整数"):
        _required_form_int("", field_name="account")
    assert _required_id(3, label="link") == 3
    with pytest.raises(ValueError, match="尚未持久化"):
        _required_id(None, label="link")
    assert _authenticated_user_id(SimpleNamespace(id=5)) == 5
    with pytest.raises(PermissionDenied):
        _authenticated_user_id(SimpleNamespace(id=None))
    assert _required_short_code(" abc ") == "abc"
    with pytest.raises(Http404):
        _required_short_code("")
    assert _as_float(None) is None
    assert _as_float("1.25") == 1.25
    assert _as_iso_datetime(None) is None
    assert _as_iso_datetime(datetime(2026, 7, 1, tzinfo=UTC)) == "2026-07-01T00:00:00+00:00"
    assert _non_empty(None, "", [], {"x": 1}) == {"x": 1}
    assert _non_empty(None, "") is None
    assert _direction_label("BUY") == "买入"
    assert _direction_label("") == "观察"
    assert _direction_label("CUSTOM") == "CUSTOM"
    assert _asset_type_label(" Fund ") == "基金"
    assert _asset_type_label("unknown") == "其他"


def test_visibility_session_ip_and_access_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mixin = ShareVisibilityMixin()
    request = _request()
    model = _model(requires_password=lambda: True)
    assert mixin._is_password_verified(request, model) is False
    mixin._mark_password_verified(request, model)
    assert mixin._is_password_verified(request, model) is True
    mixin._clear_password_verified(request, model)
    assert mixin._is_password_verified(request, model) is False
    assert mixin._get_client_ip(request) == "203.0.113.7"
    request.META.pop("HTTP_X_FORWARDED_FOR")
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    assert mixin._get_client_ip(request) == "127.0.0.1"

    logger = MagicMock()
    monkeypatch.setattr(view_module, "ShareAccessUseCases", lambda: logger)
    mixin._log_access(11, request, "success", is_verified=True)
    logger.log_access.assert_called_once()


def test_visibility_filter_removes_all_private_money_and_evidence() -> None:
    filtered = ShareVisibilityMixin()._filter_snapshot_by_visibility(_snapshot(), _model())

    assert "total_value" not in filtered["summary"]
    assert "profit_amount" not in filtered["performance"]
    assert "market_value" not in filtered["positions"]["items"][0]
    assert "total_assets" not in filtered["positions"]["summary"]
    assert "value" not in filtered["positions"]["summary"]["asset_allocation"][0]
    assert "price" not in filtered["transactions"]["items"][0]
    assert "evidence" not in filtered["decisions"]
    assert "invalidation_logic" not in filtered["decisions"]

    hidden = _model(
        show_positions=False,
        show_transactions=False,
        show_decision_summary=False,
        show_decision_evidence=False,
    )
    minimal = ShareVisibilityMixin()._filter_snapshot_by_visibility(_snapshot(), hidden)
    assert "positions" not in minimal
    assert "transactions" not in minimal
    assert "decisions" not in minimal


def test_public_context_and_performance_payload_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        is_enabled=True,
        modal_enabled=True,
        modal_title="声明",
        modal_confirm_text="知悉",
    )
    monkeypatch.setattr(view_module, "get_share_disclaimer_config", lambda: config)
    monkeypatch.setattr(view_module, "get_share_disclaimer_lines", lambda _kind: ["line"])
    mixin = ShareVisibilityMixin()

    context = mixin._build_public_context(
        _model(),
        _snapshot(),
        requires_password=True,
        password_error="wrong",
    )
    assert context["portfolio_type"] == "real"
    assert context["owner_name"] == "owner"
    assert context["requires_password"] is True
    assert context["position_count"] == 1
    assert context["disclaimer_lines"] == ["line"]

    payload = mixin._build_performance_chart_payload(_snapshot(), "1m")
    assert payload["chart_dates"] == ["bad-date", date.today().isoformat()]
    assert payload["portfolio_values"] == [2, 3]
    assert payload["is_empty"] is False

    empty = mixin._build_performance_chart_payload({"performance": {}}, "")
    assert empty["period"] == "1m"
    assert empty["is_empty"] is True


class FakeSerializer:
    def __init__(
        self,
        instance: object | None = None,
        *,
        data: dict[str, object] | None = None,
        context: dict[str, object] | None = None,
        partial: bool = False,
        many: bool = False,
    ) -> None:
        del context, partial, many
        self.validated_data = data or {}
        self.data = {"id": getattr(instance, "id", None)}

    def is_valid(self, *, raise_exception: bool) -> bool:
        return raise_exception


def test_share_link_create_update_and_revoke_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model()
    use_cases = MagicMock()
    use_cases.create_share_link.return_value = _entity()
    use_cases.update_share_link.return_value = _entity()
    use_cases.revoke_share_link.return_value = True
    monkeypatch.setattr(view_module, "CreateShareLinkSerializer", FakeSerializer)
    monkeypatch.setattr(view_module, "UpdateShareLinkSerializer", FakeSerializer)
    monkeypatch.setattr(view_module, "ShareLinkSerializer", FakeSerializer)
    monkeypatch.setattr(view_module, "ShareLinkUseCases", lambda: use_cases)
    monkeypatch.setattr(view_module, "get_share_link_model", lambda _id: model)
    request = _request(data={"account_id": 2, "title": "组合"})
    view = ShareLinkViewSet()

    created = view.create(request)
    assert created.status_code == 201

    monkeypatch.setattr(view, "get_object", lambda: model)
    updated = view.update(_request(data={"title": "新标题"}))
    assert updated.status_code == 200
    assert view.revoke(request, pk="11").data == {"status": "revoked"}

    use_cases.revoke_share_link.return_value = False
    assert view.revoke(request, pk="11").status_code == 400


def test_share_link_create_and_update_failure_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_cases = MagicMock()
    monkeypatch.setattr(view_module, "CreateShareLinkSerializer", FakeSerializer)
    monkeypatch.setattr(view_module, "UpdateShareLinkSerializer", FakeSerializer)
    monkeypatch.setattr(view_module, "ShareLinkSerializer", FakeSerializer)
    monkeypatch.setattr(view_module, "ShareLinkUseCases", lambda: use_cases)
    request = _request(data={"account_id": 2, "title": "组合"})
    view = ShareLinkViewSet()

    use_cases.create_share_link.side_effect = ValueError("bad create")
    assert view.create(request).status_code == 400
    use_cases.create_share_link.side_effect = None
    use_cases.create_share_link.return_value = _entity()
    monkeypatch.setattr(view_module, "get_share_link_model", lambda _id: None)
    assert view.create(request).data["error"] == "创建后的分享链接不存在"

    monkeypatch.setattr(view, "get_object", lambda: _model())
    use_cases.update_share_link.side_effect = ValueError("bad update")
    assert view.update(_request(data={})).status_code == 400
    use_cases.update_share_link.side_effect = None
    use_cases.update_share_link.return_value = None
    assert view.update(_request(data={})).data["error"] == "更新失败"
    use_cases.update_share_link.return_value = _entity()
    assert view.update(_request(data={})).data["error"] == "更新后的分享链接不存在"


def test_share_link_auxiliary_actions_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model()
    view = ShareLinkViewSet()
    monkeypatch.setattr(view, "get_object", lambda: model)
    monkeypatch.setattr(view_module, "list_share_snapshots", lambda _id: [])
    monkeypatch.setattr(view_module, "ShareSnapshotSerializer", FakeSerializer)
    access = MagicMock()
    access.get_access_logs.return_value = [{"id": 1}]
    access.get_access_stats.return_value = {"count": 1}
    monkeypatch.setattr(view_module, "ShareAccessUseCases", lambda: access)
    request = _request()

    assert view.snapshots(request).status_code == 200
    assert view.logs(request).data == [{"id": 1}]
    assert view.stats(request).data == {"count": 1}


def _configure_public(
    monkeypatch: pytest.MonkeyPatch,
    *,
    entity: SimpleNamespace | None,
    model: SimpleNamespace | None,
    snapshot: dict[str, object] | None = None,
    password_valid: bool = True,
) -> MagicMock:
    use_cases = MagicMock()
    use_cases.get_share_link_by_code.return_value = entity
    use_cases.verify_password.return_value = password_valid
    monkeypatch.setattr(view_module, "ShareLinkUseCases", lambda: use_cases)
    monkeypatch.setattr(view_module, "get_public_share_link_model", lambda _code: model)
    monkeypatch.setattr(view_module, "get_live_share_snapshot", lambda **_kwargs: snapshot)
    monkeypatch.setattr(view_module, "PublicShareLinkSerializer", FakeSerializer)
    monkeypatch.setattr(view_module, "ShareAccessRequestSerializer", FakeSerializer)
    monkeypatch.setattr(view_module, "increment_share_link_access_count", MagicMock())
    monkeypatch.setattr(PublicShareViewSet, "_log_access", MagicMock())
    return use_cases


def test_public_retrieve_covers_missing_inaccessible_password_and_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = PublicShareViewSet()
    request = _request()
    _configure_public(monkeypatch, entity=None, model=None)
    assert view.retrieve(request, "missing").status_code == 404

    inaccessible = _entity(
        is_accessible=lambda _now: (False, SimpleNamespace(value="expired"))
    )
    _configure_public(monkeypatch, entity=inaccessible, model=_model())
    assert view.retrieve(request, "expired").status_code == 403

    protected = _entity(requires_password=lambda: True)
    protected_model = _model(requires_password=lambda: True)
    _configure_public(monkeypatch, entity=protected, model=protected_model)
    assert view.retrieve(request, "protected").status_code == 401

    request.session["share_verified_11"] = True
    _configure_public(
        monkeypatch,
        entity=protected,
        model=protected_model,
        snapshot=_snapshot(),
    )
    assert view.retrieve(request, "protected").status_code == 200


def test_public_access_covers_password_paths_and_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = _entity(requires_password=lambda: True)
    model = _model(requires_password=lambda: True)
    use_cases = _configure_public(
        monkeypatch,
        entity=entity,
        model=model,
        snapshot=_snapshot(),
        password_valid=False,
    )
    view = PublicShareViewSet()

    assert view.access(_request(data={}), "code").status_code == 401
    invalid_request = _request(data={"password": "wrong"})
    invalid_request.session["share_verified_11"] = True
    assert view.access(invalid_request, "code").data["error"] == "密码错误"
    assert "share_verified_11" not in invalid_request.session

    use_cases.verify_password.return_value = True
    success_request = _request(data={"password": "correct"})
    response = view.access(success_request, "code")
    assert response.status_code == 200
    assert success_request.session["share_verified_11"] is True
    assert response.data["snapshot"]["summary"]["portfolio_type"] == "live"


@pytest.mark.parametrize("method", ["snapshot", "performance"])
def test_public_data_endpoints_cover_missing_snapshot_and_success(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    entity = _entity()
    model = _model()
    _configure_public(monkeypatch, entity=entity, model=model, snapshot=None)
    view = PublicShareViewSet()
    request = _request(query={"period": "3m"})
    handler = getattr(view, method)
    assert handler(request, "code").status_code == 404

    _configure_public(monkeypatch, entity=entity, model=model, snapshot=_snapshot())
    response = handler(request, "code")
    assert response.status_code == 200


def test_public_data_endpoints_reject_missing_inaccessible_and_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = PublicShareViewSet()
    request = _request()
    for method in (view.snapshot, view.performance):
        _configure_public(monkeypatch, entity=None, model=None)
        assert method(request, "missing").status_code == 404

        inaccessible = _entity(
            is_accessible=lambda _now: (False, SimpleNamespace(value="revoked"))
        )
        _configure_public(monkeypatch, entity=inaccessible, model=_model())
        assert method(request, "revoked").status_code == 403

        protected = _entity(requires_password=lambda: True)
        _configure_public(
            monkeypatch,
            entity=protected,
            model=_model(requires_password=lambda: True),
        )
        assert method(request, "protected").status_code == 401
