"""HTTP boundaries and real five-source resolution; PostgreSQL lock semantics have a separate suite."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIClient

from apps.risk_center.application.broker_order_execution_policy import (
    BrokerOrderExecutionPolicyUnavailable,
)
from apps.risk_center.infrastructure import broker_policy_sources as sources
from apps.risk_center.infrastructure.models import (
    AccountRiskPolicyModel,
    GlobalRiskFloorModel,
    RiskExceptionModel,
    RiskTemplateModel,
)


def _url(kind):
    return f"/api/risk-center/broker-orders/17/{uuid4()}/risk-{kind}/"


@pytest.mark.parametrize("kind", ["subject", "approval", "policy"])
def test_risk_order_all_routes_require_real_authenticated_session(kind):
    path = _url(kind)
    assert resolve(path).kwargs["operation"] == kind
    response = APIClient().post(path, {}, format="json")
    assert response.status_code == 403 and response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_risk_mutations_reject_extra_inputs_naive_time_and_wrong_media_type():
    staff = get_user_model().objects.create_user(username="risk-staff", is_staff=True)
    client = APIClient()
    client.force_login(staff)
    path = _url("policy")
    for invalid in (
        {"policy_id": "p", "policy_version": "2", "valid_until": "2028-01-01T00:00:00"},
        {
            "policy_id": "p",
            "policy_version": "2",
            "valid_until": "2028-01-01T00:00:00+00:00",
            "controls": {},
        },
    ):
        response = client.post(path, invalid, format="json")
        assert (
            response.status_code == 400 and response.json()["code"] == "invalid_broker_risk_command"
        )
    assert client.post(path, data="a", content_type="text/plain").status_code == 415
    assert client.get(path).status_code == 405
    assert (
        client.post(
            _url("approval"),
            {"subject_id": "s", "authorization_id": "a", "actor_id": "user:7"},
            format="json",
        ).status_code
        == 400
    )
    assert (
        client.post(
            _url("subject"),
            {
                "subject_id": "s",
                "execution_scope_id": "e",
                "execution_scope_version": "1",
                "policy_id": "p",
                "policy_version": "1",
                "permission_cap": "execution_eligible",
            },
            format="json",
        ).status_code
        == 400
    )


@pytest.mark.django_db
def test_configuration_fence_refuses_sqlite():
    if connection.vendor != "sqlite":
        pytest.skip("SQLite negative isolation contract")
    with pytest.raises(BrokerOrderExecutionPolicyUnavailable, match="transaction_required"):
        sources.lock_risk_configuration(using="default")


@pytest.mark.django_db
def test_five_live_policy_sources_bind_empty_sets_real_exceptions_and_configuration_drift(
    monkeypatch,
):
    # SQLite can verify source semantics. Only PostgreSQL gets the writer-excluding table fence.
    monkeypatch.setattr(sources, "lock_risk_configuration", lambda *, using: None)
    fields = {
        "max_total_position_pct": 0.9,
        "max_single_position_pct": 0.4,
        "max_daily_loss_pct": 0.1,
        "max_drawdown_pct": 0.1,
        "max_stop_loss_pct": 0.1,
        "take_profit_pct": 0.3,
        "min_cash_pct": 0.1,
        "force_stop_loss": True,
        "hard_exclusions": [],
    }
    floor = GlobalRiskFloorModel.objects.create(**{**fields, "max_single_position_pct": 0.2})
    template = RiskTemplateModel.objects.create(key="source", name="source", **fields)
    account = AccountRiskPolicyModel.objects.create(
        account_id=17, template=template, risk_profile="moderate"
    )
    issuer = sources.LiveBrokerPolicySources(
        17, "policy", "1", timezone.now() + timedelta(minutes=10), "default"
    )

    def read():
        return issuer.get_exact_active(
            source_snapshot_id=issuer.source_id, source_snapshot_version="1", as_of=timezone.now()
        )

    original = read()
    assert original.controls.max_single_position_pct == Decimal(".2")
    assert len(original.sources) == 5 and original == read()
    from apps.risk_center.application.broker_order_execution_policy import (
        BrokerOrderExecutionPolicyActor,
    )
    from apps.risk_center.broker_risk_issuance_composition import (
        activate_current_account_policy,
        require_current_account_policy,
    )

    activation = activate_current_account_policy(
        account_id=17,
        policy_id="policy",
        policy_version="1",
        valid_until=issuer.valid_until,
        actor=BrokerOrderExecutionPolicyActor("user:17", 17),
        using="default",
    )
    assert (
        require_current_account_policy(account_id=17, as_of=timezone.now(), using="default")
        == activation
    )
    actor = get_user_model().objects.create_user(username="author")

    def exception(account_id, field, value):
        return RiskExceptionModel.objects.create(
            account_id=account_id,
            field_name=field,
            allowed_value=value,
            created_by=actor,
            reason="bounded override",
            expires_at=issuer.valid_until + timedelta(minutes=1),
        )

    exception(90, "max_single_position_pct", 0.3)
    assert read() == original
    global_exception = exception(None, "max_single_position_pct", 0.3)
    with pytest.raises(BrokerOrderExecutionPolicyUnavailable, match="source_changed"):
        require_current_account_policy(account_id=17, as_of=timezone.now(), using="default")
    with_global = read()
    assert (
        with_global.content_hash != original.content_hash
        and with_global.controls.max_single_position_pct == Decimal(".3")
    )
    local = exception(17, "max_daily_loss_pct", 0.15)
    with_local = read()
    assert with_local.content_hash != with_global.content_hash
    RiskExceptionModel.objects.filter(pk=local.pk).update(
        reason="edited without changing resolved values"
    )
    edited = read()
    assert edited.content_hash != with_local.content_hash and edited.controls == with_local.controls
    RiskExceptionModel.objects.filter(pk=global_exception.pk).update(
        expires_at=issuer.valid_until - timedelta(seconds=1)
    )
    assert read() is None
    global_exception.delete()
    GlobalRiskFloorModel.objects.create(**fields)
    assert read() is None
    floor.delete()
    account.risk_profile = None
    account.save()
    assert read() is None
