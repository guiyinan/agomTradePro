"""Immutable broker receipts and conservative resolution of out-of-order reports."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.infrastructure.models import BrokerOrderEventModel, TradingControlModel
from apps.broker_execution.infrastructure.repositories import DjangoBrokerExecutionRepository
from tests.component.broker_execution.test_api_and_permissions import _binding, _order, _user

pytestmark = pytest.mark.django_db


@pytest.fixture
def stream():
    owner = _user("receipt-owner", "owner")
    agent, _ = _binding(owner)
    order = _order(owner, agent)
    order.status = "SUBMITTING"
    order.save()
    repository = DjangoBrokerExecutionRepository()

    def report(*events):
        return repository.report_agent_events(
            agent_pk=agent.pk, allowed_account_ids=[7], events=list(events)
        )

    return order, report


def _event(order, event_type="QMT_TRADE", **overrides):
    clock = timezone.now().isoformat()
    return {
        "event_id": "trade-1",
        "client_order_id": str(order.client_order_id),
        "event_type": event_type,
        "broker_order_id": "B1",
        "occurred_at": clock,
        "status": "",
        "payload": {"clock_source": "agent_observed", "broker_source_at": None},
        "fill": {"broker_trade_id": "T1", "quantity": "20", "price": "3.9", "occurred_at": clock},
        **overrides,
    }


@pytest.mark.parametrize(
    "field,value", [("broker_trade_id", "T2"), ("quantity", "25"), ("price", "4")]
)
def test_duplicate_rejects_substituted_trade(stream, field, value):
    order, report = stream
    first = _event(order)
    report(first)
    changed = deepcopy(first)
    changed["fill"][field] = value
    with pytest.raises(BrokerExecutionConflictError):
        report(changed)
    assert order.fills.count() == order.broker_events.count() == 1
    assert order.fills.get().quantity == Decimal("20")


def test_broker_identity_cannot_be_removed_on_duplicate(stream):
    order, report = stream
    event = _event(order)
    report(event)
    with pytest.raises(BrokerExecutionConflictError):
        report({**event, "broker_order_id": ""})


@pytest.mark.parametrize(
    "clock,source",
    [
        ("agent_observed", "2026-01-01T00:00:00+00:00"),
        ("broker", None),
        ("broker", "invalid"),
        ("invented", None),
        ("broker", "2039-01-01T00:00:00+00:00"),
    ],
)
def test_explicit_clock_requires_consistent_aware_source(stream, clock, source):
    order, report = stream
    with pytest.raises(BrokerExecutionConflictError):
        report(_event(order, payload={"clock_source": clock, "broker_source_at": source}))
    assert not order.fills.exists() and not order.broker_events.exists()


def test_fill_clock_cannot_override_event_source(stream):
    order, report = stream
    event = _event(order)
    event["fill"]["payload"] = {"clock_source": "broker", "broker_source_at": event["occurred_at"]}
    with pytest.raises(BrokerExecutionConflictError):
        report(event)
    assert not order.fills.exists()


def test_resampled_observation_can_replay_without_changing_original(stream):
    order, report = stream
    first = _event(order)
    report(first)
    observed = order.broker_events.get().occurred_at
    later = timezone.now().isoformat()
    original = deepcopy(first)
    original.update(occurred_at=later)
    original["fill"]["occurred_at"] = later
    original["fill"]["quantity"] = "20.0000"
    replay = report(original)
    assert replay["duplicate_count"] == 1 and order.broker_events.get().occurred_at == observed


def test_unknown_event_keeps_evidence_and_stops_without_fill(stream):
    order, report = stream
    response = report(_event(order, event_type="VENDOR_NEW", status="FILLED"))
    order.refresh_from_db()
    assert response["alerts"] and TradingControlModel.objects.get(account_id=7).kill_switch_active
    assert order.broker_events.get().event_type == "UNKNOWN"
    assert order.status == "RECONCILIATION_REQUIRED" and not order.fills.exists()
    assert not order.broker_order_id


def test_terminal_contradiction_keeps_first_state_and_stops(stream):
    order, report = stream
    order.status = "FILLED"
    order.broker_order_id = "B1"
    order.save()
    rejected = _event(order, event_type="QMT_ORDER_STATUS", status="BROKER_REJECTED")
    rejected.pop("fill")
    response = report(rejected)
    order.refresh_from_db()
    assert order.status == "FILLED" and response["alerts"]
    assert TradingControlModel.objects.get(account_id=7).kill_switch_active


def test_fill_and_confirmed_status_before_late_ack(stream):
    order, report = stream
    first = _event(order)
    report(first)
    status = _event(
        order, event_id="partial", event_type="QMT_ORDER_STATUS", status="PARTIALLY_FILLED"
    )
    status.pop("fill")
    assert not report(status)["alerts"]
    ack = {**status, "event_id": "ack", "event_type": "ORDER_SUBMITTED", "status": "SUBMITTED"}
    assert not report(ack)["alerts"]
    order.refresh_from_db()
    assert order.status == "PARTIALLY_FILLED" and order.filled_quantity == Decimal("20")
    assert not TradingControlModel.objects.filter(account_id=7, kill_switch_active=True).exists()


def test_legacy_receipt_replays_original_without_applying_new_effects(stream):
    order, report = stream
    event = _event(order, status="SUBMITTED", event_type="QMT_ORDER_STATUS")
    event.pop("fill")
    BrokerOrderEventModel.objects.create(
        agent=order.agent,
        order=order,
        event_id=event["event_id"],
        event_type=event["event_type"],
        status="SUBMITTED",
        occurred_at=timezone.now() - timedelta(seconds=2),
        payload={},
    )
    assert report(event)["duplicate_count"] == 1
    order.refresh_from_db()
    assert order.status == "SUBMITTING" and not order.fills.exists()


def test_same_trade_under_new_event_id_cannot_change_economics_or_source_time(stream):
    order, report = stream
    first = _event(order)
    first["payload"] = {"clock_source": "broker", "broker_source_at": first["occurred_at"]}
    report(first)
    second = deepcopy(first)
    second["event_id"] = "second-report"
    second["fill"]["quantity"] = "21"
    with pytest.raises(BrokerExecutionConflictError, match="economics"):
        report(second)
    second["fill"]["quantity"] = "20"
    earlier = (timezone.now() - timedelta(minutes=1)).isoformat()
    second["occurred_at"] = second["fill"]["occurred_at"] = earlier
    second["payload"]["broker_source_at"] = earlier
    with pytest.raises(BrokerExecutionConflictError, match="source time"):
        report(second)
    assert order.broker_events.count() == order.fills.count() == 1
    assert order.fills.get().quantity == Decimal("20")


@pytest.mark.parametrize("event_type", ["QMT_ORDER_STATUS", "ORDER_SUBMITTED", "FAKE_ORDER_STATUS"])
def test_order_ack_cannot_use_broker_insertion_time_as_status_time(stream, event_type):
    order, report = stream
    event = _event(order, event_type=event_type, status="SUBMITTED")
    event.pop("fill")
    event["payload"] = {"clock_source": "broker", "broker_source_at": event["occurred_at"]}
    with pytest.raises(BrokerExecutionConflictError):
        report(event)
    assert not order.broker_events.exists()


def test_real_trade_time_and_missing_legacy_clock_are_distinguished(stream):
    order, report = stream
    first = _event(order)
    first["payload"] = {"clock_source": "broker", "broker_source_at": first["occurred_at"]}
    report(first)
    assert (
        order.fills.get().payload["broker_source_at"] == order.fills.get().occurred_at.isoformat()
    )
    later = _event(order, event_type="ORDER_SUBMITTED", event_id="legacy-ack", status="SUBMITTED")
    later.pop("fill")
    later.pop("payload")
    report(later)
    clock = order.broker_events.get(event_id="legacy-ack").payload
    assert clock["clock_source"] == "unknown" and clock["broker_source_at"] is None


@pytest.mark.parametrize(
    "initial,expected",
    [("READY", "RECONCILIATION_REQUIRED"), ("BROKER_REJECTED", "BROKER_REJECTED")],
)
def test_real_fill_in_incompatible_order_state_requires_stop(stream, initial, expected):
    order, report = stream
    order.status = initial
    order.save()
    response = report(_event(order))
    order.refresh_from_db()
    assert order.status == expected and order.fills.count() == 1
    assert response["alerts"] and TradingControlModel.objects.get(account_id=7).kill_switch_active


def test_order_report_cannot_reject_unapproved_order_as_a_human(stream):
    order, report = stream
    order.status = "WAITING_APPROVAL"
    order.save()
    event = _event(order, event_type="QMT_ORDER_STATUS", status="REJECTED")
    event.pop("fill")
    assert report(event)["alerts"]
    order.refresh_from_db()
    assert order.status == "RECONCILIATION_REQUIRED"


def test_explicit_qmt_account_mismatch_rolls_back_and_does_not_publish_plaintext(stream):
    order, report = stream
    event = _event(order)
    event["fill"]["broker_account_ref"] = "other-private-account"
    with pytest.raises(BrokerExecutionConflictError, match="account"):
        report(event)
    assert not order.fills.exists() and not order.broker_events.exists()
    event["fill"]["broker_account_ref"] = "broker-7"
    report(event)
    assert "broker-7" not in str(order.broker_events.get().payload)
    event["fill"]["broker_account_ref"] = "changed"
    with pytest.raises(BrokerExecutionConflictError):
        report(event)
    assert order.fills.get().broker_account_ref == "broker-7"


@pytest.mark.parametrize("event_type", ["FAKE_TRADE", "FAKE_ORDER_STATUS"])
def test_fake_namespace_cannot_update_live_binding(stream, event_type):
    order, report = stream
    event = _event(order, event_type=event_type)
    if event_type == "FAKE_ORDER_STATUS":
        event.pop("fill")
        event["status"] = "SUBMITTED"
    else:
        event["fill"]["broker_account_ref"] = "fake"
    with pytest.raises(BrokerExecutionConflictError, match="source"):
        report(event)
    assert not order.fills.exists() and not order.broker_events.exists()


def test_fake_binding_accepts_its_simulator_and_rejects_qmt(stream):
    order, report = stream
    binding = order.agent.account_bindings.get()
    binding.broker_account_ref = "fake"
    binding.save(update_fields=["broker_account_ref"])
    event = _event(order, event_type="FAKE_TRADE")
    event["fill"]["broker_account_ref"] = "fake"
    report(event)
    assert order.fills.get().broker_account_ref == "fake"
    wrong = _event(order, event_id="other")
    with pytest.raises(BrokerExecutionConflictError, match="source"):
        report(wrong)
    assert order.fills.count() == order.broker_events.count() == 1


@pytest.mark.parametrize("rollback_outer", [False, True])
def test_partial_batch_forwards_only_committed_alert_once(
    stream, monkeypatch, django_capture_on_commit_callbacks, rollback_outer
):
    from django.db import transaction

    from apps.broker_execution.application import agent_use_cases

    order, _ = stream
    scope = {"agent_pk": order.agent_id, "allowed_account_ids": [order.account_id]}
    first = _event(order, event_type="UNKNOWN_VENDOR_A", status="FILLED")
    conflicting = {**first, "event_type": "UNKNOWN_VENDOR_B"}
    forwarded = []

    def forward(alerts):
        forwarded.extend(alerts)
        return ["monitor-id"], 0

    monkeypatch.setattr(agent_use_cases, "forward_operational_alerts", forward)
    use_case = agent_use_cases.ReportAgentEventsUseCase(DjangoBrokerExecutionRepository())
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            with pytest.raises(BrokerExecutionConflictError, match="first report"):
                use_case.execute(agent=scope, events=[first, conflicting])
            assert not forwarded
            if rollback_outer:
                transaction.set_rollback(True)
    assert order.broker_events.count() == (0 if rollback_outer else 1)
    if rollback_outer:
        assert forwarded == []
    else:
        assert [alert["metadata"]["code"] for alert in forwarded] == ["P0_ORDER_OUTCOME_UNKNOWN"]
        assert TradingControlModel.objects.get(account_id=7).kill_switch_active
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(BrokerExecutionConflictError, match="first report"):
                use_case.execute(agent=scope, events=[first, conflicting])
        assert len(forwarded) == 1


def test_successful_batch_preserves_aggregate_and_monitoring_result(stream, monkeypatch):
    from apps.broker_execution.application import agent_use_cases

    order, _ = stream
    scope = {"agent_pk": order.agent_id, "allowed_account_ids": [order.account_id]}
    event = _event(order, event_type="UNKNOWN_VENDOR_A", status="FILLED")
    forwarded = []

    def forward(alerts):
        forwarded.append(alerts)
        return ["monitor-id"], 0

    monkeypatch.setattr(agent_use_cases, "forward_operational_alerts", forward)
    result = agent_use_cases.ReportAgentEventsUseCase(DjangoBrokerExecutionRepository()).execute(
        agent=scope, events=[event, event]
    )
    assert result["accepted_count"] == result["duplicate_count"] == 1
    assert result["order_states"][0]["status"] == "RECONCILIATION_REQUIRED"
    assert forwarded == [result["alerts"]]
    assert result["task_monitor_alert_ids"] == ["monitor-id"]
    assert result["task_monitor_alert_failure_count"] == 0
