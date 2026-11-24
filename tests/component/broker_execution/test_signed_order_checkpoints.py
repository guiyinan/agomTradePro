"""Exercise all four order mutations with independently issued source facts on loopback PostgreSQL."""

import base64
import hashlib
import json
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.test import Client
from django.utils import timezone

from apps.broker_execution.application.agent_auth import build_agent_signature
from apps.broker_execution.application.evidence_gate import broker_order_evidence_integrated
from apps.broker_execution.domain.execution_contract_capabilities import (
    EXECUTION_CONSTRAINT_SCHEMA_V2,
)
from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAgentCredentialModel,
    BrokerExecutionAuditModel,
    LiveOrderModel,
    OrderLeaseModel,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import DatasetContractRepository
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from tests.component.data_center import test_execution_quote_activation_workflow as market
from tests.component.data_center.test_publication_activation import (
    _FenceResult as BenchmarkMarketPublisher,
)
from tests.component.portfolio.test_benchmark_issuance_native import (
    benchmark_world as benchmark_world,
)
from tests.component.risk_center.test_broker_order_execution_policy_repository import _controls
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.broker_authority_intent import (
    bind_broker_to_live_portfolio_owner,
    persist_signed_intent,
)
from tests.support.portfolio_benchmark_ledger_cleanup import (
    isolated_benchmark_ledger as isolated_benchmark_ledger,
)
from tests.support.portfolio_benchmark_valuation import publish_signed_broker_balances

pytestmark = pytest.mark.django_db(transaction=True)


def _session(user):
    session = Client(enforce_csrf_checks=True)
    login = session.get("/account/login/")
    assert login.status_code == 200
    session.force_login(user)
    session.defaults["HTTP_X_CSRFTOKEN"] = session.cookies[settings.CSRF_COOKIE_NAME].value
    return session


def _http(session, method, path, payload, expected=200):
    response = getattr(session, method)(path, payload, content_type="application/json")
    assert response.status_code == expected, (path, response.content[:1200])
    assert response["Content-Type"].startswith("application/json")
    return response.json()


def _machine(agent, account_id):
    secret = secrets.token_urlsafe(32)
    credential = BrokerAgentCredentialModel.objects.create(
        agent=agent,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        scopes=[
            "agent.heartbeat.write",
            "agent.orders.lease",
            "agent.orders.submitting_ack",
            "agent.events.write",
            "agent.snapshots.write",
        ],
        allowed_account_ids=[account_id],
        expires_at=timezone.now() + timedelta(hours=1),
    )

    def post(route, payload, expected=200):
        body = json.dumps({"contract_version": "1.0", **payload}).encode()
        nonce, req, sent_at = uuid4().hex, uuid4().hex, datetime.now(UTC).isoformat()
        response = Client().post(
            f"/api/broker-execution/agent/v1/{route}/",
            body,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Agent {credential.credential_id}.{secret}",
            HTTP_X_AGENT_ID=agent.agent_id,
            HTTP_X_REQUEST_ID=req,
            HTTP_X_NONCE=nonce,
            HTTP_X_SENT_AT=sent_at,
            HTTP_X_SIGNATURE=build_agent_signature(
                secret=secret, sent_at=sent_at, nonce=nonce, request_id=req, body=body
            ),
        )
        assert response.status_code == expected, (route, response.content[:1000])
        assert response["Content-Type"].startswith("application/json")
        return response.json()

    return post


def _prepare_risk_inputs(session, review, account_id):
    controls = _controls().to_payload()
    _http(review, "put", "/api/risk-center/floor/", {"is_active": True, **controls})
    template = _http(
        review,
        "post",
        "/api/risk-center/templates/",
        {
            "key": "ash09-exact",
            "name": "Isolated live order",
            "risk_profile": "moderate",
            **controls,
        },
        201,
    )["data"]
    return _http(
        session,
        "post",
        "/api/risk-center/account-policies/",
        {
            "account_id": account_id,
            "template_id": template["id"],
            "risk_profile": "moderate",
            "is_active": True,
            **controls,
        },
        201,
    )["data"]["id"]


def _publish_execution_quote():
    contracts, policies = DatasetContractRepository(), PublicationPolicyRepository()
    baseline = contracts.get_active_for_execution("equity.quote.snapshot")
    policy = policies.get_active("equity.quote.snapshot")
    assert baseline is not None and policy is not None
    # The standard catalog has no execution TTL. Publish a distinct rehearsal contract
    # through its owner, preserving all existing catalog versions and their contents.
    dataset = replace(baseline.key, contract_version="ash09-quote-v1")
    contracts.save(replace(baseline, key=dataset, execution_freshness_seconds=300))
    policies.save(replace(policy, dataset=dataset, policy_version="ash09-quote-policy-v1"))
    quote, raw, run_id, asset = market._seed_execution_quote(create_catalog=False, dataset=dataset)
    publisher = BenchmarkMarketPublisher()
    arguments = market._stage_arguments(raw, run_id, asset)
    arguments["preflight_context"] = market._reader_context(
        tenant_id=publisher.tenant_id, owner_id=publisher.owner_id
    )
    published = market.stage_and_activate_execution_quote_candidate(
        bundle=market._bundle(
            authority_tenant_id=publisher.tenant_id, authority_owner_id=publisher.owner_id
        ),
        **arguments,
    )
    assert str(market.get_execution_quote(asset, as_of=timezone.now()).fact_pk) == str(quote.pk)
    assert published.state.value == "published"


def _risk_receipt(session, review, account_id, order_id, grant):
    base = f"/api/risk-center/broker-orders/{account_id}/{order_id}"
    policy = _http(
        review,
        "post",
        f"{base}/risk-policy/",
        {"policy_id": uuid4().hex, "policy_version": "v1", "valid_until": grant["valid_until"]},
        201,
    )["data"]
    subject_id = uuid4().hex
    _http(
        session,
        "post",
        f"{base}/risk-subject/",
        {
            "subject_id": subject_id,
            "execution_scope_id": grant["execution_scope_id"],
            "execution_scope_version": grant["execution_scope_version"],
            "policy_id": policy["id"],
            "policy_version": policy["version"],
        },
        201,
    )
    authorization = {"subject_id": subject_id, "authorization_id": uuid4().hex}
    _http(session, "post", f"{base}/risk-approval/", authorization, 409)
    receipt = _http(review, "post", f"{base}/risk-approval/", authorization, 201)["data"]
    assert receipt["id"] == authorization["authorization_id"] and len(receipt["content_hash"]) == 64
    return receipt


def _assert_checkpoint_audit(order, intent, grant, risk):
    actions = ("create_live_order", "order_approve", "order_lease", "order_submitting")
    trail = list(
        BrokerExecutionAuditModel.objects.filter(
            resource_type="live_order", resource_id=str(order.client_order_id), action__in=actions
        ).order_by("id")
    )
    assert [row.action for row in trail] == list(actions)
    assert [row.after["status"] for row in trail] == [
        "WAITING_APPROVAL",
        "READY",
        "LEASED",
        "SUBMITTING",
    ]
    assert [row.after["version"] for row in trail] == [2, 3, 4, 5]
    plan, binding = intent.sources.plan, intent.sources.account
    expected = {
        "order_id": str(order.client_order_id),
        "order_version": str(intent.order_version),
        "order_artifact_version": intent.sources.order.artifact_version,
        "order_artifact_hash": intent.sources.order.content_hash,
        "account_id": str(order.account_id),
        "account_binding_id": binding.binding_id,
        "account_binding_version": binding.binding_version,
        "account_binding_hash": binding.content_hash,
        "plan_id": plan.portfolio_plan_id,
        "plan_version": str(plan.portfolio_plan_version),
        "plan_hash": plan.portfolio_plan_content_hash,
        "plan_binding_hash": plan.content_hash,
        "plan_order_ordinal": str(plan.plan_order_ordinal),
        "plan_order_hash": plan.plan_order_content_hash,
        "plan_approval_id": plan.portfolio_receipt_id,
        "plan_approval_version": plan.portfolio_receipt_version,
        "plan_approval_hash": plan.portfolio_receipt_content_hash,
        "execution_scope_id": grant["execution_scope_id"],
        "execution_scope_version": grant["execution_scope_version"],
        "execution_scope_hash": grant["execution_scope_hash"],
        "risk_approval_id": risk["id"],
        "risk_approval_version": risk["version"],
        "risk_approval_hash": risk["content_hash"],
    }
    assert order.authority_pin == expected
    assert all(
        row.after["clock_source"] == "server" and row.after["authority_pin"] == expected
        for row in trail
    )


def _replace_account_policy(session, account_policy_id):
    updated = _http(
        session,
        "patch",
        f"/api/risk-center/account-policies/{account_policy_id}/",
        {"max_single_position_pct": 0.19},
    )["data"]
    assert updated["id"] == account_policy_id and Decimal(
        str(updated["max_single_position_pct"])
    ) == Decimal("0.19")


@pytest.fixture
def disposable_receipt_key(monkeypatch):
    from shared.config.secrets import get_secrets

    monkeypatch.setenv(
        "AGOMTRADEPRO_ENCRYPTION_KEY", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    )
    get_secrets.cache_clear()
    try:
        yield
    finally:
        get_secrets.cache_clear()


def test_signed_account_order_checkpoints(benchmark_world, disposable_receipt_key):
    from tests.component.broker_execution.ash09_order_scope_sources import persist_order_research
    from tests.component.broker_execution.signed_order_reconciliation_flow import (
        assert_signed_order_reconciliation,
    )

    assert broker_order_evidence_integrated()
    owner, reviewer, _, _, account, agent, identity, _, _ = benchmark_world
    session, review = _session(owner), _session(reviewer)
    account_id = account.pk
    _http(
        review,
        "patch",
        f"/api/broker-execution/settings/{account_id}/",
        {
            "preview_only": False,
            "idempotency_key": uuid4().hex,
            "reason": "isolated authorized execution rehearsal",
            "auto_execution_enabled": True,
            "allowed_symbols": ["600000.SH"],
            "enforce_trading_session": False,
            "max_single_order_amount": "5000",
            "daily_order_amount_limit": "10000",
            "max_position_count": 10,
            "max_snapshot_age_seconds": 300,
            "price_deviation_limit_pct": "0.05",
        },
    )
    binding = BrokerAccountBindingModel.objects.get(account_id=account_id)
    mapping = bind_broker_to_live_portfolio_owner(identity=identity, binding=binding)
    intent = persist_signed_intent(
        account_binding=mapping,
        approver_user_id=reviewer.pk,
        agent_id=agent.agent_id,
        risk_policy_version="v1",
    )
    material = persist_order_research(
        ordinary_material=True,
        intent=intent,
        tenant_id=identity.tenant_id,
        owner_id=identity.owner_id,
        registrar_session=session,
        reviewer_session=review,
    )
    account_policy_id = _prepare_risk_inputs(session, review, account_id)
    _publish_execution_quote()
    machine = _machine(agent, account_id)
    machine(
        "heartbeat",
        {
            "observed_at": timezone.now().isoformat(),
            "qmt_connected": True,
            "account_ids": [account_id],
            "agent_version": "0.2.0",
            "execution_constraint_schemas": [EXECUTION_CONSTRAINT_SCHEMA_V2],
        },
    )
    publish_signed_broker_balances(
        agent=agent,
        account_id=account_id,
        broker_ref=binding.broker_account_ref,
        captured_at=timezone.now(),
    )
    order_id = str(intent.client_order_id)
    order_api = f"/api/broker-execution/orders/{order_id}"
    scope = f"{order_api}/execution-scope"
    confirm = {"account_id": account_id, "research_material": material}
    create = {"account_id": account_id, "client_order_id": order_id, "idempotency_key": uuid4().hex}
    _http(session, "post", "/api/broker-execution/orders/", create, 409)
    assert not LiveOrderModel.objects.filter(client_order_id=order_id).exists()
    _http(
        session,
        "post",
        f"{scope}/preview/",
        {**confirm, "research_material": {**material, "envelope_content_hash": "0" * 64}},
        409,
    )
    preview = _http(session, "post", f"{scope}/preview/", confirm)
    assert preview["expected_order_hash"] == intent.sources.order.content_hash
    _http(session, "post", f"{scope}/sign/", {**confirm, "expected_review_hash": "0" * 64}, 409)
    grant = _http(
        session,
        "post",
        f"{scope}/sign/",
        {**confirm, "expected_review_hash": preview["expected_review_hash"]},
    )
    _http(session, "post", "/api/broker-execution/orders/", create, 409)
    assert not LiveOrderModel.objects.filter(client_order_id=order_id).exists()
    risk = _risk_receipt(session, review, account_id, order_id, grant)
    _http(session, "post", "/api/broker-execution/orders/", create)
    order = LiveOrderModel.objects.get(client_order_id=order_id)
    assert (
        order.status == "WAITING_APPROVAL"
        and order.authority_pin["execution_scope_hash"] == grant["execution_scope_hash"]
    )
    pin_migration = import_module("apps.broker_execution.migrations.0014_live_order_authority_pin")
    with pytest.raises(IrreversibleError), transaction.atomic():
        with connection.schema_editor(atomic=False) as editor:
            pin_migration.remove_pin_guard(apps, editor)
    approve = {
        "preview_only": False,
        "expected_version": order.version,
        "idempotency_key": uuid4().hex,
        "reason": "isolated approved order",
    }
    with transaction.atomic():
        _replace_account_policy(session, account_policy_id)
        _http(session, "post", f"{order_api}/approve/", approve, 409)
        order.refresh_from_db()
        assert (order.status, order.version) == ("WAITING_APPROVAL", approve["expected_version"])
        transaction.set_rollback(True)
    _http(session, "post", f"{order_api}/approve/", approve)
    order.refresh_from_db()
    ready_version = order.version
    with transaction.atomic():
        changed = LiveOrderModel.objects.filter(pk=order.pk).update(
            limit_price=order.limit_price + Decimal("0.01")
        )
        assert changed == 1
        assert machine("orders/lease", {"limit": 1, "lease_seconds": 90})["data"]["orders"] == []
        order.refresh_from_db()
        assert (order.status, order.version) == ("READY", ready_version)
        assert not OrderLeaseModel.objects.filter(order=order).exists()
        transaction.set_rollback(True)
    leased = machine("orders/lease", {"limit": 1, "lease_seconds": 90})["data"]["orders"]
    assert len(leased) == 1 and str(leased[0]["client_order_id"]) == order_id
    ack = {"client_order_id": order_id, "lease_token": leased[0]["lease_token"]}
    order.refresh_from_db()
    leased_version = order.version
    with transaction.atomic():
        _replace_account_policy(session, account_policy_id)
        machine("orders/submitting", ack, 409)
        order.refresh_from_db()
        assert (order.status, order.version) == ("LEASED", leased_version)
        transaction.set_rollback(True)
    with transaction.atomic():
        assert machine("orders/submitting", ack)["data"]["accepted"]
        order.refresh_from_db()
        assert order.status == "SUBMITTING"
        _assert_checkpoint_audit(order, intent, grant, risk)
        assert_signed_order_reconciliation(order=order, machine=machine)
        # Keep this same lease open to exercise the opposite branch following a real withdrawal.
        transaction.set_rollback(True)
    assert _http(
        session,
        "post",
        f"{scope}/revoke/",
        {"account_id": account_id, "expected_scope_hash": grant["execution_scope_hash"]},
    )["revoked"]
    _http(session, "post", "/api/broker-execution/orders/", create, 409)
    _http(session, "post", f"{order_api}/approve/", approve, 409)
    machine("orders/submitting", ack, 409)
    order.refresh_from_db()
    assert order.status == "LEASED" and OrderLeaseModel.objects.get(order=order).released_at is None
