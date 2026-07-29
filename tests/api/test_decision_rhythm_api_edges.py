from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.decision_rhythm.domain.entities import (
    DecisionPriority,
    DecisionQuota,
    DecisionRequest,
    ExecutionStatus,
    ExecutionTarget,
    QuotaPeriod,
)
from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel


@pytest.fixture
def admin_user(db):
    return get_user_model().objects.create_user(
        username="decision_rhythm_admin",
        password="testpass123",
        email="decision-rhythm-admin@example.com",
        is_staff=True,
    )


@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


def _quota() -> DecisionQuota:
    return DecisionQuota(
        quota_id="quota-weekly",
        account_id="acct-1",
        period=QuotaPeriod.WEEKLY,
        max_decisions=5,
        max_execution_count=3,
        used_decisions=2,
        used_executions=1,
        period_start=datetime(2026, 7, 6, tzinfo=UTC),
        period_end=datetime(2026, 7, 13, tzinfo=UTC),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        updated_at=datetime(2026, 7, 10, tzinfo=UTC),
    )


def _decision_request() -> DecisionRequest:
    return DecisionRequest(
        request_id="request-001",
        asset_code="600519.SH",
        asset_class="a_share",
        direction="BUY",
        priority=DecisionPriority.HIGH,
        trigger_id="trigger-001",
        reason="Validated Alpha trigger.",
        expected_confidence=0.82,
        quantity=100,
        notional=150000.0,
        requested_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
        candidate_id="candidate-001",
        execution_target=ExecutionTarget.SIMULATED,
        execution_status=ExecutionStatus.PENDING,
    )


@pytest.mark.django_db
def test_decision_quota_list_success_contract(authenticated_client):
    use_case = SimpleNamespace(execute=lambda request: [_quota()])

    with patch(
        "apps.decision_rhythm.interface.quota_api_views.build_list_decision_quotas_use_case",
        return_value=use_case,
    ):
        response = authenticated_client.get("/api/decision-rhythm/quotas/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["results"][0]["quota_id"] == "quota-weekly"
    assert payload["results"][0]["account_id"] == "acct-1"
    assert payload["results"][0]["period"] == "weekly"
    assert payload["results"][0]["remaining_decisions"] == 3


@pytest.mark.django_db
def test_decision_request_list_success_contract(authenticated_client):
    use_case = SimpleNamespace(execute=lambda request: [_decision_request()])

    with patch(
        "apps.decision_rhythm.interface.request_api_views.build_list_decision_requests_use_case",
        return_value=use_case,
    ):
        response = authenticated_client.get("/api/decision-rhythm/requests/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["results"][0]["request_id"] == "request-001"
    assert payload["results"][0]["priority"] == "high"
    assert payload["results"][0]["execution_status"] == "PENDING"


@pytest.mark.django_db
def test_decision_request_detail_success_contract(authenticated_client):
    use_case = SimpleNamespace(execute=lambda request: _decision_request())

    with patch(
        "apps.decision_rhythm.interface.request_api_views.build_get_decision_request_use_case",
        return_value=use_case,
    ):
        response = authenticated_client.get("/api/decision-rhythm/requests/request-001/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["result"]["request_id"] == "request-001"
    assert payload["result"]["asset_code"] == "600519.SH"
    assert payload["result"]["execution_target"] == "SIMULATED"


@pytest.mark.django_db
def test_decision_rhythm_summary_success_contract(authenticated_client):
    use_case = SimpleNamespace(
        execute=lambda request: SimpleNamespace(
            success=True,
            summary={
                "quota_status": {"weekly": "available"},
                "pending_requests": 2,
            },
            error=None,
        )
    )

    with patch(
        "apps.decision_rhythm.interface.command_api_views.build_get_rhythm_summary_use_case",
        return_value=use_case,
    ):
        response = authenticated_client.get("/api/decision-rhythm/summary/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "result": {
            "quota_status": {"weekly": "available"},
            "pending_requests": 2,
        },
    }


@pytest.mark.django_db
def test_decision_rhythm_internal_error_does_not_leak_exception(
    authenticated_client,
):
    use_case = SimpleNamespace(
        execute=lambda request: (_ for _ in ()).throw(
            RuntimeError("database password leaked"),
        )
    )

    with patch(
        "apps.decision_rhythm.interface.command_api_views.build_get_rhythm_summary_use_case",
        return_value=use_case,
    ):
        response = authenticated_client.get("/api/decision-rhythm/summary/")

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "error": "Failed to get rhythm summary",
    }


@pytest.mark.django_db
def test_decision_rhythm_submit_rejects_invalid_quota_period(authenticated_client):
    response = authenticated_client.post(
        "/api/decision-rhythm/submit/",
        {
            "asset_code": "000001.SH",
            "asset_class": "equity",
            "direction": "BUY",
            "quota_period": "YEARLY",
        },
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "quota_period" in str(payload["error"]).lower()


@pytest.mark.django_db
def test_decision_rhythm_precheck_requires_candidate_id(authenticated_client):
    response = authenticated_client.post(
        "/api/decision-workflow/precheck/",
        {},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_decision_rhythm_reset_quota_rejects_invalid_period(authenticated_client):
    response = authenticated_client.post(
        "/api/decision-rhythm/reset-quota/",
        {"period": "YEARLY"},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_decision_rhythm_reset_quota_rejects_unauthenticated_client(api_client):
    response = api_client.post(
        "/api/decision-rhythm/reset-quota/",
        {"account_id": "acct-1", "period": QuotaPeriod.WEEKLY.value},
        format="json",
    )

    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_decision_rhythm_quota_reads_require_authentication(api_client):
    list_response = api_client.get("/api/decision-rhythm/quotas/")
    trend_response = api_client.get("/api/decision-rhythm/trend-data/?days=7")

    assert list_response.status_code in {401, 403}
    assert trend_response.status_code in {401, 403}


@pytest.mark.django_db
def test_decision_rhythm_quota_update_requires_admin(authenticated_client):
    response = authenticated_client.post(
        "/api/decision-rhythm/quota/update/",
        {
            "account_id": "acct-1",
            "period": QuotaPeriod.WEEKLY.value,
            "max_decisions": 10,
            "max_executions": 5,
        },
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_decision_rhythm_quota_update_rejects_invalid_numeric_for_admin(
    admin_client,
):
    response = admin_client.post(
        "/api/decision-rhythm/quota/update/",
        {
            "account_id": "acct-1",
            "period": QuotaPeriod.WEEKLY.value,
            "max_decisions": "invalid-number",
            "max_executions": 5,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_decision_rhythm_quota_update_serializes_period_for_admin(admin_client):
    """A successful quota update must expose the domain enum as JSON text."""

    response = admin_client.post(
        "/api/decision-rhythm/quota/update/",
        {
            "account_id": "acct-m5",
            "period": QuotaPeriod.DAILY.value,
            "max_decisions": 12,
            "max_executions": 6,
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["account_id"] == "acct-m5"
    assert payload["period"] == QuotaPeriod.DAILY.value
    assert payload["max_decisions"] == 12
    assert payload["max_executions"] == 6


@pytest.mark.django_db
def test_decision_rhythm_reset_quota_rejects_invalid_period_for_admin(admin_client):
    response = admin_client.post(
        "/api/decision-rhythm/reset-quota/",
        {"account_id": "acct-1", "period": "YEARLY"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_decision_rhythm_reset_quota_resets_only_selected_account_period(admin_client):
    target = DecisionQuotaModel.objects.create(
        quota_id="quota-acct-1-weekly",
        account_id="acct-1",
        period=QuotaPeriod.WEEKLY.value,
        max_decisions=10,
        max_execution_count=5,
        used_decisions=7,
        used_executions=3,
    )
    untouched_period = DecisionQuotaModel.objects.create(
        quota_id="quota-acct-1-daily",
        account_id="acct-1",
        period=QuotaPeriod.DAILY.value,
        max_decisions=5,
        max_execution_count=2,
        used_decisions=4,
        used_executions=1,
    )
    other_account = DecisionQuotaModel.objects.create(
        quota_id="quota-acct-2-weekly",
        account_id="acct-2",
        period=QuotaPeriod.WEEKLY.value,
        max_decisions=10,
        max_execution_count=5,
        used_decisions=6,
        used_executions=2,
    )

    response = admin_client.post(
        "/api/decision-rhythm/reset-quota/",
        {"account_id": "acct-1", "period": QuotaPeriod.WEEKLY.value},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["account_id"] == "acct-1"
    assert response.json()["reset_periods"] == [QuotaPeriod.WEEKLY.value]
    target.refresh_from_db()
    untouched_period.refresh_from_db()
    other_account.refresh_from_db()
    assert (target.used_decisions, target.used_executions) == (0, 0)
    assert (untouched_period.used_decisions, untouched_period.used_executions) == (4, 1)
    assert (other_account.used_decisions, other_account.used_executions) == (6, 2)


@pytest.mark.django_db
def test_decision_rhythm_reset_quota_resets_all_periods_for_selected_account(admin_client):
    target_quotas = [
        DecisionQuotaModel.objects.create(
            quota_id=f"quota-acct-1-{period.value}",
            account_id="acct-1",
            period=period.value,
            max_decisions=10,
            max_execution_count=5,
            used_decisions=7,
            used_executions=3,
        )
        for period in QuotaPeriod
    ]
    other_account = DecisionQuotaModel.objects.create(
        quota_id="quota-acct-2-monthly",
        account_id="acct-2",
        period=QuotaPeriod.MONTHLY.value,
        max_decisions=10,
        max_execution_count=5,
        used_decisions=6,
        used_executions=2,
    )

    response = admin_client.post(
        "/api/decision-rhythm/reset-quota/",
        {"account_id": "acct-1"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["account_id"] == "acct-1"
    assert response.json()["reset_periods"] == [period.value for period in QuotaPeriod]
    for quota in target_quotas:
        quota.refresh_from_db()
        assert (quota.used_decisions, quota.used_executions) == (0, 0)
    other_account.refresh_from_db()
    assert (other_account.used_decisions, other_account.used_executions) == (6, 2)


@pytest.mark.django_db
def test_decision_rhythm_reset_quota_rejects_missing_account_quotas(admin_client):
    response = admin_client.post(
        "/api/decision-rhythm/reset-quota/",
        {"account_id": "missing-account"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "success": False,
        "error": "未找到对应配额",
    }


@pytest.mark.django_db
def test_decision_rhythm_classic_pages_publish_role_appropriate_tui_links(
    client,
    test_user,
    admin_user,
):
    anonymous_quota = client.get("/decision-rhythm/quota/")
    assert anonymous_quota.status_code == 302

    client.force_login(test_user)
    quota_response = client.get("/decision-rhythm/quota/?account_id=acct-1")
    config_response = client.get("/decision-rhythm/config/")
    assert quota_response.status_code == 200
    assert (
        "/tui/?screen=command-center.decision-flow&amp;action=decision-rhythm.quota-list"
        in quota_response.content.decode()
    )
    assert config_response.status_code == 302

    client.force_login(admin_user)
    admin_response = client.get("/decision-rhythm/config/?account_id=acct-1")
    assert admin_response.status_code == 200
    assert (
        "/tui/?screen=command-center.decision-flow&amp;action=decision-rhythm.quota-update"
        in admin_response.content.decode()
    )


@pytest.mark.django_db
def test_decision_workspace_recommendations_reject_invalid_page(
    authenticated_client,
    settings,
):
    settings.DECISION_WORKSPACE_V2_ENABLED = True

    response = authenticated_client.get(
        "/api/decision/workspace/recommendations/?account_id=default&page=bad"
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "page" in payload["error"]


@pytest.mark.django_db
def test_valuation_recalculate_rejects_non_object_body(authenticated_client):
    response = authenticated_client.post(
        "/api/valuation/recalculate/",
        ["not", "an", "object"],
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "success": False,
        "error": "request body must be a JSON object",
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        (
            {"security_code": "000001.SZ", "fair_value": "-1"},
            "valuation prices must be positive",
        ),
        (
            {
                "security_code": "000001.SZ",
                "fair_value": "10",
                "valuation_method": "unknown",
            },
            "unsupported valuation_method",
        ),
        (
            {
                "security_code": "000001.SZ",
                "fair_value": "10",
                "input_parameters": "not-an-object",
            },
            "input_parameters must be a JSON object",
        ),
    ],
)
def test_valuation_recalculate_rejects_invalid_financial_input(
    authenticated_client,
    payload,
    expected_error,
):
    response = authenticated_client.post(
        "/api/valuation/recalculate/",
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == expected_error


@pytest.mark.django_db
def test_invalidation_ai_draft_normalizes_non_object_meta(authenticated_client):
    ai_result = {
        "status": "success",
        "content": '{"logic":"AND","conditions":[],"meta":"invalid"}',
        "provider_used": "test-provider",
        "model": "test-model",
    }

    with patch(
        "apps.decision_rhythm.interface.valuation_api_views.generate_chat_completion",
        return_value=ai_result,
    ):
        response = authenticated_client.post(
            "/api/decision/workspace/invalidation/ai-draft/",
            {"security_code": "000001.SZ"},
            format="json",
        )

    assert response.status_code == 200
    meta = response.json()["data"]["draft"]["meta"]
    assert meta["security_code"] == "000001.SZ"
    assert meta["side"] == "BUY"
