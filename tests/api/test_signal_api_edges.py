from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.regime.application.current_regime import CurrentRegimeResult
from apps.signal.domain.rules import Eligibility
from apps.signal.infrastructure.models import InvestmentSignalModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="signal_user",
        password="testpass123",
        email="signal@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.fixture
def sample_signal(db):
    return InvestmentSignalModel.objects.create(
        asset_code="510300",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="PMI 回升，看好市场",
        invalidation_description="PMI 跌破 50",
        target_regime="Recovery",
        status="pending",
    )


@pytest.mark.django_db
def test_signal_retrieve_returns_success_contract(authenticated_client, sample_signal):
    response = authenticated_client.get(f"/api/signal/{sample_signal.id}/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["id"] == sample_signal.id
    assert payload["asset_code"] == "510300"
    assert payload["logic_desc"] == "PMI 回升，看好市场"
    assert payload["invalidation_description"] == "PMI 跌破 50"


@pytest.mark.django_db
def test_signal_approve_updates_status(authenticated_client, sample_signal):
    response = authenticated_client.post(f"/api/signal/{sample_signal.id}/approve/", {}, format="json")

    assert response.status_code == 200
    sample_signal.refresh_from_db()
    assert sample_signal.status == "approved"
    assert sample_signal.rejection_reason == ""


@pytest.mark.django_db
def test_signal_invalidate_sets_timestamp_and_reason(authenticated_client, sample_signal):
    response = authenticated_client.post(
        f"/api/signal/{sample_signal.id}/invalidate/",
        {"reason": "regime changed"},
        format="json",
    )

    assert response.status_code == 200
    sample_signal.refresh_from_db()
    assert sample_signal.status == "invalidated"
    assert sample_signal.rejection_reason == "regime changed"
    assert sample_signal.invalidated_at is not None


@pytest.mark.django_db
def test_signal_check_eligibility_returns_400_when_regime_missing(authenticated_client):
    with patch("apps.regime.application.current_regime.resolve_current_regime", return_value=None):
        response = authenticated_client.post(
            "/api/signal/check_eligibility/",
            {
                "asset_code": "510300",
                "logic_desc": "test logic",
                "invalidation_logic": "PMI < 50",
                "invalidation_threshold": 49.5,
            },
            format="json",
        )

    assert response.status_code == 400
    assert response.json()["error"] == "No regime data available"


@pytest.mark.django_db
def test_signal_check_eligibility_returns_success_contract(authenticated_client):
    current_regime = CurrentRegimeResult(
        dominant_regime="Recovery",
        confidence=0.88,
        observed_at=date(2026, 7, 10),
        data_source="test",
        warnings=[],
    )
    with patch(
        "apps.signal.application.query_services.resolve_current_regime",
        return_value=current_regime,
    ), patch(
        "apps.signal.application.query_services.check_eligibility",
        return_value=Eligibility.PREFERRED,
    ):
        response = authenticated_client.post(
            "/api/signal/check_eligibility/",
            {
                "asset_code": "510300",
                "logic_desc": "PMI recovery supports equities",
            },
            format="json",
        )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "is_eligible": True,
        "eligibility": "preferred",
        "regime_match": True,
        "policy_match": True,
        "current_regime": "Recovery",
        "rejection_reason": None,
    }


@pytest.mark.django_db
def test_signal_stats_returns_aggregated_counts(authenticated_client):
    InvestmentSignalModel.objects.create(
        asset_code="000001",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="A",
        invalidation_description="PMI < 50",
        target_regime="Recovery",
        status="approved",
    )
    InvestmentSignalModel.objects.create(
        asset_code="000002",
        asset_class="a_share_growth",
        direction="SHORT",
        logic_desc="B",
        invalidation_description="PMI > 55",
        target_regime="Deflation",
        status="rejected",
    )

    response = authenticated_client.get("/api/signal/stats/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stats"]["total"] >= 2
    assert payload["stats"]["approved"] >= 1
    assert payload["stats"]["rejected"] >= 1


@pytest.mark.django_db
def test_signal_active_alias_returns_only_approved_signals(authenticated_client):
    approved_signal = InvestmentSignalModel.objects.create(
        asset_code="000001",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="Approved signal",
        invalidation_description="PMI < 50",
        target_regime="Recovery",
        status="approved",
    )
    InvestmentSignalModel.objects.create(
        asset_code="000002",
        asset_class="a_share_growth",
        direction="SHORT",
        logic_desc="Pending signal",
        invalidation_description="PMI > 55",
        target_regime="Deflation",
        status="pending",
    )

    response = authenticated_client.get("/api/signal/active/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == approved_signal.id
    assert payload[0]["status"] == "approved"


@pytest.mark.django_db
def test_signal_list_excludes_uat_records_by_default(authenticated_client):
    InvestmentSignalModel.objects.create(
        asset_code="UATSIG_CN_ALPHA",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="UAT signal",
        invalidation_description="PMI < 50",
        target_regime="Recovery",
        status="approved",
    )
    prod_signal = InvestmentSignalModel.objects.create(
        asset_code="510300.SH",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="Production signal",
        invalidation_description="PMI < 50",
        target_regime="Recovery",
        status="approved",
    )

    response = authenticated_client.get("/api/signal/")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [prod_signal.id]


@pytest.mark.django_db
def test_signal_list_can_include_uat_records_when_requested(authenticated_client):
    uat_signal = InvestmentSignalModel.objects.create(
        asset_code="UATSIG_CN_ALPHA",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="UAT signal",
        invalidation_description="PMI < 50",
        target_regime="Recovery",
        status="approved",
    )
    prod_signal = InvestmentSignalModel.objects.create(
        asset_code="510300.SH",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="Production signal",
        invalidation_description="PMI < 50",
        target_regime="Recovery",
        status="approved",
    )

    response = authenticated_client.get("/api/signal/?include_test=true")

    assert response.status_code == 200
    payload = response.json()
    returned_ids = {item["id"] for item in payload}
    assert returned_ids == {uat_signal.id, prod_signal.id}


@pytest.mark.django_db
def test_signal_retrieve_invalid_id_returns_json_404(authenticated_client):
    response = authenticated_client.get("/api/signal/active-like-string/")

    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {"detail": "Not found."}
