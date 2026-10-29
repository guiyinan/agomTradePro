"""Durable market worker and pinned credential transport regression."""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

import qmt_agent.bridge_worker as bridge_worker_module
from qmt_agent.api_client import AgentApiError
from qmt_agent.bridge_client import BridgeClient, _NoRedirect, protect_token, validate_server_url
from qmt_agent.bridge_worker import BridgeWorker, XtDataSource


class Source:
    def __init__(self):
        self.calls = 0

    def quotes(self, assets):
        self.calls += 1
        return [
            {
                "asset_code": assets[0],
                "price": 3.5,
                "observed_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            }
        ]


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
        return {
            "batch_id": payload["batch_id"],
            "outcome": "success",
            "failed": 0,
            "succeeded": len(payload["samples"]),
            "stored": 1,
        }


_MISSING = object()


def _daily_bar(*, suspend_flag=_MISSING, close=3.5, open_price=3.4):
    row = {
        "open": open_price,
        "high": 3.6,
        "low": 3.3,
        "close": close,
        "volume": 2,
        "amount": 700,
    }
    if suspend_flag is not _MISSING:
        row["suspendFlag"] = suspend_flag
    return row


class HistoryFrame:
    def __init__(self, rows):
        self.rows = rows

    def iterrows(self):
        return iter(self.rows)


class HistorySdk:
    def __init__(self, frames):
        self.frames = frames
        self.downloads = []
        self.reads = []

    def download_history_data(self, asset, **options):
        self.downloads.append((asset, options))

    def get_market_data_ex(self, fields, assets, **options):
        self.reads.append((fields, assets, options))
        return {asset: self.frames[asset] for asset in assets if asset in self.frames}


class HistoryTransport:
    def __init__(self, assets):
        self.assets = assets
        self.batches = []
        self.fail_daily_status = None

    def post(self, operation, payload):
        if operation == "plan":
            return {"enabled": True, "assets": self.assets, "poll_seconds": 10}
        self.batches.append(json.loads(json.dumps(payload)))
        if payload.get("kind") == "daily_status" and self.fail_daily_status:
            raise AgentApiError(self.fail_daily_status)
        return {
            "batch_id": payload["batch_id"],
            "outcome": "success",
            "failed": 0,
            "succeeded": len(payload["samples"]),
            "stored": 1,
        }


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


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1.attacker.example",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com?x=y",
    ],
)
def test_bridge_rejects_ambiguous_or_insecure_server_origins(url):
    with pytest.raises(ValueError):
        validate_server_url(url)


def test_bridge_redirect_never_forwards_credentials():
    with pytest.raises(AgentApiError):
        _NoRedirect().redirect_request(None, None, 302, "found", {}, "https://other.example")


def test_pairing_persists_dpapi_ciphertext_only(tmp_path, monkeypatch):
    client = BridgeClient("https://server.example")
    monkeypatch.setattr(
        client,
        "post",
        lambda *a, **k: {
            "server_url": "https://server.example",
            "agent_id": "local-qmt",
            "binding_id": "binding",
            "token": "secret-market-token",
        },
    )
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
            return {
                assets[0]: {
                    "time": int(datetime.now(UTC).timestamp() * 1000),
                    "lastPrice": 3.5,
                    "open": 0,
                    "volume": 0,
                }
            }

    sdk = SDK()
    monkeypatch.setattr("qmt_agent.bridge_worker.importlib.import_module", lambda name: sdk)
    source = XtDataSource()
    with pytest.raises(AgentApiError):
        source.quotes(["510300.SH"])
    quote = source.quotes(["510300.SH"])[0]
    assert sdk.subscribed == 2
    assert quote["price"] == "3.5" and quote["open"] is None and quote["volume"] == "0"


def test_xtdata_daily_history_keeps_source_date_and_skips_empty_bars(monkeypatch):
    day = (datetime.now(UTC) - timedelta(days=2)).date()
    empty_day = day + timedelta(days=1)
    bar = {"open": 3.4, "high": 3.6, "low": 3.3, "close": 3.5, "volume": 2, "amount": 700}
    frame = SimpleNamespace(
        iterrows=lambda: iter(
            [
                (day.strftime("%Y%m%d"), dict(bar, suspendFlag=0)),
                (empty_day.strftime("%Y%m%d"), dict(bar, close=0, suspendFlag=1)),
            ]
        )
    )
    sdk = SimpleNamespace(
        downloads=[],
        reads=[],
        download_history_data=lambda *a, **k: sdk.downloads.append((a, k)),
        get_market_data_ex=lambda *a, **k: sdk.reads.append((a, k)) or {"510300.SH": frame},
    )
    monkeypatch.setattr("qmt_agent.bridge_worker.importlib.import_module", lambda name: sdk)
    rows = XtDataSource().bars(["510300.SH"], day.isoformat(), empty_day.isoformat())
    assert len(rows) == 1
    assert rows[0]["bar_date"] == day.isoformat()
    assert rows[0]["observed_at"].startswith(day.isoformat())
    assert rows[0]["price"] == "3.5" and rows[0]["volume"] == "2"
    assert len(sdk.reads) == 1
    fields, assets = sdk.reads[0][0][:2]
    assert fields == ["open", "high", "low", "close", "volume", "amount", "suspendFlag"]
    assert assets == ["510300.SH"]


def test_xtdata_daily_history_emits_statuses_and_bars_from_one_native_read(monkeypatch, caplog):
    start = date.today() - timedelta(days=12)
    flags = [np.int64(-1), -0.0, 1.0, None, 2, True, float("nan")]
    days = [start + timedelta(days=offset) for offset in range(len(flags))]
    frame = HistoryFrame(
        [
            (day.strftime("%Y%m%d"), _daily_bar(suspend_flag=flag))
            for day, flag in zip(days, flags, strict=True)
        ]
    )
    sdk = HistorySdk({"510300.SH": frame})
    monkeypatch.setattr("qmt_agent.bridge_worker.importlib.import_module", lambda name: sdk)

    with caplog.at_level(logging.WARNING, logger="qmt_agent.bridge_worker"):
        result = XtDataSource().daily_history(
            ["510300.SH"], start.isoformat(), days[-1].isoformat()
        )

    assert [row["suspend_flag"] for row in result.statuses] == [-1, 0, 1, None, None, None, None]
    assert [row["bar_date"] for row in result.statuses] == [day.isoformat() for day in days]
    assert all(row["asset_code"] == "510300.SH" for row in result.statuses)
    assert caplog.text.count("QMT returned an unknown suspendFlag") == 3
    assert len(result.bars) == len(flags)
    assert sdk.downloads == [
        (
            "510300.SH",
            {
                "period": "1d",
                "start_time": start.strftime("%Y%m%d"),
                "end_time": days[-1].strftime("%Y%m%d"),
            },
        )
    ]
    assert len(sdk.reads) == 1
    fields, assets, options = sdk.reads[0]
    assert fields == ["open", "high", "low", "close", "volume", "amount", "suspendFlag"]
    assert assets == ["510300.SH"]
    assert options == {
        "period": "1d",
        "start_time": start.strftime("%Y%m%d"),
        "end_time": days[-1].strftime("%Y%m%d"),
        "dividend_type": "none",
        "fill_data": False,
    }


def test_xtdata_daily_history_keeps_status_without_a_usable_price_bar(monkeypatch):
    day = date.today() - timedelta(days=3)
    frame = HistoryFrame([(day.strftime("%Y%m%d"), _daily_bar(suspend_flag=1, open_price=0))])
    sdk = HistorySdk({"510300.SH": frame})
    monkeypatch.setattr("qmt_agent.bridge_worker.importlib.import_module", lambda name: sdk)

    result = XtDataSource().daily_history(["510300.SH"], day.isoformat(), day.isoformat())

    assert result.bars == ()
    assert result.statuses == (
        {"asset_code": "510300.SH", "bar_date": day.isoformat(), "suspend_flag": 1},
    )


def test_xtdata_daily_history_keeps_missing_flag_unknown_and_empty_result_empty(monkeypatch):
    day = date.today() - timedelta(days=4)
    frame = HistoryFrame([(day.strftime("%Y%m%d"), _daily_bar(close=0))])
    sdk = HistorySdk({"510300.SH": frame})
    monkeypatch.setattr("qmt_agent.bridge_worker.importlib.import_module", lambda name: sdk)
    source = XtDataSource()

    result = source.daily_history(["510300.SH"], day.isoformat(), day.isoformat())
    assert result.statuses == (
        {"asset_code": "510300.SH", "bar_date": day.isoformat(), "suspend_flag": None},
    )
    assert result.bars == ()

    sdk.frames.clear()
    empty = source.daily_history(["510300.SH"], day.isoformat(), day.isoformat())
    assert empty.bars == () and empty.statuses == ()


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date.today().isoformat(), date.today().isoformat()),
        (
            (date.today() - timedelta(days=34)).isoformat(),
            (date.today() - timedelta(days=2)).isoformat(),
        ),
        (
            (date.today() - timedelta(days=2)).isoformat(),
            (date.today() - timedelta(days=3)).isoformat(),
        ),
    ],
)
def test_xtdata_daily_history_rejects_uncompleted_or_invalid_range_without_sdk_read(
    monkeypatch, start, end
):
    sdk = HistorySdk({})
    monkeypatch.setattr("qmt_agent.bridge_worker.importlib.import_module", lambda name: sdk)
    source = XtDataSource()

    with pytest.raises(ValueError):
        source.daily_history(["510300.SH"], start, end)
    assert sdk.downloads == [] and sdk.reads == []


@pytest.mark.parametrize(
    ("machine_day", "utc_now", "end", "accepted"),
    [
        (date(2026, 10, 28), datetime(2026, 10, 27, 15, 30, tzinfo=UTC), date(2026, 10, 27), False),
        (date(2026, 10, 27), datetime(2026, 10, 27, 16, 30, tzinfo=UTC), date(2026, 10, 27), True),
    ],
)
def test_daily_history_range_uses_china_date_not_machine_timezone(
    monkeypatch, machine_day, utc_now, end, accepted
):
    class MachineDate:
        @staticmethod
        def fromisoformat(value):
            return date.fromisoformat(value)

        @classmethod
        def today(cls):
            return machine_day

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_now.astimezone(tz) if tz is not None else utc_now.replace(tzinfo=None)

    monkeypatch.setattr(bridge_worker_module, "date", MachineDate)
    monkeypatch.setattr(bridge_worker_module, "datetime", FrozenDateTime)

    if accepted:
        start_day, end_day = bridge_worker_module._completed_history_range(
            "2026-10-26", end.isoformat()
        )
        assert (start_day, end_day) == (date(2026, 10, 26), end)
    else:
        with pytest.raises(ValueError):
            bridge_worker_module._completed_history_range("2026-10-26", end.isoformat())


def test_daily_status_worker_rechecks_range_against_actual_collected_at(tmp_path, monkeypatch):
    instants = [
        datetime(2026, 10, 28, 16, 30, tzinfo=UTC),
        datetime(2026, 10, 28, 15, 30, tzinfo=UTC),
    ]

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = instants.pop(0)
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    class MachineDate:
        @staticmethod
        def fromisoformat(value):
            return date.fromisoformat(value)

        @classmethod
        def today(cls):
            return date(2026, 10, 29)

    monkeypatch.setattr(bridge_worker_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(bridge_worker_module, "date", MachineDate)
    day = date(2026, 10, 28)
    result = SimpleNamespace(
        bars=(),
        statuses=({"asset_code": "510300.SH", "bar_date": day.isoformat(), "suspend_flag": 1},),
    )

    class DailySource(Source):
        def daily_history(self, assets, start, end):
            return result

    worker = BridgeWorker(tmp_path, HistoryTransport(["510300.SH"]), DailySource())
    with pytest.raises(AgentApiError, match="China-local collection date"):
        worker.run_once(start=day.isoformat(), end=day.isoformat())

    assert worker.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    worker.close()


def test_xtdata_daily_history_rejects_out_of_range_and_conflicting_duplicate_dates(monkeypatch):
    day = date.today() - timedelta(days=5)
    sdk = HistorySdk(
        {
            "510300.SH": HistoryFrame(
                [
                    (
                        (day + timedelta(days=1)).strftime("%Y%m%d"),
                        _daily_bar(suspend_flag=0),
                    )
                ]
            )
        }
    )
    monkeypatch.setattr("qmt_agent.bridge_worker.importlib.import_module", lambda name: sdk)
    source = XtDataSource()

    with pytest.raises(AgentApiError):
        source.daily_history(["510300.SH"], day.isoformat(), day.isoformat())

    sdk.frames["510300.SH"] = HistoryFrame(
        [
            (day.strftime("%Y%m%d"), _daily_bar(suspend_flag=0)),
            (day.strftime("%Y%m%d"), _daily_bar(suspend_flag=1)),
        ]
    )
    with pytest.raises(AgentApiError):
        source.daily_history(["510300.SH"], day.isoformat(), day.isoformat())


def test_daily_history_worker_persists_separate_status_and_legacy_bar_batches(tmp_path):
    day = date.today() - timedelta(days=6)
    start, end = day.isoformat(), day.isoformat()
    bar = {
        "asset_code": "510300.SH",
        "bar_date": start,
        "observed_at": f"{start}T00:00:00+00:00",
        "price": "3.5",
        "open": "3.4",
        "high": "3.6",
        "low": "3.3",
        "volume": "2",
        "amount": "700",
    }
    status = {"asset_code": "510300.SH", "bar_date": start, "suspend_flag": None}
    result = SimpleNamespace(bars=(bar,), statuses=(status,))

    class DailySource(Source):
        def __init__(self):
            super().__init__()
            self.bar_calls = 0
            self.daily_calls = []

        def bars(self, assets, request_start, request_end):
            self.bar_calls += 1
            return [bar]

        def daily_history(self, assets, request_start, request_end):
            self.daily_calls.append((assets, request_start, request_end))
            return result

    source = DailySource()
    transport = HistoryTransport(["510300.SH"])
    worker = BridgeWorker(tmp_path, transport, source)
    outcome = worker.run_once(start=start, end=end)

    assert outcome["outcome"] == "success"
    assert source.daily_calls == [(["510300.SH"], start, end)]
    assert source.bar_calls == 0
    pending = [
        json.loads(row[0]) for row in worker.db.execute("SELECT payload FROM outbox ORDER BY rowid")
    ]
    assert [payload["kind"] for payload in pending] == ["daily_status"]
    assert transport.batches[0]["kind"] == "bar"
    bar_payload = transport.batches[0]
    assert set(bar_payload) == {"batch_id", "kind", "collected_at", "samples"}
    status_payload = pending[0]
    assert set(status_payload) == {
        "batch_id",
        "kind",
        "schema_version",
        "collected_at",
        "request_start",
        "request_end",
        "samples",
    }
    assert status_payload["kind"] == "daily_status"
    assert status_payload["schema_version"] == "qmt-native-daily-status.v1"
    assert status_payload["request_start"] == start and status_payload["request_end"] == end
    assert status_payload["samples"] == [status]
    assert datetime.fromisoformat(status_payload["collected_at"]).tzinfo is not None
    worker.close()


@pytest.mark.parametrize("rejection", ["ack lost", "old server rejected daily_status"])
def test_daily_status_rejection_survives_restart_with_same_payload_and_identity(
    tmp_path, rejection
):
    day = date.today() - timedelta(days=7)
    start = end = day.isoformat()
    bar = {"asset_code": "510300.SH", "bar_date": start, "price": "3.5"}
    status = {"asset_code": "510300.SH", "bar_date": start, "suspend_flag": 1}
    result = SimpleNamespace(bars=(bar,), statuses=(status,))

    class DailySource(Source):
        def __init__(self):
            super().__init__()
            self.daily_calls = 0

        def bars(self, assets, request_start, request_end):
            return [bar]

        def daily_history(self, assets, request_start, request_end):
            self.daily_calls += 1
            return result

    source = DailySource()
    transport = HistoryTransport(["510300.SH"])
    worker = BridgeWorker(tmp_path, transport, source)
    worker.run_once(start=start, end=end)
    original = json.loads(worker.db.execute("SELECT payload FROM outbox").fetchone()[0])
    transport.fail_daily_status = rejection
    with pytest.raises(AgentApiError):
        worker.run_once(start=start, end=end)
    retained = json.loads(worker.db.execute("SELECT payload FROM outbox").fetchone()[0])
    assert retained == original
    assert transport.batches[-1] == original
    worker.close()

    transport.fail_daily_status = None
    worker = BridgeWorker(tmp_path, transport, source)
    assert worker.run_once(start=start, end=end)["stored"] == 1
    assert transport.batches[-1] == original
    assert source.daily_calls == 1
    assert worker.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    worker.close()


def test_daily_status_outbox_batches_at_500_samples(tmp_path):
    start_day = date.today() - timedelta(days=40)
    end_day = start_day + timedelta(days=30)
    assets = [f"A{index:03d}.SH" for index in range(17)]
    statuses = tuple(
        {
            "asset_code": asset,
            "bar_date": (start_day + timedelta(days=offset)).isoformat(),
            "suspend_flag": offset % 3 - 1,
        }
        for asset in assets
        for offset in range(30)
    )[:501]
    result = SimpleNamespace(bars=(), statuses=statuses)

    class DailySource(Source):
        def daily_history(self, requested_assets, request_start, request_end):
            return result

        def bars(self, requested_assets, request_start, request_end):
            raise AssertionError("daily_history must supply the single combined read")

    transport = HistoryTransport(assets)
    worker = BridgeWorker(tmp_path, transport, DailySource())
    worker.run_once(start=start_day.isoformat(), end=end_day.isoformat())

    assert len(transport.batches[0]["samples"]) == 500
    assert transport.batches[0]["kind"] == "daily_status"
    rest = json.loads(worker.db.execute("SELECT payload FROM outbox").fetchone()[0])
    assert rest["kind"] == "daily_status" and rest["samples"] == list(statuses[500:])
    worker.close()


def test_unknown_market_outbox_kind_is_not_posted_or_deleted(tmp_path):
    transport, source = HistoryTransport(["510300.SH"]), Source()
    worker = BridgeWorker(tmp_path, transport, source)
    batch_id = "unknown-kind-batch"
    payload = {"batch_id": batch_id, "kind": "mystery", "samples": []}
    with worker.db:
        worker.db.execute("INSERT INTO outbox VALUES (?,?)", (batch_id, json.dumps(payload)))

    with pytest.raises(AgentApiError):
        worker.run_once()
    assert transport.batches == []
    assert worker.db.execute("SELECT id,payload FROM outbox").fetchone() == (
        batch_id,
        json.dumps(payload),
    )
    worker.close()


def test_legacy_bar_only_source_keeps_original_bar_payload(tmp_path):
    start = end = (date.today() - timedelta(days=2)).isoformat()
    row = {"asset_code": "510300.SH", "bar_date": start, "price": "3.5"}

    class LegacyBarSource(Source):
        def bars(self, assets, request_start, request_end):
            return [row]

    transport, source = HistoryTransport(["510300.SH"]), LegacyBarSource()
    worker = BridgeWorker(tmp_path, transport, source)
    worker.run_once(start=start, end=end)

    assert transport.batches[0]["kind"] == "bar"
    assert set(transport.batches[0]) == {"batch_id", "kind", "collected_at", "samples"}
    worker.close()
