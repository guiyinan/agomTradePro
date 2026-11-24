"""Negative contracts at the actual Portfolio paths and ORM writer boundary."""

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.portfolio.infrastructure.benchmark_approval_models import BenchmarkApprovalEventModel


@pytest.mark.parametrize("suffix", ("", "approve/", "revoke/", "review"))
def test_anonymous_benchmark_issuance_and_review_are_denied(suffix):
    request_id = uuid4()
    path = "/api/portfolio/benchmark-approvals/"
    if suffix:
        path += f"{request_id}/" + ("" if suffix == "review" else suffix)
    client = Client()
    response = (
        client.get(path)
        if suffix == "review"
        else client.post(path, {}, content_type="application/json")
    )
    assert response.status_code == 403
    assert response.headers["Content-Type"].startswith("application/json")


def test_untrusted_permission_identity_or_content_selectors_are_rejected_before_read():
    path = "/api/portfolio/benchmark-approvals/"
    request = APIRequestFactory().post(
        path,
        {
            "request_id": str(uuid4()),
            "valuation_id": str(uuid4()),
            "valuation_version": 1,
            "allowed": True,
            "account_id": "external-account",
        },
        format="json",
    )

    class TestUser:
        is_authenticated = True
        pk = 1

    force_authenticate(request, user=TestUser())
    result = resolve(path).func(request)
    assert result.status_code == 400


@pytest.mark.parametrize("bad", [{"previous_epoch": 5}, {"definition_id": ["nested"]}])
def test_epoch_selectors_reject_malformed_types_before_account_access(bad):
    path = "/api/portfolio/benchmark-valuations/epochs/"
    payload = {
        "account_namespace": "portfolio",
        "account_id": "1",
        "policy_id": "policy",
        "definition_id": "definition",
    } | bad
    request = APIRequestFactory().post(path, payload, format="json")

    class Operator:
        is_authenticated = True
        pk = 1

    force_authenticate(request, user=Operator())
    response = resolve(path).func(request)
    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/json")


def test_database_model_has_no_manual_approval_creation_path():
    row = BenchmarkApprovalEventModel()
    with pytest.raises(ValidationError):
        row.save(force_insert=True)
    with pytest.raises(ValidationError):
        row.save_base(raw=True, force_insert=True)
    with pytest.raises(ValidationError):
        BenchmarkApprovalEventModel._base_manager.all().bulk_create([row])
    with pytest.raises(ValidationError):
        row.delete()
