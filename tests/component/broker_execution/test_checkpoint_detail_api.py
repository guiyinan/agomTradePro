"""Only the actual owner can opt in to source diagnostics on the existing order route."""

import pytest
from django.db import OperationalError, connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.broker_execution.application.evidence_gate import BROKER_ORDER_EVIDENCE_BLOCKER
from apps.broker_execution.infrastructure.models import BrokerAccountAccessModel
from tests.component.broker_execution.test_api_and_permissions import _binding, _order, _user


@pytest.mark.django_db
def test_order_detail_diagnostics_require_current_order_and_binding_ownership():
    owner = _user("checkpoint-detail-owner", "owner")
    trader = _user("checkpoint-detail-delegate", "trader")
    outsider = _user("checkpoint-detail-outsider", "trader")
    admin = _user("checkpoint-detail-admin", "admin", superuser=True)
    agent, binding = _binding(owner)
    order = _order(owner, agent)
    url = f"/api/broker-execution/orders/{order.client_order_id}/"
    BrokerAccountAccessModel.objects.create(user=trader, account_id=7, can_trade=True)
    client = Client()
    client.force_login(owner)
    with CaptureQueriesContext(connection) as queries:
        default = client.get(url)
    assert default.status_code == 200
    assert default.headers["Content-Type"].startswith("application/json")
    assert "checkpoint_diagnostics" not in default.json()["data"]
    assert not any("broker_execution_pre_risk_scope" in query["sql"] for query in queries)
    assert client.get(url + "?checkpoint=1&checkpoint=0").status_code == 400
    result = client.get(url, {"checkpoint": "1"})
    assert result.status_code == 200
    assert result.headers["Content-Type"].startswith("application/json")
    data = result.json()["data"]
    assert data["must_not_execute"] is True
    diagnostic = data["checkpoint_diagnostics"]
    assert set(diagnostic) == {"permission", "must_not_execute", "blocker_codes"}
    assert diagnostic["permission"] == "display_only" and diagnostic["must_not_execute"] is True
    assert BROKER_ORDER_EVIDENCE_BLOCKER in diagnostic["blocker_codes"]
    assert "broker_checkpoint_pre_risk_scope_missing_or_ambiguous" in diagnostic["blocker_codes"]
    if connection.vendor == "sqlite":
        assert "broker_checkpoint_risk_fence_unavailable" in diagnostic["blocker_codes"]
    # Exercise the public route under a storage lock failure after ownership was observed.
    owner_observed = False
    lock_order = []

    def unavailable(execute, sql, params, many, context):
        nonlocal owner_observed
        if (
            'AS "a" FROM "broker_execution_live_order"' in sql
            and "broker_execution_account_binding" in sql
        ):
            owner_observed = True
        elif owner_observed and 'FROM "broker_execution_live_order"' in sql:
            lock_order.append("order")
        if (
            owner_observed
            and "broker_execution_account_binding" in sql
            and "LIMIT 1" in sql
            and "broker_execution_live_order" not in sql
        ):
            lock_order.append("binding")
            raise OperationalError("isolated account row lock unavailable")
        return execute(sql, params, many, context)

    with connection.execute_wrapper(unavailable):
        busy = client.get(url, {"checkpoint": "1"})
    assert lock_order == ["order", "binding"]
    assert busy.status_code == 200
    assert busy.json()["data"]["checkpoint_diagnostics"]["blocker_codes"] == [
        BROKER_ORDER_EVIDENCE_BLOCKER,
        "broker_checkpoint_temporarily_unavailable",
    ]
    for viewer in (trader, admin):
        client.force_login(viewer)
        with CaptureQueriesContext(connection) as queries:
            result = client.get(url, {"checkpoint": "1"})
        assert result.status_code == 200
        assert "checkpoint_diagnostics" not in result.json()["data"]
        assert not any("broker_execution_pre_risk_scope" in query["sql"] for query in queries)
    client.force_login(outsider)
    assert client.get(url, {"checkpoint": "1"}).status_code == 404
    client.force_login(owner)
    binding.is_active = False
    binding.save(update_fields=["is_active"])
    assert "checkpoint_diagnostics" not in client.get(url + "?checkpoint=1").json()["data"]
    client.logout()
    assert client.get(url + "?checkpoint=1").status_code in (401, 403)
