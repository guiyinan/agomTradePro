"""Standalone Agent local idempotency and uncertainty behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qmt_agent.config import AgentConfig
from qmt_agent.executor import QmtAgentExecutor
from qmt_agent.fake_adapter import FakeQmtAdapter
from qmt_agent.health import run_preflight, run_qmt_read_probe
from qmt_agent.qmt_adapter import (
    _qmt_event_time,
    _qmt_order_status_map,
    decode_order_remark,
    encode_order_remark,
)
from qmt_agent.state_store import AgentStateStore


class _Api:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def post(self, endpoint: str, payload: dict):
        self.calls.append((endpoint, payload))
        return {}


def _order() -> dict:
    return {
        "client_order_id": "00000000-0000-0000-0000-000000000001",
        "account_id": 7,
        "asset_code": "510300.SH",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "100",
        "limit_price": "3.9",
        "lease_token": "lease-token",
    }


def test_heartbeat_publishes_agent_source_observation_time(tmp_path: Path) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=True,
    )
    api = _Api()
    broker = FakeQmtAdapter("success")
    broker.connect()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)

    executor.heartbeat()

    endpoint, payload = api.calls[0]
    assert endpoint == "heartbeat/"
    assert payload["contract_version"] == "1.0"
    assert payload["observed_at"].endswith("+00:00")
    state.close()


def test_agent_records_submitting_before_broker_and_does_not_duplicate(tmp_path: Path) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=False,
        enforce_trading_session=False,
    )
    api = _Api()
    broker = FakeQmtAdapter("success")
    broker.connect()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)
    executor.execute_order(_order())
    assert state.get(_order()["client_order_id"])["status"] == "SUBMITTED"
    assert [endpoint for endpoint, _payload in api.calls] == [
        "orders/submitting/",
        "events/",
    ]
    try:
        executor.execute_order(_order())
    except RuntimeError as exc:
        assert "idempotency" in str(exc)
    else:
        raise AssertionError("duplicate local submission should fail")
    state.close()


def test_dry_run_reports_idempotent_validation_without_qmt_submission(
    tmp_path: Path,
) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=True,
        enforce_trading_session=False,
    )
    api = _Api()
    broker = FakeQmtAdapter("success")
    broker.connect()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    order = {**_order(), "approval_digest": "approval-v1"}
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)

    executor.execute_order(order)
    executor.execute_order(order)

    assert broker.orders == {}
    assert state.get(order["client_order_id"]) is None
    first_event = api.calls[0][1]["events"][0]
    second_event = api.calls[1][1]["events"][0]
    assert first_event["event_type"] == "DRY_RUN_VALIDATED"
    assert first_event["status"] == ""
    assert first_event["event_id"] == second_event["event_id"]
    state.close()


def test_unknown_broker_outcome_requires_reconciliation(tmp_path: Path) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=False,
        enforce_trading_session=False,
    )
    api = _Api()
    broker = FakeQmtAdapter("unknown")
    broker.connect()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)
    executor.execute_order(_order())
    assert state.get(_order()["client_order_id"])["status"] == "RECONCILIATION_REQUIRED"
    assert api.calls[-1][1]["events"][0]["status"] == "RECONCILIATION_REQUIRED"
    state.close()


def test_restart_recovery_preserves_authoritative_final_broker_status(
    tmp_path: Path,
) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=False,
    )
    api = _Api()
    broker = FakeQmtAdapter("success")
    broker.connect()
    broker.orders[_order()["client_order_id"]] = {
        "broker_order_id": "FAKE-RECOVERED-1",
        "status": "FILLED",
        "asset_code": _order()["asset_code"],
        "side": _order()["side"],
        "quantity": _order()["quantity"],
        "limit_price": _order()["limit_price"],
    }
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    state.mark_submitting(_order()["client_order_id"], _order())
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)

    executor.recover_uncertain_submissions()

    assert api.calls[-1][1]["events"][0]["status"] == "FILLED"
    assert state.get(_order()["client_order_id"])["status"] == "FILLED"
    state.close()


def test_agent_reports_polled_broker_events(tmp_path: Path) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=False,
    )
    api = _Api()
    broker = FakeQmtAdapter("success")
    broker.poll_events = lambda: [
        {
            "event_id": "qmt-order-1",
            "client_order_id": _order()["client_order_id"],
            "event_type": "QMT_ORDER_STATUS",
            "status": "FILLED",
            "occurred_at": "2026-07-21T00:00:00+00:00",
        }
    ]
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)

    executor.sync_broker_events()

    assert api.calls == [
        (
            "events/",
            {
                "contract_version": "1.0",
                "events": broker.poll_events(),
            },
        )
    ]
    state.close()


def test_fake_adapter_reports_fill_before_final_order_status() -> None:
    broker = FakeQmtAdapter("filled")
    broker.connect()
    result = broker.submit_order(_order())

    events = broker.poll_events()

    assert result.accepted is True
    assert [event["event_type"] for event in events] == [
        "FAKE_TRADE",
        "FAKE_ORDER_STATUS",
    ]
    assert events[0]["status"] == ""
    assert events[1]["status"] == "FILLED"


def test_agent_refuses_disabled_tls_verification_for_remote_vps(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-1",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path,
        broker_account_id="broker-1",
        broker_account_type="STOCK",
        system_account_id=7,
        verify_tls=False,
    )

    with pytest.raises(ValueError, match="loopback"):
        config.validate()


def test_qmt_order_remark_round_trips_uuid_within_vendor_limit() -> None:
    client_order_id = "00000000-0000-0000-0000-000000000001"

    remark = encode_order_remark(client_order_id)

    assert len(remark.encode("ascii")) <= 24
    assert decode_order_remark(remark) == client_order_id
    assert decode_order_remark(client_order_id) == client_order_id
    assert decode_order_remark("foreign-strategy-order") is None


def test_agent_rejects_unimplemented_credit_account_semantics(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-1",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path,
        broker_account_id="broker-1",
        broker_account_type="CREDIT",
        system_account_id=7,
    )

    with pytest.raises(ValueError, match="STOCK accounts only"):
        config.validate()


def test_qmt_documented_order_states_are_not_silently_dropped() -> None:
    constants = SimpleNamespace(
        ORDER_UNREPORTED=48,
        ORDER_WAIT_REPORTING=49,
        ORDER_REPORTED=50,
        ORDER_REPORTED_CANCEL=51,
        ORDER_PARTSUCC_CANCEL=52,
        ORDER_PART_CANCEL=53,
        ORDER_CANCELED=54,
        ORDER_PART_SUCC=55,
        ORDER_SUCCEEDED=56,
        ORDER_JUNK=57,
        ORDER_UNKNOWN=255,
    )

    mapping = _qmt_order_status_map(constants)

    assert mapping[51] == "CANCEL_PENDING"
    assert mapping[53] == "CANCELED"
    assert mapping[57] == "BROKER_REJECTED"
    assert mapping[255] == "RECONCILIATION_REQUIRED"


def test_qmt_event_time_preserves_broker_timestamp() -> None:
    assert _qmt_event_time(0, "fallback") == "fallback"
    assert _qmt_event_time(1_700_000_000, "fallback").startswith(
        "2023-11-14T22:13:20"
    )


def test_agent_preflight_reports_supported_local_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qmt_userdata = tmp_path / "userdata_mini"
    qmt_userdata.mkdir()
    config = AgentConfig(
        agent_id="agent-1",
        server_url="https://vps.example.com",
        qmt_userdata_path=qmt_userdata,
        broker_account_id="broker-1",
        broker_account_type="STOCK",
        system_account_id=7,
        qmt_client_version="QMT-2026.1",
        xtquant_version="xtquant-2026.1",
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )
    monkeypatch.setattr("qmt_agent.health.platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "qmt_agent.health.importlib.util.find_spec", lambda _name: object()
    )

    report = run_preflight(config)

    assert report["python_supported"] is True
    assert report["xtquant_installed"] is True
    assert report["qmt_client_version_recorded"] is True
    assert report["xtquant_version_recorded"] is True
    assert report["ready"] is True


def test_qmt_read_probe_queries_all_facts_without_trading(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-read-probe",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path / "userdata_mini",
        broker_account_id="must-not-appear-in-report",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )
    broker = FakeQmtAdapter("success")

    report = run_qmt_read_probe(config, broker, adapter_name="fake")

    assert report["ready"] is True
    assert report["read_only"] is True
    assert report["submitted_order"] is False
    assert report["canceled_order"] is False
    assert report["checks"]["asset_query"] is True
    assert report["checks"]["positions_query"] is True
    assert report["checks"]["orders_query"] is True
    assert report["checks"]["trades_query"] is True
    assert "must-not-appear-in-report" not in str(report)


def test_qmt_read_probe_fails_closed_on_disconnect(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-read-probe-failure",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path / "userdata_mini",
        broker_account_id="broker-1",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )

    report = run_qmt_read_probe(
        config,
        FakeQmtAdapter("disconnect"),
        adapter_name="fake",
    )

    assert report["ready"] is False
    assert report["checks"] == {
        "qmt_connected": False,
        "failure_type": "RuntimeError",
        "failure_code": "BROKER_READ_FAILED",
    }


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        ("QMT trader connection failed", "QMT_CONNECTION_FAILED"),
        ("QMT account subscription failed", "QMT_ACCOUNT_SUBSCRIPTION_FAILED"),
    ],
)
def test_qmt_read_probe_reports_secret_free_failure_stage(
    tmp_path: Path,
    message: str,
    expected_code: str,
) -> None:
    class FailingBroker(FakeQmtAdapter):
        def connect(self) -> None:
            raise RuntimeError(message)

    config = AgentConfig(
        agent_id="agent-read-probe-stage",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path / "userdata_mini",
        broker_account_id="must-not-appear-in-report",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )

    report = run_qmt_read_probe(config, FailingBroker("success"))

    assert report["ready"] is False
    assert report["checks"]["failure_code"] == expected_code
    assert "must-not-appear-in-report" not in str(report)
    assert message not in str(report)


def test_qmt_read_probe_detects_vendor_server_authorization_denial(
    tmp_path: Path,
) -> None:
    class FailingBroker(FakeQmtAdapter):
        def connect(self) -> None:
            raise RuntimeError("QMT trader connection failed")

    userdata = tmp_path / "userdata"
    log_dir = userdata / "log"
    log_dir.mkdir(parents=True)
    (log_dir / "XtClient_20260722.log").write_text(
        "The XtQuantServer is not allowed to start.\n",
        encoding="utf-8",
    )
    config = AgentConfig(
        agent_id="agent-server-denial",
        server_url="https://vps.example.com",
        qmt_userdata_path=userdata,
        broker_account_id="must-not-appear-in-report",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )

    report = run_qmt_read_probe(config, FailingBroker("success"))

    assert report["ready"] is False
    assert report["checks"]["failure_code"] == "QMT_SERVER_NOT_ALLOWED"
    assert "must-not-appear-in-report" not in str(report)
    assert "XtQuantServer" not in str(report)


def test_real_qmt_read_probe_requires_recorded_version_matrix(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-version-probe",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path / "userdata_mini",
        broker_account_id="broker-1",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )

    report = run_qmt_read_probe(
        config,
        FakeQmtAdapter("success"),
        adapter_name="xtquant",
    )

    assert report["ready"] is False
    assert report["checks"]["qmt_client_version_recorded"] is False
    assert report["checks"]["xtquant_version_recorded"] is False
