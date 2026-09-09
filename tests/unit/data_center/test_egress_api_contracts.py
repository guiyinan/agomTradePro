"""HTTP boundaries for regional egress management and diagnostics."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.data_center.interface import egress_api_views as views


def staff_request(method, data=None, *, staff=True):
    request = getattr(APIRequestFactory(), method)(
        "/api/data-center/egress/", data=data, format="json"
    )
    force_authenticate(
        request, user=SimpleNamespace(pk=987654, is_authenticated=True, is_staff=staff)
    )
    return request


@pytest.mark.parametrize(
    "view,method,args",
    [
        (views.egress_endpoint_list, "get", ()),
        (views.egress_endpoint_detail, "patch", (1,)),
        (views.egress_endpoint_test, "post", (1,)),
        (views.egress_rule_list, "post", ()),
        (views.egress_rule_detail, "patch", (1,)),
        (views.egress_rule_preview, "post", ()),
        (views.egress_diagnostics, "post", ()),
    ],
)
def test_nonstaff_cannot_manage_or_probe(view, method, args):
    response = view(staff_request(method, {}, staff=False), *args)
    assert response.status_code == 403
    response.render()
    assert response["Content-Type"].startswith("application/json")


def test_endpoint_list_uses_safe_service_projection(monkeypatch):
    record = SimpleNamespace(to_dict=lambda: {"id": 1, "name": "CN", "password_configured": True})
    monkeypatch.setattr(views.egress_service, "list_endpoints", lambda: (record,))
    response = views.egress_endpoint_list(staff_request("get"))
    response.render()
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.data == {"results": [{"id": 1, "name": "CN", "password_configured": True}]}


def test_blocked_diagnostic_never_reports_success(monkeypatch):
    report = SimpleNamespace(to_dict=lambda: {"outcome": "blocked", "error_code": "EGRESS_NO_RULE"})
    monkeypatch.setattr(views.egress_service, "test_endpoint", lambda _id, context=None: report)
    response = views.egress_endpoint_test(staff_request("post", {}), 1)
    assert response.status_code == 200
    assert response.data["success"] is False
    assert response.data["data"]["outcome"] == "blocked"


def test_invalid_input_never_reaches_endpoint_writer(monkeypatch):
    writer = Mock()
    monkeypatch.setattr(views.egress_service, "create_endpoint", writer)
    response = views.egress_endpoint_list(
        staff_request(
            "post",
            {
                "name": "CN",
                "region": "cn",
                "protocol": "http",
                "host": "frpc_egress_visitor",
                "port": 70000,
            },
        )
    )
    assert response.status_code == 400
    writer.assert_not_called()


def test_configuration_error_does_not_echo_secret_text(monkeypatch):
    def invalid(_id, _payload):
        raise ValueError("http://private-user:private-password@proxy")

    monkeypatch.setattr(views.egress_service, "update_endpoint", invalid)
    response = views.egress_endpoint_detail(staff_request("patch", {"enabled": True}), 1)
    response.render()
    assert response.status_code == 400
    assert b"private-password" not in response.content
    assert response.data["error_code"] == "EGRESS_INVALID_CONFIGURATION"


def test_embedded_target_credentials_never_reach_diagnostics(monkeypatch):
    diagnose = Mock()
    monkeypatch.setattr(views.egress_service, "diagnose_route", diagnose)
    response = views.egress_diagnostics(
        staff_request(
            "post",
            {
                "provider_id": 1,
                "dataset_key": "equity.price.bar",
                "deployment_region": "overseas",
                "url": "https://private-user:private-password@example.com/data",
            },
        )
    )
    response.render()
    assert response.status_code == 400
    assert b"private-password" not in response.content
    diagnose.assert_not_called()


def test_wildcard_request_context_returns_bad_request(monkeypatch):
    diagnose = Mock()
    monkeypatch.setattr(views.egress_service, "diagnose_route", diagnose)
    response = views.egress_diagnostics(
        staff_request(
            "post",
            {
                "provider_id": 1,
                "dataset_key": "*",
                "deployment_region": "overseas",
                "url": "https://example.com/daily",
            },
        )
    )
    assert response.status_code == 400
    diagnose.assert_not_called()
