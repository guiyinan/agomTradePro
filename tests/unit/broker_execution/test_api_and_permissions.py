"""Canonical API, account scoping, preview, idempotency, and UI contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from apps.broker_execution.application.agent_auth import build_agent_signature
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
)
from apps.broker_execution.infrastructure.models import (
    BrokerAccountAccessModel,
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerCommandModel,
    BrokerExecutionAuditModel,
    BrokerOrderEventModel,
    LiveOrderModel,
    TradingControlModel,
)
from apps.broker_execution.infrastructure.repositories import (
    DjangoBrokerExecutionRepository,
)
from apps.broker_execution.interface import api_views as broker_api_views
from apps.broker_execution.interface.serializers import AgentEventsSerializer
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


def _user(username: str, role: str, *, superuser: bool = False) -> User:
    user = User.objects.create_user(
        username=username,
        password="test123",
        is_staff=superuser,
        is_superuser=superuser,
    )
    profile = user.account_profile
    profile.rbac_role = role
    profile.approval_status = "approved"
    profile.save(update_fields=["rbac_role", "approval_status", "updated_at"])
    return user


def test_agent_event_batch_is_bounded_to_contract_limit() -> None:
    event = {
        "event_id": "event-1",
        "client_order_id": "00000000-0000-0000-0000-000000000001",
        "event_type": "TEST",
        "occurred_at": "2026-07-22T00:00:00Z",
    }
    serializer = AgentEventsSerializer(
        data={"contract_version": "1.0", "events": [event] * 201}
    )

    assert serializer.is_valid() is False
    assert "events" in serializer.errors
    unsupported = AgentEventsSerializer(
        data={"contract_version": "2.0", "events": [event]}
    )
    assert unsupported.is_valid() is False
    assert "contract_version" in unsupported.errors
    malformed_fill = AgentEventsSerializer(
        data={
            "contract_version": "1.0",
            "events": [
                event
                | {
                    "fill": {
                        "broker_trade_id": "trade-1",
                        "quantity": "-1",
                        "price": "3.90",
                        "occurred_at": "2026-07-22T00:00:00Z",
                    }
                }
            ],
        }
    )
    assert malformed_fill.is_valid() is False
    assert "events" in malformed_fill.errors


def _binding(owner: User, account_id: int = 7) -> tuple[BrokerAgentModel, BrokerAccountBindingModel]:
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id=f"agent-{account_id}",
        display_name="Home QMT",
    )
    binding = BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=account_id,
        agent=agent,
        broker_account_ref=f"broker-{account_id}",
        broker_account_mask="****1234",
        auto_execution_enabled=True,
        max_single_order_amount=Decimal("100000"),
        daily_order_amount_limit=Decimal("500000"),
        allowed_symbols=["510300.SH"],
    )
    return agent, binding


def _order(owner: User, agent: BrokerAgentModel, account_id: int = 7) -> LiveOrderModel:
    return LiveOrderModel.objects.create(
        user=owner,
        account_id=account_id,
        agent=agent,
        asset_code="510300.SH",
        side="BUY",
        quantity=Decimal("100"),
        limit_price=Decimal("3.90"),
        estimated_amount=Decimal("390"),
        risk_policy_version="risk-v1",
        risk_snapshot={"passed": True},
        expires_at=timezone.now() + timedelta(hours=1),
    )


@pytest.mark.django_db
def test_unauthenticated_api_and_page_are_rejected() -> None:
    client = Client()
    api = client.get("/api/broker-execution/")
    page = client.get("/broker-execution/")
    assert api.status_code in {401, 403}
    assert page.status_code == 302


@pytest.mark.django_db
def test_login_failure_audit_excludes_password_and_records_source_ip() -> None:
    _user("known-login-user", "owner")
    client = Client()

    response = client.post(
        "/account/login/",
        data={
            "username": "known-login-user",
            "password": "do-not-store-this-password",
        },
        REMOTE_ADDR="203.0.113.9",
        HTTP_USER_AGENT="security-audit-test",
        HTTP_X_REQUEST_ID="login-failure-1",
    )

    assert response.status_code == 200
    audit = BrokerExecutionAuditModel.objects.get(
        action="login_failed",
        resource_id="known-login-user",
    )
    serialized = json.dumps(audit.after)
    assert audit.after["source_ip"] == "203.0.113.9"
    assert audit.request_id == "login-failure-1"
    assert "do-not-store-this-password" not in serialized
    assert "password" not in serialized.lower()


@pytest.mark.django_db
def test_owner_can_preview_commit_and_replay_approval() -> None:
    owner = _user("broker-owner", "owner")
    agent, _ = _binding(owner)
    order = _order(owner, agent)
    client = Client()
    client.force_login(owner)
    endpoint = f"/api/broker-execution/orders/{order.client_order_id}/approve/"
    preview = client.post(
        endpoint,
        data=json.dumps({"preview_only": True, "reason": "reviewed"}),
        content_type="application/json",
    )
    assert preview.status_code == 200
    order.refresh_from_db()
    assert order.status == "WAITING_APPROVAL"
    commit_payload = {
        "preview_only": False,
        "reason": "reviewed",
        "expected_version": preview.json()["data"]["order"]["version"],
        "idempotency_key": "approve-owner-1",
    }
    commit = client.post(endpoint, data=json.dumps(commit_payload), content_type="application/json")
    replay = client.post(endpoint, data=json.dumps(commit_payload), content_type="application/json")
    assert commit.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"]["idempotent_replay"] is True
    order.refresh_from_db()
    assert order.status == "READY"
    assert len(order.approval_digest) == 64
    assert BrokerExecutionAuditModel.objects.filter(action="order_approve").count() == 1


@pytest.mark.django_db
def test_order_action_commit_rejects_a_stale_preview_version() -> None:
    owner = _user("stale-preview-owner", "owner")
    agent, _ = _binding(owner, account_id=73)
    order = _order(owner, agent, account_id=73)
    client = Client()
    client.force_login(owner)
    endpoint = f"/api/broker-execution/orders/{order.client_order_id}/approve/"
    preview = client.post(
        endpoint,
        data=json.dumps({"preview_only": True, "reason": "reviewed"}),
        content_type="application/json",
    )
    preview_version = preview.json()["data"]["order"]["version"]
    LiveOrderModel.objects.filter(pk=order.pk).update(version=preview_version + 1)

    commit = client.post(
        endpoint,
        data=json.dumps(
            {
                "preview_only": False,
                "reason": "reviewed",
                "expected_version": preview_version,
                "idempotency_key": "stale-preview-approve",
            }
        ),
        content_type="application/json",
    )

    assert commit.status_code == 409
    order.refresh_from_db()
    assert order.status == "WAITING_APPROVAL"
    assert order.approval_digest == ""


@pytest.mark.django_db
def test_advisor_draft_route_accepts_only_server_generated_plan_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _user("advisor-route-owner", "owner")
    calls = []

    class _UseCase:
        def execute(self, **kwargs):
            calls.append(kwargs)
            return {
                "preview_only": True,
                "plan_digest": "a" * 64,
                "orders_count": 1,
            }

    monkeypatch.setattr(
        broker_api_views,
        "PreviewOrCreateAdvisorLiveOrdersUseCase",
        _UseCase,
    )
    client = Client()
    client.force_login(owner)

    response = client.post(
        "/api/broker-execution/orders/from-advisor-sheet/",
        data=json.dumps({"account_id": 7, "preview_only": True}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert calls[0]["account_id"] == 7
    assert set(calls[0]) == {
        "actor",
        "account_id",
        "preview_only",
        "expected_plan_digest",
        "idempotency_key",
    }


@pytest.mark.django_db
def test_account_scope_and_action_grants_are_enforced() -> None:
    owner = _user("binding-owner", "owner")
    trader = _user("granted-trader", "trader")
    outsider = _user("outside-trader", "trader")
    agent, _ = _binding(owner)
    order = _order(owner, agent)
    BrokerAccountAccessModel.objects.create(
        user=trader, account_id=7, can_approve=True, can_trade=True
    )
    granted = Client()
    granted.force_login(trader)
    outsider_client = Client()
    outsider_client.force_login(outsider)
    assert granted.get(f"/api/broker-execution/orders/{order.client_order_id}/").status_code == 200
    assert outsider_client.get(
        f"/api/broker-execution/orders/{order.client_order_id}/"
    ).status_code == 404
    response = granted.post(
        f"/api/broker-execution/orders/{order.client_order_id}/approve/",
        data=json.dumps({"preview_only": True, "reason": "delegated review"}),
        content_type="application/json",
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_manages_account_grants_only_through_preview_commit_and_audit() -> None:
    administrator = _user("access-admin", "admin", superuser=True)
    owner = _user("access-owner", "owner")
    trader = _user("access-trader", "trader")
    _binding(owner, account_id=77)
    endpoint = "/api/broker-execution/account-access/"
    payload = {
        "user_id": trader.id,
        "account_id": 77,
        "can_approve": True,
        "can_trade": False,
        "is_active": True,
        "reason": "delegate order approval",
    }
    client = Client()
    client.force_login(administrator)

    preview = client.post(
        endpoint,
        data=json.dumps(payload | {"preview_only": True}),
        content_type="application/json",
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["target_user"]["username"] == trader.username
    assert BrokerAccountAccessModel.objects.count() == 0

    commit_payload = payload | {
        "preview_only": False,
        "idempotency_key": "account-access-77",
    }
    commit = client.post(
        endpoint,
        data=json.dumps(commit_payload),
        content_type="application/json",
    )
    replay = client.post(
        endpoint,
        data=json.dumps(commit_payload),
        content_type="application/json",
    )
    assert commit.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"]["idempotent_replay"] is True
    grant = BrokerAccountAccessModel.objects.get(user=trader, account_id=77)
    assert grant.can_approve is True
    assert grant.can_trade is False
    assert grant.granted_by == administrator
    assert BrokerExecutionAuditModel.objects.filter(
        actor=administrator,
        user=owner,
        action="account_access_updated",
        account_id=77,
    ).count() == 1

    catalog = client.get(endpoint)
    assert catalog.status_code == 200
    assert catalog.json()["data"]["access_grants"][0]["username"] == trader.username

    owner_client = Client()
    owner_client.force_login(owner)
    assert owner_client.get(endpoint).status_code == 403
    assert owner_client.post(
        endpoint,
        data=json.dumps(payload | {"preview_only": True}),
        content_type="application/json",
    ).status_code == 403


@pytest.mark.django_db
def test_django_admin_cannot_mutate_broker_execution_state() -> None:
    for model in (
        BrokerAgentModel,
        BrokerAccountBindingModel,
        BrokerAccountAccessModel,
        BrokerAgentCredentialModel,
        LiveOrderModel,
        TradingControlModel,
        BrokerExecutionAuditModel,
    ):
        model_admin = admin.site._registry[model]
        assert model_admin.has_add_permission(None) is False
        assert model_admin.has_change_permission(None) is False
        assert model_admin.has_delete_permission(None) is False


@pytest.mark.django_db
def test_read_only_role_cannot_approve_even_owned_order() -> None:
    viewer = _user("read-only-owner", "read_only")
    agent, _ = _binding(viewer)
    order = _order(viewer, agent)
    client = Client()
    client.force_login(viewer)
    response = client.post(
        f"/api/broker-execution/orders/{order.client_order_id}/approve/",
        data=json.dumps({"preview_only": True, "reason": "attempt"}),
        content_type="application/json",
    )
    assert response.status_code == 403
    assert BrokerExecutionAuditModel.objects.filter(
        actor=viewer, action="permission_denied", resource_id="approve"
    ).exists()


@pytest.mark.django_db
def test_kill_switch_is_previewed_committed_and_visible_on_overview() -> None:
    owner = _user("stop-owner", "owner")
    _binding(owner)
    client = Client()
    client.force_login(owner)
    endpoint = "/api/broker-execution/kill-switch/"
    preview = client.post(
        endpoint,
        data=json.dumps({"account_id": 0, "active": True, "reason": "incident", "preview_only": True}),
        content_type="application/json",
    )
    assert preview.status_code == 200
    assert TradingControlModel.objects.count() == 0
    commit = client.post(
        endpoint,
        data=json.dumps(
            {
                "account_id": 0,
                "active": True,
                "reason": "incident",
                "preview_only": False,
                "idempotency_key": "stop-1",
            }
        ),
        content_type="application/json",
    )
    assert commit.status_code == 200
    overview = client.get("/api/broker-execution/").json()["data"]
    assert overview["today_readiness"] == "STOPPED"


@pytest.mark.django_db
def test_resume_requires_admin_password_and_audits_source_ip() -> None:
    admin = _user("resume-admin", "admin", superuser=True)
    agent, _ = _binding(admin, account_id=79)
    agent.status = BrokerAgentModel.STATUS_ONLINE
    agent.qmt_connected = True
    agent.last_heartbeat_at = timezone.now()
    agent.save(update_fields=["status", "qmt_connected", "last_heartbeat_at", "updated_at"])
    TradingControlModel.objects.create(
        user=admin,
        account_id=79,
        kill_switch_active=True,
        reason="incident",
        changed_by=admin,
    )
    client = Client()
    client.force_login(admin)
    endpoint = "/api/broker-execution/kill-switch/"
    base_payload = {
        "account_id": 79,
        "active": False,
        "reason": "readiness restored",
    }

    preview = client.post(
        endpoint,
        data=json.dumps(base_payload | {"preview_only": True}),
        content_type="application/json",
    )
    missing = client.post(
        endpoint,
        data=json.dumps(
            base_payload
            | {"preview_only": False, "idempotency_key": "resume-missing"}
        ),
        content_type="application/json",
    )
    wrong = client.post(
        endpoint,
        data=json.dumps(
            base_payload
            | {
                "preview_only": False,
                "idempotency_key": "resume-wrong",
                "reauth": {"method": "password", "credential": "wrong"},
            }
        ),
        content_type="application/json",
        REMOTE_ADDR="198.51.100.7",
    )
    success = client.post(
        endpoint,
        data=json.dumps(
            base_payload
            | {
                "preview_only": False,
                "idempotency_key": "resume-success",
                "reauth": {"method": "password", "credential": "test123"},
            }
        ),
        content_type="application/json",
        REMOTE_ADDR="198.51.100.7",
        HTTP_USER_AGENT="broker-execution-test",
    )

    assert preview.status_code == 200
    assert preview.json()["data"]["reauthentication_required"] is True
    assert missing.status_code == 400
    assert wrong.status_code == 403
    assert success.status_code == 200
    assert TradingControlModel.objects.get(user=admin, account_id=79).kill_switch_active is False
    denial = BrokerExecutionAuditModel.objects.get(
        actor=admin,
        action="permission_denied",
        resource_id="resume:reauthentication",
    )
    assert denial.after["request_context"]["source_ip"] == "198.51.100.7"
    resumed = BrokerExecutionAuditModel.objects.get(actor=admin, action="kill_switch_off")
    assert resumed.after["request_context"]["source_ip"] == "198.51.100.7"
    assert "credential" not in json.dumps(resumed.after)


@pytest.mark.django_db
def test_admin_global_kill_switch_stops_every_active_bound_account() -> None:
    admin = _user("global-stop-admin", "admin", superuser=True)
    first_owner = _user("global-stop-owner-1", "owner")
    second_owner = _user("global-stop-owner-2", "owner")
    _binding(first_owner, account_id=81)
    _binding(second_owner, account_id=82)
    client = Client()
    client.force_login(admin)

    response = client.post(
        "/api/broker-execution/kill-switch/",
        data=json.dumps(
            {
                "account_id": 0,
                "active": True,
                "reason": "system-wide incident",
                "preview_only": False,
                "idempotency_key": "global-stop-1",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["affected_account_count"] == 2
    assert set(
        TradingControlModel.objects.filter(kill_switch_active=True).values_list(
            "user_id", "account_id"
        )
    ) == {(first_owner.id, 81), (second_owner.id, 82)}
    assert BrokerExecutionAuditModel.objects.filter(
        actor=admin, action="kill_switch_on"
    ).count() == 2


@pytest.mark.django_db
def test_trader_global_kill_switch_stops_explicitly_authorized_owner_account() -> None:
    owner = _user("delegated-stop-owner", "owner")
    trader = _user("delegated-stop-trader", "trader")
    _binding(owner, account_id=83)
    BrokerAccountAccessModel.objects.create(
        user=trader,
        account_id=83,
        can_trade=True,
    )
    client = Client()
    client.force_login(trader)

    preview = client.post(
        "/api/broker-execution/kill-switch/",
        data=json.dumps(
            {
                "account_id": 0,
                "active": True,
                "reason": "delegated incident response",
                "preview_only": True,
            }
        ),
        content_type="application/json",
    )
    commit = client.post(
        "/api/broker-execution/kill-switch/",
        data=json.dumps(
            {
                "account_id": 0,
                "active": True,
                "reason": "delegated incident response",
                "preview_only": False,
                "idempotency_key": "delegated-stop-1",
            }
        ),
        content_type="application/json",
    )

    assert preview.status_code == 200
    assert preview.json()["data"]["affected_accounts"] == [
        {"user_id": owner.id, "account_id": 83}
    ]
    assert commit.status_code == 200
    assert TradingControlModel.objects.get(
        user=owner,
        account_id=83,
    ).kill_switch_active


@pytest.mark.django_db
def test_kill_switch_blocks_approval_but_still_allows_rejection() -> None:
    owner = _user("stopped-approval-owner", "owner")
    agent, _ = _binding(owner, account_id=71)
    order = _order(owner, agent, account_id=71)
    TradingControlModel.objects.create(
        user=owner,
        account_id=71,
        kill_switch_active=True,
        reason="incident",
    )
    client = Client()
    client.force_login(owner)

    approve = client.post(
        f"/api/broker-execution/orders/{order.client_order_id}/approve/",
        data=json.dumps(
            {
                "preview_only": False,
                "reason": "must remain stopped",
                "expected_version": order.version,
                "idempotency_key": "stopped-approve-1",
            }
        ),
        content_type="application/json",
    )
    reject = client.post(
        f"/api/broker-execution/orders/{order.client_order_id}/reject/",
        data=json.dumps(
            {
                "preview_only": False,
                "reason": "safe rejection",
                "expected_version": order.version,
                "idempotency_key": "stopped-reject-1",
            }
        ),
        content_type="application/json",
    )

    assert approve.status_code == 409
    assert reject.status_code == 200


@pytest.mark.django_db
def test_submit_ack_rechecks_limits_and_allow_list_after_approval() -> None:
    owner = _user("ack-gate-owner", "owner")
    agent, binding = _binding(owner, account_id=72)
    binding.enforce_trading_session = False
    binding.save(update_fields=["enforce_trading_session", "updated_at"])
    order = _order(owner, agent, account_id=72)
    client = Client()
    client.force_login(owner)
    approval = client.post(
        f"/api/broker-execution/orders/{order.client_order_id}/approve/",
        data=json.dumps(
            {
                "preview_only": False,
                "reason": "approved before tighter settings",
                "expected_version": order.version,
                "idempotency_key": "ack-gate-approve",
            }
        ),
        content_type="application/json",
    )
    assert approval.status_code == 200
    BrokerAgentModel.objects.filter(pk=agent.pk).update(
        status=BrokerAgentModel.STATUS_ONLINE,
        qmt_connected=True,
    )
    BrokerAccountSnapshotModel.objects.create(
        user=owner,
        agent=agent,
        account_id=72,
        captured_at=timezone.now(),
        cash_available=Decimal("100000"),
        total_asset=Decimal("100000"),
    )
    repository = DjangoBrokerExecutionRepository()
    leased = repository.lease_agent_orders(
        agent_pk=agent.pk,
        allowed_account_ids=[72],
        limit=1,
        lease_seconds=30,
    )["orders"][0]
    binding.allowed_symbols = []
    binding.save(update_fields=["allowed_symbols", "updated_at"])

    with pytest.raises(BrokerExecutionConflictError, match="allow-list"):
        repository.acknowledge_submitting(
            agent_pk=agent.pk,
            allowed_account_ids=[72],
            client_order_id=str(order.client_order_id),
            lease_token=leased["lease_token"],
        )

    order.refresh_from_db()
    assert order.status == "LEASED"


@pytest.mark.django_db
def test_cancel_command_acceptance_waits_for_authoritative_broker_status() -> None:
    owner = _user("cancel-pending-owner", "owner")
    agent, _ = _binding(owner, account_id=74)
    order = _order(owner, agent, account_id=74)
    LiveOrderModel.objects.filter(pk=order.pk).update(
        status="SUBMITTED",
        broker_order_id="QMT-74",
    )
    order.refresh_from_db()
    client = Client()
    client.force_login(owner)
    response = client.post(
        f"/api/broker-execution/orders/{order.client_order_id}/cancel/",
        data=json.dumps(
            {
                "preview_only": False,
                "reason": "cancel requested",
                "expected_version": order.version,
                "idempotency_key": "cancel-pending-74",
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    order.refresh_from_db()
    assert order.status == "CANCEL_PENDING"

    repository = DjangoBrokerExecutionRepository()
    command = repository.lease_agent_commands(
        agent_pk=agent.pk, allowed_account_ids=[74], limit=1
    )[
        "commands"
    ][0]
    completed = repository.complete_agent_command(
        agent_pk=agent.pk,
        allowed_account_ids=[74],
        command_id=command["command_id"],
        success=True,
        result={"cancel_accepted": True},
    )
    replay = repository.complete_agent_command(
        agent_pk=agent.pk,
        allowed_account_ids=[74],
        command_id=command["command_id"],
        success=True,
        result={"cancel_accepted": True},
    )
    order.refresh_from_db()
    assert completed["status"] == "completed"
    assert replay["idempotent_replay"] is True
    assert order.status == "CANCEL_PENDING"

    repository.report_agent_events(
        agent_pk=agent.pk,
        allowed_account_ids=[74],
        events=[
            {
                "event_id": "qmt-canceled-74",
                "client_order_id": str(order.client_order_id),
                "event_type": "QMT_ORDER_STATUS",
                "status": "CANCELED",
                "occurred_at": timezone.now().isoformat(),
                "broker_order_id": "QMT-74",
            }
        ],
    )
    order.refresh_from_db()
    assert order.status == "CANCELED"
    assert BrokerExecutionAuditModel.objects.filter(
        action="agent_command_cancel_completed",
        resource_id=str(order.client_order_id),
    ).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/broker-execution/",
        "/broker-execution/orders/",
        "/broker-execution/reconciliation/",
        "/broker-execution/connection/",
        "/broker-execution/settings/",
        "/broker-execution/audit/",
    ],
)
def test_classic_web_routes_render_user_tasks(path: str) -> None:
    owner = _user(f"page-{hashlib.sha1(path.encode()).hexdigest()[:8]}", "owner")
    client = Client()
    client.force_login(owner)
    response = client.get(path)
    assert response.status_code == 200
    assert "实盘" in response.content.decode("utf-8")
    assert set(response.context["page_view_model"]) == {
        "status",
        "summary",
        "data",
        "warnings",
        "next_actions",
        "permissions",
    }


def _signed_headers(token: str, agent_id: str, body: bytes, nonce: str) -> dict[str, str]:
    sent_at = timezone.now().isoformat()
    request_id = f"request-{nonce}"
    secret = token.split(".", 1)[1]
    return {
        "HTTP_AUTHORIZATION": f"Agent {token}",
        "HTTP_X_AGENT_ID": agent_id,
        "HTTP_X_REQUEST_ID": request_id,
        "HTTP_X_SENT_AT": sent_at,
        "HTTP_X_NONCE": nonce,
        "HTTP_X_SIGNATURE": build_agent_signature(
            secret=secret,
            sent_at=sent_at,
            nonce=nonce,
            request_id=request_id,
            body=body,
        ),
    }


@pytest.mark.django_db
def test_agent_scope_signature_and_nonce_replay_are_enforced() -> None:
    owner = _user("agent-owner", "owner")
    agent, _ = _binding(owner)
    secret = "local-agent-secret"
    credential = BrokerAgentCredentialModel.objects.create(
        agent=agent,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        scopes=["agent.heartbeat.write"],
        allowed_account_ids=[7],
        expires_at=timezone.now() + timedelta(days=1),
    )
    token = f"{credential.credential_id}.{secret}"
    payload = {
        "contract_version": "1.0",
        "qmt_connected": True,
        "account_ids": [7],
        "agent_version": "0.1.0",
        "qmt_version": "fake",
        "dry_run": True,
    }
    body = json.dumps(payload).encode()
    headers = _signed_headers(token, agent.agent_id, body, "nonce-1")
    client = Client()
    first = client.post(
        "/api/broker-execution/agent/v1/heartbeat/",
        data=body,
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        "/api/broker-execution/agent/v1/heartbeat/",
        data=body,
        content_type="application/json",
        **headers,
    )
    assert first.status_code == 200
    assert replay.status_code == 403
    agent.refresh_from_db()
    assert agent.qmt_connected is True
    failed_audit = BrokerExecutionAuditModel.objects.get(
        action="agent_auth_failed",
        request_id=headers["HTTP_X_REQUEST_ID"],
    )
    assert failed_audit.actor_type == "agent"
    assert failed_audit.after["failure_code"] == "nonce_replayed"
    assert failed_audit.after["source_ip"] == "127.0.0.1"
    assert token not in json.dumps(failed_audit.after)


@pytest.mark.django_db
def test_agent_credential_account_scope_is_enforced_independently_of_binding() -> None:
    owner = _user("agent-account-scope-owner", "owner")
    agent, _ = _binding(owner, account_id=94)
    BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=95,
        agent=agent,
        broker_account_ref="broker-95",
        broker_account_mask="****0095",
        auto_execution_enabled=True,
        max_single_order_amount=Decimal("100000"),
        daily_order_amount_limit=Decimal("500000"),
        allowed_symbols=["510300.SH"],
    )
    secret = "account-scoped-agent-secret"
    credential = BrokerAgentCredentialModel.objects.create(
        agent=agent,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        scopes=["agent.heartbeat.write"],
        allowed_account_ids=[94],
        expires_at=timezone.now() + timedelta(days=1),
    )
    token = f"{credential.credential_id}.{secret}"
    client = Client()

    forbidden_payload = {
        "contract_version": "1.0",
        "qmt_connected": True,
        "account_ids": [95],
        "agent_version": "0.1.0",
        "qmt_version": "fake",
        "dry_run": True,
    }
    forbidden_body = json.dumps(forbidden_payload).encode()
    forbidden = client.post(
        "/api/broker-execution/agent/v1/heartbeat/",
        data=forbidden_body,
        content_type="application/json",
        **_signed_headers(token, agent.agent_id, forbidden_body, "scope-denied"),
    )
    assert forbidden.status_code == 403

    allowed_payload = forbidden_payload | {"account_ids": [94]}
    allowed_body = json.dumps(allowed_payload).encode()
    allowed = client.post(
        "/api/broker-execution/agent/v1/heartbeat/",
        data=allowed_body,
        content_type="application/json",
        **_signed_headers(token, agent.agent_id, allowed_body, "scope-allowed"),
    )
    assert allowed.status_code == 200


@pytest.mark.django_db
def test_broker_event_idempotency_is_scoped_to_agent() -> None:
    first_owner = _user("event-owner-1", "owner")
    second_owner = _user("event-owner-2", "owner")
    first_agent, _ = _binding(first_owner, account_id=91)
    second_agent, _ = _binding(second_owner, account_id=92)
    first_order = _order(first_owner, first_agent, account_id=91)
    second_order = _order(second_owner, second_agent, account_id=92)
    LiveOrderModel.objects.filter(
        pk__in=[first_order.pk, second_order.pk]
    ).update(status="SUBMITTING")
    repository = DjangoBrokerExecutionRepository()
    occurred_at = timezone.now().isoformat()

    first = repository.report_agent_events(
        agent_pk=first_agent.pk,
        allowed_account_ids=[91],
        events=[
            {
                "event_id": "broker-event-1",
                "client_order_id": str(first_order.client_order_id),
                "event_type": "QMT_ORDER_STATUS",
                "status": "BROKER_REJECTED",
                "occurred_at": occurred_at,
                "payload": {"status_msg": "broker price validation rejected"},
            }
        ],
    )
    second = repository.report_agent_events(
        agent_pk=second_agent.pk,
        allowed_account_ids=[92],
        events=[
            {
                "event_id": "broker-event-1",
                "client_order_id": str(second_order.client_order_id),
                "event_type": "QMT_ORDER_STATUS",
                "status": "BROKER_REJECTED",
                "occurred_at": occurred_at,
            }
        ],
    )

    assert first["accepted_count"] == 1
    assert second["accepted_count"] == 1
    assert BrokerOrderEventModel.objects.filter(event_id="broker-event-1").count() == 2
    first_order.refresh_from_db()
    assert first_order.failure_code == "QMT_ORDER_STATUS"
    assert first_order.failure_message == "broker price validation rejected"


@pytest.mark.django_db
def test_agent_overfill_stops_account_and_future_snapshot_is_rejected() -> None:
    owner = _user("overfill-owner", "owner")
    agent, _ = _binding(owner, account_id=93)
    order = _order(owner, agent, account_id=93)
    LiveOrderModel.objects.filter(pk=order.pk).update(status="SUBMITTED")
    repository = DjangoBrokerExecutionRepository()

    with pytest.raises(BrokerExecutionConflictError, match="future"):
        repository.sync_agent_snapshot(
            agent_pk=agent.pk,
            allowed_account_ids=[93],
            payload={
                "account_id": 93,
                "captured_at": (timezone.now() + timedelta(hours=1)).isoformat(),
                "cash_available": "100000",
                "total_asset": "100000",
                "positions": [],
            },
        )

    result = repository.report_agent_events(
        agent_pk=agent.pk,
        allowed_account_ids=[93],
        events=[
            {
                "event_id": "overfill-93",
                "client_order_id": str(order.client_order_id),
                "event_type": "QMT_TRADE",
                "status": "",
                "occurred_at": timezone.now().isoformat(),
                "fill": {
                    "broker_trade_id": "trade-overfill-93",
                    "quantity": "200",
                    "price": "3.9",
                    "occurred_at": timezone.now().isoformat(),
                },
            },
            {
                "event_id": "overfill-final-status-93",
                "client_order_id": str(order.client_order_id),
                "event_type": "QMT_ORDER_STATUS",
                "status": "FILLED",
                "occurred_at": timezone.now().isoformat(),
            },
        ],
    )

    order.refresh_from_db()
    assert order.status == "RECONCILIATION_REQUIRED"
    assert order.failure_code == "BROKER_OVERFILL"
    assert result["alerts"][0]["metadata"]["code"] == "P0_BROKER_OVERFILL"
    assert TradingControlModel.objects.get(
        user=owner,
        account_id=93,
    ).kill_switch_active


@pytest.mark.django_db
def test_admin_binding_and_credential_management_are_preview_first_and_idempotent() -> None:
    admin = _user("broker-admin", "admin", superuser=True)
    owner = _user("managed-owner", "owner")
    SimulatedAccountModel.objects.create(
        id=8,
        user=owner,
        account_name="Managed real account",
        account_type="real",
        initial_capital=Decimal("100000"),
        current_cash=Decimal("100000"),
        current_market_value=Decimal("0"),
        total_value=Decimal("100000"),
    )
    client = Client()
    client.force_login(admin)
    binding_payload = {
        "user_id": owner.id,
        "account_id": 8,
        "agent_id": "managed-agent-8",
        "display_name": "Managed QMT",
        "broker_account_ref": "sensitive-broker-account",
        "broker_account_mask": "****8888",
        "account_type": "STOCK",
        "is_active": True,
        "reason": "initial setup",
        "preview_only": True,
    }
    preview = client.post(
        "/api/broker-execution/bindings/",
        data=json.dumps(binding_payload),
        content_type="application/json",
    )
    assert preview.status_code == 200
    assert BrokerAccountBindingModel.objects.filter(account_id=8).exists() is False
    binding_payload.update(preview_only=False, idempotency_key="binding-8")
    commit = client.post(
        "/api/broker-execution/bindings/",
        data=json.dumps(binding_payload),
        content_type="application/json",
    )
    assert commit.status_code == 200
    rotate_payload = {
        "agent_id": "managed-agent-8",
        "scopes": ["agent.heartbeat.write"],
        "account_ids": [8],
        "expires_at": (timezone.now() + timedelta(days=1)).isoformat(),
        "preview_only": False,
        "idempotency_key": "credential-8",
    }
    issued = client.post(
        "/api/broker-execution/credentials/rotate/",
        data=json.dumps(rotate_payload),
        content_type="application/json",
    )
    replay = client.post(
        "/api/broker-execution/credentials/rotate/",
        data=json.dumps(rotate_payload),
        content_type="application/json",
    )
    assert issued.status_code == 200
    assert issued.json()["data"]["token"]
    assert replay.json()["data"]["token"] == ""
    assert replay.json()["data"]["shown_once"] is False
    connection_page = client.get("/broker-execution/connection/")
    connection_html = connection_page.content.decode("utf-8")
    assert "立即撤销" in connection_html
    assert "解绑" in connection_html
    assert "测试连接 / 立即同步" in connection_html

    sync_payload = {
        "agent_id": "managed-agent-8",
        "reason": "verify local connection",
        "preview_only": True,
    }
    sync_preview = client.post(
        "/api/broker-execution/connections/sync/",
        data=json.dumps(sync_payload),
        content_type="application/json",
    )
    assert sync_preview.status_code == 200
    assert BrokerCommandModel.objects.count() == 0
    sync_payload.update(
        preview_only=False,
        idempotency_key="connection-sync-8",
    )
    sync_commit = client.post(
        "/api/broker-execution/connections/sync/",
        data=json.dumps(sync_payload),
        content_type="application/json",
    )
    sync_replay = client.post(
        "/api/broker-execution/connections/sync/",
        data=json.dumps(sync_payload),
        content_type="application/json",
    )
    assert sync_commit.status_code == 200
    assert sync_replay.status_code == 200
    command = BrokerCommandModel.objects.get()
    assert command.command_type == "full_sync"
    assert command.status == "pending"
    assert sync_replay.json()["data"]["command_id"] == str(command.command_id)

    credential_id = issued.json()["data"]["credential_id"]
    revoke_endpoint = (
        f"/api/broker-execution/credentials/{credential_id}/revoke/"
    )
    revoke_preview = client.post(
        revoke_endpoint,
        data=json.dumps({"reason": "rotation complete", "preview_only": True}),
        content_type="application/json",
    )
    revoke_commit = client.post(
        revoke_endpoint,
        data=json.dumps(
            {
                "reason": "rotation complete",
                "preview_only": False,
                "idempotency_key": "credential-revoke-8",
            }
        ),
        content_type="application/json",
    )
    assert revoke_preview.status_code == 200
    assert revoke_commit.status_code == 200
    assert BrokerAgentCredentialModel.objects.get(
        credential_id=credential_id
    ).revoked_at is not None

    unbind_payload = {
        "user_id": owner.id,
        "account_id": 8,
        "agent_id": "managed-agent-8",
        "is_active": False,
        "reason": "device retired",
        "preview_only": False,
        "idempotency_key": "binding-disable-8",
    }
    unbind = client.post(
        "/api/broker-execution/bindings/",
        data=json.dumps(unbind_payload),
        content_type="application/json",
    )
    assert unbind.status_code == 200
    assert not BrokerAccountBindingModel.objects.get(account_id=8).is_active

    audit_html = client.get("/broker-execution/audit/").content.decode("utf-8")
    assert "筛选审计记录" in audit_html
    assert "导出当前筛选 CSV" in audit_html


@pytest.mark.django_db
def test_strict_get_endpoints_do_not_mutate_persisted_execution_state() -> None:
    owner = _user("strict-read-owner", "owner")
    agent, _ = _binding(owner)
    order = _order(owner, agent)
    client = Client()
    client.force_login(owner)
    before = {
        "agents": BrokerAgentModel.objects.count(),
        "bindings": BrokerAccountBindingModel.objects.count(),
        "orders": LiveOrderModel.objects.count(),
        "audits": BrokerExecutionAuditModel.objects.count(),
        "controls": TradingControlModel.objects.count(),
    }
    paths = [
        "/api/broker-execution/",
        "/api/broker-execution/orders/",
        f"/api/broker-execution/orders/{order.client_order_id}/",
        "/api/broker-execution/connections/",
        "/api/broker-execution/reconciliations/",
        "/api/broker-execution/audit/",
    ]
    assert all(client.get(path).status_code == 200 for path in paths)
    after = {
        "agents": BrokerAgentModel.objects.count(),
        "bindings": BrokerAccountBindingModel.objects.count(),
        "orders": LiveOrderModel.objects.count(),
        "audits": BrokerExecutionAuditModel.objects.count(),
        "controls": TradingControlModel.objects.count(),
    }
    assert after == before
