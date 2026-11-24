"""Exercise the real display material lifecycle independently of native order execution."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import resolve
from rest_framework.test import APIRequestFactory

from apps.broker_execution.interface.order_scope_views import BrokerOrderExecutionScopeView
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.order_execution_evidence_composition import _read_fenced_evidence
from tests.component.broker_execution.ash09_order_scope_sources import persist_research_output


@pytest.mark.parametrize("action", ["preview", "sign", "revoke"])
def test_order_scope_commands_require_authentication(action):
    path = f"/api/broker-execution/orders/{uuid4()}/execution-scope/{action}/"
    resolved = resolve(path)
    assert resolved.func.cls is BrokerOrderExecutionScopeView
    response = resolved.func(
        APIRequestFactory().post(path, {"account_id": 2}, format="json"), **resolved.kwargs
    )
    response.render()
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_scoped_order_material_stays_display_only_under_real_operator_approval():
    sessions = []
    users = []
    for name in ("material-registrar", "material-independent-reviewer"):
        user = get_user_model().objects.create_user(username=name, is_staff=True)
        session = Client()
        session.force_login(user)
        users.append(user)
        sessions.append(session)
    order = ArtifactRef(
        "broker_execution", "live_order_approval_snapshot", str(uuid4()), "1", "1" * 64
    )
    plan = ArtifactRef("portfolio", "transition_plan", "plan-1", "v1", "2" * 64)
    receipt = ArtifactRef("portfolio", "transition_plan_approval", "receipt-1", "v1", "3" * 64)
    selectors = {
        "order": order,
        "plan": plan,
        "plan_receipt": receipt,
        "owner_user_id": users[0].pk,
        "owner_id": "owner-1",
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "using": "default",
    }
    selected = persist_research_output(
        **selectors,
        registrar_session=sessions[0],
        reviewer_session=sessions[1],
        ordinary_material=True,
    )
    content_hash = selected.pop("envelope_content_hash")
    selectors.update(selected_output=ArtifactRef(**selected), expected_envelope_hash=content_hash)
    result = _read_fenced_evidence(**selectors)
    assert result is not None
    assert result.permission == "display_only" and result.governance_state == "research_only"
    assert result.blockers == ("evidence.output_not_promoted",)
    assert len(result.read_scope_hashes) == 3
    assert result.linked_order_sources == (plan,)
    assert _read_fenced_evidence(**{**selectors, "account_id": "wrong-account"}) is None
    assert _read_fenced_evidence(**{**selectors, "owner_user_id": users[1].pk}) is None
    assert _read_fenced_evidence(**{**selectors, "expected_envelope_hash": "0" * 64}) is None
    unrelated_plan = ArtifactRef("portfolio", "transition_plan", "plan-2", "v1", "7" * 64)
    assert _read_fenced_evidence(**{**selectors, "plan": unrelated_plan}) is None
