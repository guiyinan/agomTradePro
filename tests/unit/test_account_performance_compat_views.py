"""Tests for Account performance compatibility delegation boundaries."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from apps.account.interface import performance_compat_views


@pytest.mark.parametrize("portfolio_id", [None, True, 0, -1, 1.0, "1"])
def test_resolve_account_id_rejects_invalid_portfolio_ids_without_lookup(
    monkeypatch: pytest.MonkeyPatch,
    portfolio_id: object,
) -> None:
    def unexpected_lookup(value: int) -> int:
        raise AssertionError("invalid portfolio ids must not reach the repository")

    monkeypatch.setattr(
        performance_compat_views.interface_services,
        "get_unified_account_id_for_portfolio",
        unexpected_lookup,
    )

    assert performance_compat_views._resolve_account_id(portfolio_id) is None


@pytest.mark.parametrize("mapped_account_id", [None, True, 0, -1, 2_147_483_648, "21"])
def test_resolve_account_id_rejects_invalid_mapping_results(
    monkeypatch: pytest.MonkeyPatch,
    mapped_account_id: object,
) -> None:
    monkeypatch.setattr(
        performance_compat_views.interface_services,
        "get_unified_account_id_for_portfolio",
        lambda portfolio_id: mapped_account_id,
    )

    assert performance_compat_views._resolve_account_id(7) is None


def test_delegate_forwards_raw_request_and_account_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeViewClass:
        @classmethod
        def as_view(cls, **initkwargs: object) -> Callable[..., object]:
            def view(raw_request: object, **kwargs: object) -> Response:
                captured["raw_request"] = raw_request
                captured["kwargs"] = kwargs
                return Response({"ok": True})

            return view

    monkeypatch.setattr(
        performance_compat_views,
        "get_simulated_trading_view",
        lambda view_key: FakeViewClass,
    )
    raw_request = APIRequestFactory().get("/compat/?start_date=2026-01-01")
    request = Request(raw_request)

    response = performance_compat_views._delegate(
        request,
        21,
        "account-performance-report",
    )

    assert response.status_code == 200
    assert response.data == {"ok": True}
    assert captured == {
        "raw_request": raw_request,
        "kwargs": {"account_id": 21},
    }


def test_delegate_fails_closed_without_logging_registry_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_resolution(view_key: str) -> object:
        raise RuntimeError("registry-secret-token")

    monkeypatch.setattr(
        performance_compat_views,
        "get_simulated_trading_view",
        fail_resolution,
    )
    request = Request(APIRequestFactory().get("/compat/"))

    with caplog.at_level("ERROR"):
        response = performance_compat_views._delegate(
            request,
            21,
            "account-performance-report",
        )

    assert response.status_code == 503
    assert response.data == {"error": "账户服务暂时不可用"}
    assert "RuntimeError" in caplog.text
    assert "registry-secret-token" not in caplog.text


def test_delegate_rejects_non_response_results(monkeypatch: pytest.MonkeyPatch) -> None:
    class InvalidViewClass:
        @classmethod
        def as_view(cls, **initkwargs: object) -> Callable[..., object]:
            return lambda raw_request, **kwargs: {"unsafe": "payload"}

    monkeypatch.setattr(
        performance_compat_views,
        "get_simulated_trading_view",
        lambda view_key: InvalidViewClass,
    )
    request = Request(APIRequestFactory().get("/compat/"))

    response = performance_compat_views._delegate(
        request,
        21,
        "account-performance-report",
    )

    assert response.status_code == 503
    assert response.data == {"error": "账户服务暂时不可用"}
