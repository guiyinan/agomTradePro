"""Direct branch contracts for account interface views."""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError

from apps.account.interface import views as view_module


def _raw(function: object) -> object:
    return inspect.unwrap(function)


def _request(
    *,
    method: str = "GET",
    post: dict[str, object] | None = None,
    get: dict[str, object] | None = None,
    body: bytes = b"",
) -> SimpleNamespace:
    return SimpleNamespace(
        method=method,
        POST=post or {},
        GET=get or {},
        META={"REMOTE_ADDR": "127.0.0.1"},
        body=body,
        user=SimpleNamespace(id=7, username="admin", is_superuser=False),
        session={},
        build_absolute_uri=lambda _path: "https://example.test/",
    )


def _response(
    _request: object,
    template: str,
    context: dict[str, object] | None = None,
    **kwargs: object,
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=int(kwargs.get("status", 200)),
        template=template,
        context=context or {},
    )


def _redirect(path: str) -> SimpleNamespace:
    return SimpleNamespace(status_code=302, url=path)


@pytest.fixture
def patched_views(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(view_module, "render", _response)
    monkeypatch.setattr(view_module, "redirect", _redirect)
    monkeypatch.setattr(view_module, "_redirect_with_ui_mode", _redirect)
    for level in ("error", "info", "success", "warning"):
        monkeypatch.setattr(view_module.messages, level, MagicMock())


def test_account_helpers_cover_identity_token_and_redirect_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(post={"token_name": " custom ", "access_level": "read"})
    assert view_module._authenticated_user_id(request) == 7
    request.user.id = None
    with pytest.raises(PermissionDenied):
        view_module._authenticated_user_id(request)

    monkeypatch.setattr(view_module, "is_system_admin", lambda user: user == "admin")
    assert view_module.is_admin_user("admin") is True
    monkeypatch.setattr(
        view_module.interface_services,
        "build_token_payload",
        lambda **_kwargs: {"token": 123},
    )
    assert view_module._build_token_payload(
        username="u",
        token_name="n",
        token_value="v",
    ) == {"token": "123"}
    monkeypatch.setattr(
        view_module.interface_services,
        "build_token_payload",
        lambda **_kwargs: "bad",
    )
    assert view_module._build_token_payload(username="u", token_name="n", token_value="v") is None
    assert view_module._get_token_name_from_request(_request(post={"token_name": " named "})) == "named"
    assert view_module._get_token_name_from_request(_request(), "prefix").startswith("prefix-")
    monkeypatch.setattr(
        view_module.interface_services,
        "normalize_token_access_level",
        lambda value: value or "read_only",
    )
    assert view_module._get_token_access_level_from_request(request) == "read"
    assert view_module.get_client_ip(
        SimpleNamespace(META={"HTTP_X_FORWARDED_FOR": "1.2.3.4, 5.6.7.8"})
    ) == "1.2.3.4"
    assert view_module.get_client_ip(SimpleNamespace(META={})) is None


@pytest.mark.parametrize(
    ("post", "service_patch"),
    [
        ({"username": "", "password": ""}, None),
        (
            {"username": "u", "password": "a", "password_confirm": "b"},
            None,
        ),
        (
            {
                "username": "u",
                "password": "p",
                "password_confirm": "p",
                "user_agreement": "on",
                "risk_warning": "on",
            },
            "exists",
        ),
        (
            {
                "username": "u",
                "password": "p",
                "password_confirm": "p",
                "risk_warning": "on",
            },
            None,
        ),
        (
            {
                "username": "u",
                "password": "p",
                "password_confirm": "p",
                "user_agreement": "on",
            },
            None,
        ),
    ],
)
def test_register_validation_paths(
    monkeypatch: pytest.MonkeyPatch,
    patched_views: None,
    post: dict[str, object],
    service_patch: str | None,
) -> None:
    monkeypatch.setattr(view_module.interface_services, "get_system_settings", lambda: {})
    monkeypatch.setattr(
        view_module.interface_services,
        "username_exists",
        lambda _username: service_patch == "exists",
    )
    response = _raw(view_module.register_view)(_request(method="POST", post=post))
    assert response.status_code == 200


def test_register_pending_success_and_error_paths(
    monkeypatch: pytest.MonkeyPatch,
    patched_views: None,
) -> None:
    monkeypatch.setattr(view_module.interface_services, "get_system_settings", lambda: {})
    monkeypatch.setattr(view_module.interface_services, "username_exists", lambda _username: False)
    payload = {
        "username": "u",
        "email": "u@example.test",
        "password": "p",
        "password_confirm": "p",
        "user_agreement": "on",
        "risk_warning": "on",
    }
    registration = SimpleNamespace(
        user=SimpleNamespace(is_superuser=False),
        approval_status="pending",
        display_name="User",
    )
    monkeypatch.setattr(
        view_module.interface_services,
        "register_user",
        lambda **_kwargs: registration,
    )
    assert _raw(view_module.register_view)(_request(method="POST", post=payload)).url == "/account/login/"

    registration.approval_status = "approved"
    monkeypatch.setattr(view_module, "login", MagicMock())
    assert _raw(view_module.register_view)(_request(method="POST", post=payload)).status_code == 302

    for error in (IntegrityError("duplicate"), RuntimeError("service down")):
        monkeypatch.setattr(
            view_module.interface_services,
            "register_user",
            lambda _error=error, **_kwargs: (_ for _ in ()).throw(_error),
        )
        assert _raw(view_module.register_view)(_request(method="POST", post=payload)).status_code == 200


def test_logout_and_token_self_service_paths(
    monkeypatch: pytest.MonkeyPatch,
    patched_views: None,
) -> None:
    monkeypatch.setattr(view_module, "logout", MagicMock())
    assert _raw(view_module.logout_view)(_request()).url == "/account/login/"

    outcome = SimpleNamespace(
        payload={"token": "secret"},
        level="success",
        message="created",
    )
    monkeypatch.setattr(view_module.interface_services, "create_self_token", lambda *_args, **_kwargs: outcome)
    request = _request(method="POST")
    response = _raw(view_module.create_self_token_view)(request)
    assert response.status_code == 302
    assert request.session["self_new_token_payload"] == {"token": "secret"}

    monkeypatch.setattr(
        view_module.interface_services,
        "create_self_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert _raw(view_module.create_self_token_view)(_request(method="POST")).status_code == 302

    for error in (LookupError("missing"), RuntimeError("down")):
        monkeypatch.setattr(
            view_module.interface_services,
            "revoke_self_token",
            lambda *_args, _error=error: (_ for _ in ()).throw(_error),
        )
        assert _raw(view_module.revoke_self_token_view)(_request(method="POST"), 1).status_code == 302


@pytest.mark.parametrize(
    "post",
    [
        {"flow_type": "invalid", "amount": "1", "flow_date": "2026-07-01"},
        {"flow_type": "deposit", "amount": "0", "flow_date": "2026-07-01"},
        {"flow_type": "deposit", "amount": "1"},
        {"flow_type": "deposit", "amount": "1", "flow_date": "bad"},
    ],
)
def test_capital_flow_validation_paths(
    patched_views: None,
    post: dict[str, object],
) -> None:
    assert _raw(view_module.capital_flow_view)(_request(method="POST", post=post)).status_code == 302


def test_capital_flow_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    patched_views: None,
) -> None:
    outcome = SimpleNamespace(level="success", message="saved")
    monkeypatch.setattr(view_module.interface_services, "create_capital_flow", lambda *_args, **_kwargs: outcome)
    post = {"flow_type": "deposit", "amount": "100", "flow_date": "2026-07-01"}
    assert _raw(view_module.capital_flow_view)(_request(method="POST", post=post)).status_code == 302

    monkeypatch.setattr(
        view_module.interface_services,
        "create_capital_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert _raw(view_module.capital_flow_view)(_request(method="POST", post=post)).status_code == 302


def test_apply_backtest_results_success_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        method="POST",
        body=json.dumps({"scale_factor": 0.5}).encode(),
    )
    monkeypatch.setattr(
        view_module.interface_services,
        "apply_backtest_results",
        lambda *_args, **_kwargs: {"backtest_name": "test"},
    )
    assert json.loads(_raw(view_module.apply_backtest_results_view)(request, 3).content)["success"] is True

    for error, status_code in ((ValueError("bad"), 400), (RuntimeError("down"), 500)):
        monkeypatch.setattr(
            view_module.interface_services,
            "apply_backtest_results",
            lambda *_args, _error=error, **_kwargs: (_ for _ in ()).throw(_error),
        )
        assert _raw(view_module.apply_backtest_results_view)(request, 3).status_code == status_code


def test_volatility_api_maps_value_and_generic_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.account.application import volatility_use_cases

    monkeypatch.setattr(
        view_module.interface_services,
        "get_active_portfolio_for_user",
        lambda _id: (_ for _ in ()).throw(ValueError("no portfolio")),
    )
    assert _raw(view_module.portfolio_volatility_api_view)(_request()).status_code == 400

    monkeypatch.setattr(
        view_module.interface_services,
        "get_active_portfolio_for_user",
        lambda _id: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(
        volatility_use_cases,
        "VolatilityAnalysisUseCase",
        lambda: (_ for _ in ()).throw(RuntimeError("analysis down")),
    )
    assert _raw(view_module.portfolio_volatility_api_view)(_request()).status_code == 500


def test_admin_token_actions_cover_success_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    patched_views: None,
) -> None:
    outcome = SimpleNamespace(
        payload={"token": "secret"},
        level="success",
        message="ok",
        username="target",
        token_name="token",
    )
    monkeypatch.setattr(view_module.interface_services, "rotate_user_token", lambda **_kwargs: outcome)
    request = _request(method="POST")
    assert _raw(view_module.rotate_user_token_view)(request, 2).status_code == 302
    assert request.session["new_token_payload"] == {"token": "secret"}

    token_actions = [
        ("rotate_user_token_view", "rotate_user_token", (request, 2)),
        ("revoke_user_token_view", "revoke_user_tokens", (request, 2)),
        ("revoke_access_token_view", "revoke_access_token", (request, 3)),
        ("toggle_user_mcp_view", "toggle_user_mcp", (request, 2)),
    ]
    for view_name, service_name, args in token_actions:
        for error in (User.DoesNotExist(), RuntimeError("down")):
            monkeypatch.setattr(
                view_module.interface_services,
                service_name,
                lambda *_args, _error=error, **_kwargs: (_ for _ in ()).throw(_error),
            )
            assert _raw(getattr(view_module, view_name))(*args).status_code == 302


def test_admin_user_actions_cover_success_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    patched_views: None,
) -> None:
    request = _request(method="POST", post={"rejection_reason": "risk", "rbac_role": "observer"})
    outcome = SimpleNamespace(level="success", message="ok")
    actions = [
        ("approve_user_view", "approve_user"),
        ("reject_user_view", "reject_user"),
        ("set_user_role_view", "set_user_role"),
        ("reset_user_status_view", "reset_user_status"),
    ]
    for view_name, service_name in actions:
        monkeypatch.setattr(
            view_module.interface_services,
            service_name,
            lambda *_args, **_kwargs: outcome,
        )
        assert _raw(getattr(view_module, view_name))(request, 2).status_code == 302
        for error in (User.DoesNotExist(), RuntimeError("down")):
            monkeypatch.setattr(
                view_module.interface_services,
                service_name,
                lambda *_args, _error=error, **_kwargs: (_ for _ in ()).throw(_error),
            )
            assert _raw(getattr(view_module, view_name))(request, 2).status_code == 302


def test_system_settings_error_returns_form(
    monkeypatch: pytest.MonkeyPatch,
    patched_views: None,
) -> None:
    monkeypatch.setattr(
        view_module.interface_services,
        "update_system_settings",
        lambda _post: (_ for _ in ()).throw(ValueError("bad json")),
    )
    monkeypatch.setattr(view_module.interface_services, "build_system_settings_context", lambda: {})
    response = _raw(view_module.system_settings_view)(_request(method="POST"))
    assert response.status_code == 200
