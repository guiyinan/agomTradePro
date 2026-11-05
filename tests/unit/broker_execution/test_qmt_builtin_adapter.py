"""Contract checks for the QMT built-in Python named-pipe bridge."""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

import qmt_agent.builtin_adapter as bridge_adapter
from qmt_agent import builtin_strategy
from qmt_agent.builtin_adapter import BuiltinPythonAdapter
from qmt_agent.config import AgentConfig
from qmt_agent.executor import QmtAgentExecutor
from qmt_agent.state_store import AgentStateStore


class _NativeRuntime:
    """In-memory native QMT functions and objects used by the strategy."""

    def __init__(self) -> None:
        self.account_id = "native-account"
        self.passorder_calls: list[tuple[object, ...]] = []
        self.cancel_calls: list[tuple[object, ...]] = []
        self.publish_order_on_submit = True
        self.cancel_result = True
        self.orders = [self._order()]
        self.trades = [self._trade()]

    def _order(self) -> SimpleNamespace:
        return SimpleNamespace(
            m_strOrderSysID="ORDER-1",
            m_strRemark="A" + "A" * 22,
            m_strInstrumentID="510300",
            m_strExchangeID="SH",
            m_nOffsetFlag=48,
            m_nVolumeTotalOriginal=100,
            m_nVolumeTraded=20,
            m_dLimitPrice=3.9,
            m_dTradedPrice=3.89,
            m_nOrderStatus=55,
            m_strErrorMsg="",
            m_strCancelInfo="",
            m_strInsertDate="20261016",
            m_strInsertTime="09:45:00",
        )

    def _trade(self) -> SimpleNamespace:
        return SimpleNamespace(
            m_strTradeID="TRADE-1",
            m_strOrderSysID="ORDER-1",
            m_strInstrumentID="510300",
            m_strExchangeID="SH",
            m_nVolume=20,
            m_dPrice=3.89,
            m_strTradeDate="20261016",
            m_strTradeTime="09:45:01",
        )

    def query(self, account_id: str, account_type: str, data_type: str) -> list[object]:
        assert account_id == self.account_id
        assert account_type.upper() == "STOCK"
        if data_type.upper() == "ACCOUNT":
            return [SimpleNamespace(m_dAvailable=1234.5, m_dBalance=5678.9)]
        if data_type.upper() == "POSITION":
            return [
                SimpleNamespace(
                    m_strInstrumentID="510300",
                    m_strExchangeID="SH",
                    m_nVolume=120,
                    m_nCanUseVolume=100,
                )
            ]
        if data_type.upper() == "ORDER":
            return list(self.orders)
        if data_type.upper() == "DEAL":
            return list(self.trades)
        raise AssertionError(data_type)

    def passorder(self, *args: object) -> None:
        self.passorder_calls.append(args)
        if self.publish_order_on_submit:
            order = self._order()
            order.m_strRemark = str(args[9])
            self.orders.append(order)

    def cancel(self, *args: object) -> bool:
        self.cancel_calls.append(args)
        return self.cancel_result


class _Context:
    def __init__(self) -> None:
        self.accounts: list[str] = []

    def set_account(self, account_id: str) -> None:
        self.accounts.append(account_id)

    def run_time(self, *args: object) -> None:
        return None


@pytest.fixture
def native_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[_NativeRuntime, str]]:
    runtime = _NativeRuntime()
    pipe_name = "agom_test_" + uuid.uuid4().hex
    monkeypatch.setattr(builtin_strategy, "PIPE_ADDRESS", rf"\\.\pipe\{pipe_name}")
    monkeypatch.setattr(builtin_strategy, "account", runtime.account_id, raising=False)
    monkeypatch.setattr(builtin_strategy, "get_trade_detail_data", runtime.query, raising=False)
    monkeypatch.setattr(builtin_strategy, "passorder", runtime.passorder, raising=False)
    monkeypatch.setattr(builtin_strategy, "cancel", runtime.cancel, raising=False)
    monkeypatch.setattr(builtin_strategy, "_requests", queue.Queue())
    monkeypatch.setattr(builtin_strategy, "_pending", {})
    monkeypatch.setattr(builtin_strategy, "_responses", {})
    monkeypatch.setattr(builtin_strategy, "_response_order", [])
    monkeypatch.setattr(builtin_strategy, "_submission_markers", {})
    context = _Context()
    builtin_strategy.init(context)
    stop = threading.Event()

    def run() -> None:
        while not stop.is_set():
            builtin_strategy._process_requests(context)
            time.sleep(0.005)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        yield runtime, pipe_name
    finally:
        stop.set()
        worker.join(timeout=2)
        builtin_strategy.stop(context)
        server_thread = builtin_strategy._server_thread
        if server_thread is not None:
            server_thread.join(timeout=2)


@pytest.fixture(autouse=True)
def xtquant_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("xtquant")
    module.xtconstant = SimpleNamespace(
        STOCK_BUY=23,
        STOCK_SELL=24,
        FIX_PRICE=11,
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
    monkeypatch.setitem(sys.modules, "xtquant", module)


def _adapter(pipe_name: str, runtime: _NativeRuntime) -> BuiltinPythonAdapter:
    return BuiltinPythonAdapter(
        userdata_path=Path("unused"),
        broker_account_id=runtime.account_id,
        pipe_name=pipe_name,
        bridge_timeout_seconds=2,
    )


def _order() -> dict[str, Any]:
    return {
        "client_order_id": "00000000-0000-0000-0000-000000000001",
        "asset_code": "510300.SH",
        "side": "BUY",
        "quantity": "100",
        "limit_price": "3.90",
    }


def test_builtin_adapter_queries_all_native_account_facts(
    native_runtime: tuple[_NativeRuntime, str],
) -> None:
    runtime, pipe_name = native_runtime
    adapter = _adapter(pipe_name, runtime)
    adapter.connect()
    snapshot = adapter.account_snapshot()

    assert adapter.health()["qmt_connected"] is True
    assert snapshot["cash_available"] == "1234.5"
    assert snapshot["total_asset"] == "5678.9"
    assert snapshot["positions"][0]["asset_code"] == "510300.SH"
    assert snapshot["orders"][0]["broker_order_id"] == "ORDER-1"
    assert snapshot["orders"][0]["status"] == "PARTIALLY_FILLED"
    assert snapshot["trades"][0]["broker_trade_id"] == "TRADE-1"


def test_builtin_adapter_submits_immediate_limit_order_with_native_passorder(
    native_runtime: tuple[_NativeRuntime, str],
) -> None:
    runtime, pipe_name = native_runtime
    adapter = _adapter(pipe_name, runtime)
    adapter.connect()
    result = adapter.submit_order(_order())

    assert result.accepted is True
    assert result.broker_order_id == "ORDER-1"
    call = runtime.passorder_calls[-1]
    assert call[:10] == (
        23,
        1101,
        runtime.account_id,
        "510300.SH",
        11,
        3.9,
        100,
        "AgomTradePro",
        2,
        "AAAAAAAAAAAAAAAAAAAAAAQ",
    )


def test_builtin_adapter_accepts_submission_while_order_id_is_pending(
    native_runtime: tuple[_NativeRuntime, str],
) -> None:
    runtime, pipe_name = native_runtime
    runtime.publish_order_on_submit = False
    adapter = _adapter(pipe_name, runtime)
    adapter.connect()
    result = adapter.submit_order(_order())

    assert result.accepted is True
    assert result.broker_order_id == ""
    assert len(runtime.passorder_calls) == 1


def test_builtin_adapter_cancels_by_native_order_id(
    native_runtime: tuple[_NativeRuntime, str],
) -> None:
    runtime, pipe_name = native_runtime
    adapter = _adapter(pipe_name, runtime)
    adapter.connect()

    assert adapter.cancel_order("ORDER-1") is True
    assert runtime.cancel_calls[-1][:3] == ("ORDER-1", runtime.account_id, "STOCK")


def test_native_strategy_does_not_execute_expired_submission(
    native_runtime: tuple[_NativeRuntime, str],
) -> None:
    runtime, _pipe_name = native_runtime
    request = {
        "schema": "agom-qmt-builtin-bridge.v1",
        "request_id": str(uuid.uuid4()),
        "operation": "submit",
        "not_after": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        "payload": {
            "account_id": runtime.account_id,
            "asset_code": "510300.SH",
            "side": 23,
            "quantity": 100,
            "price": 3.9,
            "strategy_name": "AgomTradePro",
            "order_remark": "AQAAAAAAAAAAAAAAAAAAAAE",
        },
    }

    with pytest.raises(ValueError, match="REQUEST_EXPIRED"):
        builtin_strategy._execute(request)

    assert runtime.passorder_calls == []


def test_native_submission_marker_prevents_duplicate_after_response_loss(
    native_runtime: tuple[_NativeRuntime, str],
) -> None:
    runtime, _pipe_name = native_runtime
    runtime.publish_order_on_submit = False
    request_id = str(uuid.uuid4())
    request = {
        "schema": "agom-qmt-builtin-bridge.v1",
        "request_id": request_id,
        "operation": "submit",
        "not_after": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        "payload": {
            "account_id": runtime.account_id,
            "asset_code": "510300.SH",
            "side": 23,
            "quantity": 100,
            "price": 3.9,
            "strategy_name": "AgomTradePro",
            "order_remark": "NEW-REMARK",
        },
    }

    first = builtin_strategy._execute(request)
    assert first["accepted"] is True
    with pytest.raises(RuntimeError, match="SUBMIT_OUTCOME_UNKNOWN"):
        builtin_strategy._execute(request)

    assert len(runtime.passorder_calls) == 1


def test_config_selects_builtin_python_and_named_pipe(tmp_path: Path) -> None:
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        json.dumps(
            {
                "agent_id": "agent-1",
                "server_url": "https://vps.example.com",
                "qmt_userdata_path": "userdata",
                "broker_account_id": "account-1",
                "system_account_id": 7,
                "qmt_trade_api": "builtin_python",
                "qmt_builtin_pipe_name": "custom_pipe",
            }
        ),
        encoding="utf-8",
    )

    config = AgentConfig.from_file(config_path)

    assert config.qmt_trade_api == "builtin_python"
    assert config.qmt_builtin_pipe_name == "custom_pipe"


def test_pipe_response_loss_replays_cached_submission_without_duplicate_order(
    native_runtime: tuple[_NativeRuntime, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, pipe_name = native_runtime
    adapter = _adapter(pipe_name, runtime)
    adapter.connect()
    original_client = bridge_adapter.PipeClient
    responses_to_drop = 1

    class _ResponseLossClient:
        def __init__(self, address: str) -> None:
            self.connection = original_client(address)

        def send_bytes(self, data: bytes) -> None:
            self.connection.send_bytes(data)

        def poll(self, timeout: float) -> bool:
            return self.connection.poll(timeout)

        def recv_bytes(self) -> bytes:
            nonlocal responses_to_drop
            data = self.connection.recv_bytes()
            if responses_to_drop:
                responses_to_drop -= 1
                raise RuntimeError("simulated response loss")
            return data

        def close(self) -> None:
            self.connection.close()

    request_id = uuid.uuid4()
    monkeypatch.setattr(bridge_adapter, "PipeClient", _ResponseLossClient)
    monkeypatch.setattr(bridge_adapter.uuid, "uuid4", lambda: request_id)

    with pytest.raises(RuntimeError, match="simulated response loss"):
        adapter.submit_order(_order())
    recovered = adapter.submit_order(_order())

    assert recovered.accepted is True
    assert recovered.broker_order_id == "ORDER-1"
    assert len(runtime.passorder_calls) == 1


def test_strategy_restart_recovers_uncertain_submission_without_replaying_passorder(
    native_runtime: tuple[_NativeRuntime, str],
    tmp_path: Path,
) -> None:
    runtime, pipe_name = native_runtime
    adapter = _adapter(pipe_name, runtime)
    adapter.connect()
    order = _order()
    state_path = tmp_path / "agent-state.sqlite3"
    state = AgentStateStore(state_path)
    state.mark_submitting(order["client_order_id"], order)
    adapter.submit_order(order)
    state.mark_result(order["client_order_id"], "RECONCILIATION_REQUIRED")
    state.close()

    context = builtin_strategy._runtime["context"]
    builtin_strategy.stop(context)
    server_thread = builtin_strategy._server_thread
    if server_thread is not None:
        server_thread.join(timeout=2)
    builtin_strategy._responses = {}
    builtin_strategy._response_order = []
    builtin_strategy._submission_markers = {}
    builtin_strategy._pending = {}
    builtin_strategy._requests = queue.Queue()
    builtin_strategy.init(context)

    class _RecoveryApi:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
            self.calls.append((path, payload))
            return {}

    restarted_adapter = _adapter(pipe_name, runtime)
    restarted_adapter.connect()
    restarted_state = AgentStateStore(state_path)
    api = _RecoveryApi()
    executor = QmtAgentExecutor(
        config=SimpleNamespace(),
        api=api,
        broker=restarted_adapter,
        state=restarted_state,
    )

    executor.recover_uncertain_submissions()

    recovered = restarted_state.get(order["client_order_id"])
    assert recovered is not None
    assert recovered["status"] == "PARTIALLY_FILLED"
    assert recovered["broker_order_id"] == "ORDER-1"
    assert api.calls[0][0] == "events/"
    assert api.calls[0][1]["events"][0]["payload"]["found"] is True
    assert len(runtime.passorder_calls) == 1
    restarted_state.close()


def test_builtin_adapter_reports_fill_and_cancel_with_idempotent_event_reads(
    native_runtime: tuple[_NativeRuntime, str],
) -> None:
    runtime, pipe_name = native_runtime
    runtime.orders = []
    runtime.trades = []
    adapter = _adapter(pipe_name, runtime)
    adapter.connect()
    adapter.submit_order(_order())
    runtime.trades = [runtime._trade()]

    first_events = adapter.poll_events()
    second_events = adapter.poll_events()
    assert adapter.cancel_order("ORDER-1") is True

    assert [event["event_type"] for event in first_events] == ["QMT_TRADE", "QMT_ORDER_STATUS"]
    assert first_events[0]["fill"]["broker_trade_id"] == "TRADE-1"
    assert first_events[1]["status"] == "PARTIALLY_FILLED"
    assert [event["event_id"] for event in second_events] == [
        event["event_id"] for event in first_events
    ]
    assert runtime.cancel_calls[-1][:3] == ("ORDER-1", runtime.account_id, "STOCK")
