"""Persisted staff workflow for registering and enabling regional exits."""

from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.config_center.application.public import get_egress_endpoint
from apps.data_center.application import egress_service
from apps.data_center.domain.egress_routing import (
    EgressRouteRule,
    EgressRoutingError,
    EgressStrategy,
)
from apps.data_center.infrastructure.egress_repositories import EgressRoutingRuleRepository
from apps.data_center.infrastructure.models import ProviderConfigModel


@pytest.fixture
def operator(db):
    user = get_user_model().objects.create_user(username="egress-operator", is_staff=True)
    client = Client()
    client.force_login(user)
    return client


def endpoint_payload():
    return {
        "name": "Mainland test",
        "region": "cn",
        "protocol": "http",
        "host": "frpc_egress_visitor",
        "port": 18080,
        "username": "private-proxy-user",
        "password": "private-proxy-password",
        "enabled": False,
        "concurrency_limit": 2,
    }


def post_json(client, url, payload):
    response = client.post(url, data=payload, content_type="application/json")
    assert response["Content-Type"].startswith("application/json")
    return response


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="egress-integration-test-encryption")
def test_register_disabled_endpoint_and_rule_then_enable(operator, monkeypatch):
    provider = ProviderConfigModel.objects.create(
        name="egress-public-market", source_type="akshare"
    )
    response = post_json(operator, "/api/data-center/egress/endpoints/", endpoint_payload())
    assert response.status_code == 201, response.content
    endpoint = response.json()["data"]
    assert endpoint["enabled"] is False
    assert "private-proxy" not in response.content.decode()
    endpoint_id = endpoint["id"]
    rule_response = post_json(
        operator,
        "/api/data-center/egress/rules/",
        {
            "provider_id": provider.pk,
            "dataset_key": "equity.price.bar",
            "domain_pattern": "push2his.eastmoney.com",
            "deployment_region": "overseas",
            "strategy": "fixed",
            "fixed_egress_id": endpoint_id,
            "priority": 10,
            "enabled": False,
        },
    )
    assert rule_response.status_code == 201, rule_response.content
    rule_id = rule_response.json()["data"]["id"]
    listing = operator.get("/api/data-center/egress/rules/")
    assert listing.status_code == 200
    assert listing["Content-Type"].startswith("application/json")
    listed = listing.json()["results"][0]
    assert listed["provider_name"] == provider.name
    assert listed["egress_name"] == "Mainland test"
    assert "private-proxy" not in listing.content.decode()
    context = {
        "provider_id": provider.pk,
        "dataset_key": "equity.price.bar",
        "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "deployment_region": "overseas",
    }
    transport = Mock()
    transport.probe_endpoint.return_value = egress_service.EgressTransportResult(
        outcome="success", status_code=200
    )
    monkeypatch.setattr(egress_service, "_transport", transport)
    diagnostic = post_json(
        operator, f"/api/data-center/egress/endpoints/{endpoint_id}/test/", context
    )
    assert diagnostic.status_code == 200, diagnostic.content
    assert diagnostic.json()["success"] is True, diagnostic.content
    assert transport.probe_endpoint.call_args.kwargs["egress_id"] == endpoint_id
    transport.request.assert_not_called()
    premature = operator.patch(
        f"/api/data-center/egress/rules/{rule_id}/",
        data={"enabled": True},
        content_type="application/json",
    )
    assert premature.status_code == 400
    enabled = operator.patch(
        f"/api/data-center/egress/endpoints/{endpoint_id}/",
        data={"enabled": True, "password": ""},
        content_type="application/json",
    )
    assert enabled.status_code == 200, enabled.content
    assert get_egress_endpoint(endpoint_id).password == "private-proxy-password"
    enabled_rule = operator.patch(
        f"/api/data-center/egress/rules/{rule_id}/",
        data={"enabled": True},
        content_type="application/json",
    )
    assert enabled_rule.status_code == 200, enabled_rule.content
    context = {
        "provider_id": provider.pk,
        "dataset_key": "equity.price.bar",
        "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "deployment_region": "overseas",
    }
    preview = post_json(operator, "/api/data-center/egress/rules/preview/", context)
    assert preview.status_code == 200, preview.content
    assert preview.json()["data"]["egress_id"] == endpoint_id
    direct = operator.patch(
        f"/api/data-center/egress/rules/{rule_id}/",
        data={"strategy": "direct"},
        content_type="application/json",
    )
    assert direct.status_code == 200, direct.content
    assert direct.json()["data"]["fixed_egress_id"] is None


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="egress-integration-test-encryption")
def test_disabled_endpoint_with_no_target_is_reported_blocked(operator):
    response = post_json(operator, "/api/data-center/egress/endpoints/", endpoint_payload())
    assert response.status_code == 201, response.content
    endpoint_id = response.json()["data"]["id"]
    diagnostic = post_json(operator, f"/api/data-center/egress/endpoints/{endpoint_id}/test/", {})
    assert diagnostic.status_code == 200, diagnostic.content
    assert diagnostic.json()["success"] is False
    assert diagnostic.json()["data"]["outcome"] == "blocked"


@pytest.mark.django_db
def test_enabled_overlapping_rules_are_rejected(operator):
    provider = ProviderConfigModel.objects.create(name="overlap-market", source_type="akshare")
    payload = {
        "provider_id": provider.pk,
        "dataset_key": "equity.price.bar",
        "domain_pattern": "*.eastmoney.com",
        "deployment_region": "overseas",
        "strategy": "direct",
        "priority": 10,
        "enabled": True,
    }
    first = post_json(operator, "/api/data-center/egress/rules/", payload)
    assert first.status_code == 201, first.content
    payload["domain_pattern"] = "push2his.eastmoney.com"
    second = post_json(operator, "/api/data-center/egress/rules/", payload)
    assert second.status_code == 400
    assert second.json()["error_code"] == "EGRESS_RULE_PRIORITY_CONFLICT"


@pytest.mark.django_db
def test_repository_rechecks_conflicts_without_application_preflight():
    provider = ProviderConfigModel.objects.create(name="atomic-egress", source_type="akshare")
    repository = EgressRoutingRuleRepository()

    def rule(pattern):
        return EgressRouteRule(
            rule_id=None,
            provider_id=provider.pk,
            dataset_key="equity.price.bar",
            domain_pattern=pattern,
            deployment_region="overseas",
            strategy=EgressStrategy.DIRECT,
            fixed_egress_id=None,
            priority=10,
            enabled=True,
        )

    repository.create(rule("*.eastmoney.com"))
    with pytest.raises(EgressRoutingError) as error:
        repository.create(rule("push2his.eastmoney.com"))
    assert error.value.code == "EGRESS_RULE_PRIORITY_CONFLICT"
    assert len(repository.list()) == 1
