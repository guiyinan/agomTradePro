from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.decision_rhythm.infrastructure.global_alert_repository import (
    DjangoDecisionRhythmGlobalAlertRepository,
)
from apps.decision_rhythm.infrastructure.models import (
    DecisionRequestModel,
    DecisionResponseModel,
    UnifiedRecommendationModel,
)
from apps.decision_rhythm.interface.workspace_api_support import (
    workspace_account_access_response,
)
from apps.equity.interface.page_views import _validate_optional_account_scope
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


def _request(*, authenticated: bool) -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(is_authenticated=authenticated))


def test_workspace_account_access_rejects_anonymous_reads() -> None:
    response = workspace_account_access_response(
        _request(authenticated=False),
        "default",
    )

    assert response is not None
    assert response.status_code == 401
    assert response.data["success"] is False


def test_workspace_account_access_checks_numeric_owner_scope(monkeypatch) -> None:
    calls: list[tuple[object, int, str]] = []

    def deny_account(user: object, account_id: int, action: str) -> SimpleNamespace:
        calls.append((user, account_id, action))
        return SimpleNamespace(error="无权查看该账户", status_code=403)

    monkeypatch.setattr(
        "apps.decision_rhythm.interface.workspace_api_support.get_account_access",
        deny_account,
    )
    request = _request(authenticated=True)
    response = workspace_account_access_response(request, "17", action="查看")

    assert response is not None
    assert response.status_code == 403
    assert response.data["error"] == "无权查看该账户"
    assert calls == [(request.user, 17, "查看")]


def test_workspace_account_access_rejects_logical_namespaces_without_owner_proof(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.decision_rhythm.interface.workspace_api_support.get_account_access",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("not a numeric account")),
    )

    response = workspace_account_access_response(
        _request(authenticated=True),
        "account_001",
    )

    assert response is not None
    assert response.status_code == 400
    assert response.data["error"] == "account_id must identify an owned account"


def test_equity_detail_account_query_reuses_owner_scope_check(monkeypatch) -> None:
    request = SimpleNamespace(
        GET={"account_id": "17"},
        user=SimpleNamespace(is_authenticated=True),
    )
    monkeypatch.setattr(
        "apps.equity.interface.page_views.get_account_access",
        lambda user, account_id, action: SimpleNamespace(error="无权查看该账户", status_code=403),
    )

    response = _validate_optional_account_scope(request)

    assert response is not None
    assert response.status_code == 403


@pytest.mark.parametrize("kind", ["legacy_preview", "approval"])
def test_execution_checks_persisted_owner_before_risk_or_write(monkeypatch, kind) -> None:
    from rest_framework.response import Response

    from apps.decision_rhythm.interface import workspace_execution_api_views as views

    checked = []

    def deny(request, account_id, *, action="查看", required=True):
        checked.append(account_id)
        return Response({"error": "无权访问该账户"}, status=403)

    monkeypatch.setattr(views, "workspace_account_access_response", deny)
    monkeypatch.setattr(views, "get_unified_recommendation", lambda _: None)
    monkeypatch.setattr(
        views, "get_legacy_recommendation", lambda _: SimpleNamespace(account_id="17")
    )
    monkeypatch.setattr(views, "get_approval_request", lambda _: SimpleNamespace(account_id="17"))
    monkeypatch.setattr(
        views,
        "build_recommendation_risk_checks",
        lambda *args: pytest.fail("Risk computation must not run before ownership"),
    )
    request = _request(authenticated=True)
    request.data = {"recommendation_id": "legacy-1", "approval_request_id": "approval-1"}
    view = (
        views.ExecutionPreviewView() if kind == "legacy_preview" else views.ExecutionApproveView()
    )
    response = view.post(request)
    assert response.status_code == 403
    assert checked == ["17"]


@pytest.mark.django_db
def test_workspace_recommendation_read_uses_persisted_account_owner() -> None:
    user_model = get_user_model()
    owner = user_model.objects.create_user(username="r3-owner", password="password")
    other_user = user_model.objects.create_user(username="r3-other", password="password")
    account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="R3 owner account",
        account_type="simulated",
        initial_capital="100000",
        current_cash="100000",
        total_value="100000",
    )
    UnifiedRecommendationModel.objects.create(
        recommendation_id="r3-owned-recommendation",
        account_id=str(account.id),
        security_code="600000.SH",
        side="BUY",
        composite_score=0.8,
    )

    owner_client = Client()
    owner_client.force_login(owner)
    owner_response = owner_client.get(
        "/api/decision/workspace/recommendations/",
        {"account_id": str(account.id)},
    )
    assert owner_response.status_code == 200
    assert owner_response.json()["data"]["total_count"] == 1

    other_client = Client()
    other_client.force_login(other_user)
    other_response = other_client.get(
        "/api/decision/workspace/recommendations/",
        {"account_id": str(account.id)},
    )
    assert other_response.status_code == 403


@pytest.mark.django_db
def test_workspace_recommendation_action_uses_record_account_when_scope_omitted() -> None:
    user_model = get_user_model()
    owner = user_model.objects.create_user(username="r3-action-owner", password="password")
    other_user = user_model.objects.create_user(username="r3-action-other", password="password")
    account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="R3 action account",
        account_type="simulated",
        initial_capital="100000",
        current_cash="100000",
        total_value="100000",
    )
    recommendation = UnifiedRecommendationModel.objects.create(
        recommendation_id="r3-action-recommendation",
        account_id=str(account.id),
        security_code="600001.SH",
        side="BUY",
        composite_score=0.8,
    )

    owner_client = Client()
    owner_client.force_login(owner)
    owner_response = owner_client.post(
        "/api/decision/workspace/recommendations/action/",
        data={"recommendation_id": recommendation.recommendation_id, "action": "watch"},
        content_type="application/json",
    )
    assert owner_response.status_code == 200

    other_client = Client()
    other_client.force_login(other_user)
    other_response = other_client.post(
        "/api/decision/workspace/recommendations/action/",
        data={"recommendation_id": recommendation.recommendation_id, "action": "ignore"},
        content_type="application/json",
    )
    assert other_response.status_code == 403


@pytest.mark.django_db
def test_pending_execution_requests_are_limited_to_owned_account_ids() -> None:
    """Investor pending queues must exclude other-account and unbound requests."""

    user_model = get_user_model()
    owner = user_model.objects.create_user(username="r3-pending-owner")
    other = user_model.objects.create_user(username="r3-pending-other")
    owner_account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="R3 pending owner",
        account_type="simulated",
        initial_capital="100000",
        current_cash="100000",
        total_value="100000",
    )
    other_account = SimulatedAccountModel.objects.create(
        user=other,
        account_name="R3 pending other",
        account_type="simulated",
        initial_capital="100000",
        current_cash="100000",
        total_value="100000",
    )
    owner_rec = UnifiedRecommendationModel.objects.create(
        recommendation_id="r3-pending-owned-rec",
        account_id=str(owner_account.id),
        security_code="600000.SH",
        side="BUY",
    )
    other_rec = UnifiedRecommendationModel.objects.create(
        recommendation_id="r3-pending-other-rec",
        account_id=str(other_account.id),
        security_code="600001.SH",
        side="BUY",
    )
    owned_request = DecisionRequestModel.objects.create(
        request_id="r3-pending-owned-request",
        asset_code="600000.SH",
        asset_class="equity",
        direction="BUY",
        execution_status="PENDING",
        unified_recommendation=owner_rec,
    )
    other_request = DecisionRequestModel.objects.create(
        request_id="r3-pending-other-request",
        asset_code="600001.SH",
        asset_class="equity",
        direction="BUY",
        execution_status="PENDING",
        unified_recommendation=other_rec,
    )
    unbound_request = DecisionRequestModel.objects.create(
        request_id="r3-pending-unbound-request",
        asset_code="600002.SH",
        asset_class="equity",
        direction="BUY",
        execution_status="PENDING",
    )
    for request in (owned_request, other_request, unbound_request):
        DecisionResponseModel.objects.create(request=request, approved=True)

    repository = DjangoDecisionRhythmGlobalAlertRepository()

    scoped = repository.list_pending_execution_requests(
        limit=10,
        account_ids=[str(owner_account.id)],
    )
    assert [item.request_id for item in scoped] == [owned_request.request_id]
    assert repository.list_pending_execution_requests(limit=10, account_ids=[]) == []
    assert {item.request_id for item in repository.list_pending_execution_requests(limit=10)} == {
        owned_request.request_id,
        other_request.request_id,
        unbound_request.request_id,
    }
