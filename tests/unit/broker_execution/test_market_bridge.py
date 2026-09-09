"""Durable market worker and pinned credential transport regression."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from qmt_agent.api_client import AgentApiError
from qmt_agent.bridge_client import BridgeClient, _NoRedirect, protect_token, validate_server_url
from qmt_agent.bridge_worker import BridgeWorker, XtDataSource


class Source:
    def __init__(self):
        self.calls = 0

    def quotes(self, assets):
        self.calls += 1
        return [{"asset_code": assets[0], "price": 3.5,
                 "observed_at": (datetime.now(UTC)-timedelta(seconds=1)).isoformat()}]


class Transport:
    def __init__(self):
        self.enabled = True
        self.lose_ack = True
        self.batches = []

    def post(self, operation, payload):
        if operation == "plan":
            return {"enabled": self.enabled, "assets": ["510300.SH"], "poll_seconds": 10}
        self.batches.append(payload)
        if self.lose_ack:
            raise AgentApiError("ack lost")
        return {"batch_id": payload["batch_id"], "outcome": "success", "failed": 0,
                "succeeded": len(payload["samples"]), "stored": 1}


def test_market_outbox_survives_lost_ack_restart_without_retimestamping(tmp_path):
    transport, source = Transport(), Source()
    worker = BridgeWorker(tmp_path, transport, source)
    with pytest.raises(AgentApiError):
        worker.run_once()
    worker.close()
    transport.lose_ack = False
    worker = BridgeWorker(tmp_path, transport, source)
    assert worker.run_once()["stored"] == 1
    assert transport.batches[0] == transport.batches[1]
    assert source.calls == 1
    assert worker.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    worker.close()


def test_market_pause_never_touches_trading_state_or_collects(tmp_path):
    trading = tmp_path / "agent-state.sqlite3"
    trading.write_bytes(b"untouched trading state")
    transport, source = Transport(), Source()
    transport.enabled = False
    worker = BridgeWorker(tmp_path, transport, source)
    assert worker.run_once()["outcome"] == "blocked"
    assert source.calls == 0
    transport.enabled = True
    (tmp_path / "PAUSE_MARKET").touch()
    assert worker.run_once()["outcome"] == "blocked"
    assert trading.read_bytes() == b"untouched trading state"
    worker.close()


def test_only_one_market_worker_can_own_a_state_directory(tmp_path):
    transport, source = Transport(), Source()
    worker = BridgeWorker(tmp_path, transport, source)
    with pytest.raises(AgentApiError):
        BridgeWorker(tmp_path, transport, source)
    worker.close()
    replacement = BridgeWorker(tmp_path, transport, source)
    replacement.close()


@pytest.mark.parametrize("url", ["http://127.0.0.1.attacker.example", "https://user:pass@example.com",
                                 "https://example.com/path", "https://example.com?x=y"])
def test_bridge_rejects_ambiguous_or_insecure_server_origins(url):
    with pytest.raises(ValueError):
        validate_server_url(url)


def test_bridge_redirect_never_forwards_credentials():
    with pytest.raises(AgentApiError):
        _NoRedirect().redirect_request(None, None, 302, "found", {}, "https://other.example")


def test_pairing_persists_dpapi_ciphertext_only(tmp_path, monkeypatch):
    client = BridgeClient("https://server.example")
    monkeypatch.setattr(client, "post", lambda *a, **k: {"server_url": "https://server.example",
        "agent_id": "local-qmt", "binding_id": "binding", "token": "secret-market-token"})
    monkeypatch.setattr("qmt_agent.bridge_client.protect_token", lambda value: "encrypted")
    client.pair("one-time-code", "local-qmt", tmp_path)
    content = (tmp_path / "bridge.json").read_text()
    assert "secret-market-token" not in content
    assert json.loads(content)["protected_token"] == "encrypted"
    with pytest.raises(AgentApiError):
        client.pair("other-code", "local-qmt", tmp_path)


def test_windows_dpapi_roundtrip():
    import os
    if os.name != "nt":
        pytest.skip("Windows credential store")
    encrypted = protect_token("test-only-bridge-secret")
    assert "test-only-bridge-secret" not in encrypted
    assert protect_token(encrypted, decrypt=True) == "test-only-bridge-secret"


def test_xtdata_reconnect_and_missing_open_prices(monkeypatch):
    class SDK:
        def __init__(self):
            self.fail = True
            self.subscribed = 0

        def subscribe_quote(self, asset, period):
            self.subscribed += 1
            return self.subscribed

        def get_full_tick(self, assets):
            if self.fail:
                self.fail = False
                raise RuntimeError("disconnected")
            return {assets[0]: {"time": int(datetime.now(UTC).timestamp()*1000),
                                "lastPrice": 3.5, "open": 0, "volume": 0}}

    sdk = SDK()
    monkeypatch.setattr("qmt_agent.bridge_worker.importlib.import_module", lambda name: sdk)
    source = XtDataSource()
    with pytest.raises(AgentApiError):
        source.quotes(["510300.SH"])
    quote = source.quotes(["510300.SH"])[0]
    assert sdk.subscribed == 2
    assert quote["price"] == "3.5" and quote["open"] is None and quote["volume"] == "0"


def test_xtdata_daily_history_keeps_source_date_and_skips_empty_bars(monkeypatch):
    from types import SimpleNamespace
    day = (datetime.now(UTC)-timedelta(days=2)).date()
    bar = {"open": 3.4, "high": 3.6, "low": 3.3, "close": 3.5, "volume": 2, "amount": 700}
    frame = SimpleNamespace(iterrows=lambda: iter([(day.strftime("%Y%m%d"), bar),
                                                   (day.strftime("%Y%m%d"), dict(bar, close=0))]))
    sdk = SimpleNamespace(download_history_data=lambda *a, **k: None,
                          get_market_data_ex=lambda *a, **k: {"510300.SH": frame})
    monkeypatch.setattr("qmt_agent.bridge_worker.importlib.import_module", lambda name: sdk)
    rows = XtDataSource().bars(["510300.SH"], day.isoformat(), day.isoformat())
    assert len(rows) == 1
    assert rows[0]["bar_date"] == day.isoformat()
    assert rows[0]["observed_at"].startswith(day.isoformat())
    assert rows[0]["price"] == "3.5" and rows[0]["volume"] == "2"
