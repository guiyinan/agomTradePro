"""The policy API accepts only exact binding selectors and requires Session auth."""

import pytest
from django.urls import resolve
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.account.interface import single_owner_policy_api_views as subject
from apps.account.interface.single_owner_policy_api_views import (
    SingleOwnerPolicyPublishRequestSerializer,
    SingleOwnerPolicyPublishView,
)
from core.exceptions import AgomTradeProException


def _payload():
    return {"binding_id": "binding", "binding_version": "v1", "binding_content_hash": "a" * 64}


def test_exact_binding_payload_is_preserved():
    serializer = SingleOwnerPolicyPublishRequestSerializer(data=_payload())
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == _payload()


@pytest.mark.parametrize(
    "field,value",
    [
        ("binding_id", 1),
        ("binding_id", " binding"),
        ("binding_version", "v 1"),
        ("binding_content_hash", "A" * 64),
        ("binding_content_hash", "short"),
    ],
)
def test_invalid_selector_is_not_coerced(field, value):
    serializer = SingleOwnerPolicyPublishRequestSerializer(data={**_payload(), field: value})
    assert not serializer.is_valid()
    assert serializer.errors


@pytest.mark.parametrize(
    "field",
    [
        "user_id",
        "owner_id",
        "tenant_id",
        "account_id",
        "policy_id",
        "ttl_seconds",
        "status",
        "source",
    ],
)
def test_client_authority_fields_are_rejected(field):
    serializer = SingleOwnerPolicyPublishRequestSerializer(data={**_payload(), field: "injected"})
    assert not serializer.is_valid()
    assert "non_field_errors" in serializer.errors


@pytest.mark.parametrize("payload", [None, [], "invalid", {}, {"binding_id": "only"}])
def test_malformed_payload_has_renderable_validation_errors(payload):
    serializer = SingleOwnerPolicyPublishRequestSerializer(data=payload)
    with pytest.raises(subject.serializers.ValidationError) as caught:
        serializer.is_valid(raise_exception=True)
    assert isinstance(caught.value.detail, dict)


def test_anonymous_post_is_json_forbidden_without_publication():
    request = APIRequestFactory().post(
        "/api/account/authority/policy/publish/", _payload(), format="json"
    )
    response = SingleOwnerPolicyPublishView.as_view()(request)
    response.render()
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")
    assert "error" in response.data and "code" in response.data


def test_production_route_resolves_to_policy_view():
    assert (
        resolve("/api/account/authority/policy/publish/").func.cls is SingleOwnerPolicyPublishView
    )


@pytest.mark.parametrize(
    "error_type,status",
    [
        (subject.AccountOwnerAssignmentConflict, 409),
        (subject.CanonicalAccountCreationBindingV2Conflict, 409),
        (subject.AccountOwnerAssignmentUnavailable, 503),
        (subject.AccountOwnerAssignmentCorruption, 503),
        (subject.CanonicalAccountCreationBindingV2Unavailable, 503),
        (subject.CanonicalAccountCreationBindingV2Corruption, 503),
    ],
)
def test_business_errors_are_translated_without_leaking_details(monkeypatch, error_type, status):
    def fail(**_):
        raise error_type("private storage detail")

    monkeypatch.setattr(subject, "publish_bound_single_owner_policy", fail)
    raw = APIRequestFactory().post(
        "/policy/", _payload(), format="json", HTTP_IDEMPOTENCY_KEY="test-key"
    )
    # Direct handler unit test isolates mapping; real authentication is covered in PG tests.
    with pytest.raises(AgomTradeProException) as caught:
        SingleOwnerPolicyPublishView().post(Request(raw, parsers=[JSONParser()]))
    assert caught.value.status_code == status
    assert "private storage detail" not in str(caught.value)
