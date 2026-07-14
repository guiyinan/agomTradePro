"""SDK contracts for authenticated realtime WebSocket streaming."""

import json

import pytest

from agomtradepro import AgomTradeProClient
from agomtradepro.realtime_stream import RealtimeStream, RealtimeStreamClosedError


class FakeConnection:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent: list[dict] = []
        self.closed = False

    def recv(self):
        item = self.incoming.pop(0)
        if isinstance(item, Exception):
            raise item
        return json.dumps(item)

    def send(self, value: str) -> None:
        self.sent.append(json.loads(value))

    def close(self) -> None:
        self.closed = True


def test_realtime_stream_uses_header_auth_subscribes_and_yields_typed_envelopes() -> None:
    connection = FakeConnection(
        [
            {"type": "connection.ready", "subscriptions": []},
            {
                "type": "subscription.updated",
                "request_id": "ignored-by-test",
                "subscriptions": ["510300.SH"],
            },
            {"type": "price.update", "asset_code": "510300.SH", "price": "3.6"},
        ]
    )
    calls = []

    def factory(url, **kwargs):
        calls.append((url, kwargs))
        return connection

    stream = RealtimeStream(
        base_url="https://trade.example/base/",
        authorization="Token formal-key",
        asset_codes=["510300.sh"],
        connection_factory=factory,
    )
    with stream as connected:
        assert next(connected).type == "connection.ready"
        assert next(connected).type == "subscription.updated"
        price = next(connected)
        assert price.type == "price.update"
        assert price.payload["price"] == "3.6"
        connected.ping("heartbeat-1")

    assert calls == [
        (
            "wss://trade.example/ws/realtime/prices/",
            {"additional_headers": {"Authorization": "Token formal-key"}},
        )
    ]
    assert connection.sent[0]["action"] == "subscribe"
    assert connection.sent[0]["asset_codes"] == ["510300.SH"]
    assert connection.sent[0]["request_id"]
    assert connection.sent[1] == {"action": "ping", "request_id": "heartbeat-1"}
    assert connection.closed is True


def test_client_builds_stream_from_formal_token_configuration() -> None:
    client = AgomTradeProClient(base_url="http://localhost:8000", api_token="abc")

    stream = client.realtime_stream(["510300.SH"])

    assert stream.base_url == "http://localhost:8000"
    assert stream.authorization == "Token abc"
    assert stream.asset_codes == ("510300.SH",)


def test_realtime_stream_raises_typed_close_error() -> None:
    class FakeClosedError(Exception):
        code = 1013

    connection = FakeConnection([FakeClosedError("retry later")])
    stream = RealtimeStream(
        base_url="http://localhost:8000",
        authorization="Token key",
        connection_factory=lambda *args, **kwargs: connection,
    )
    stream.__enter__()

    with pytest.raises(RealtimeStreamClosedError) as exc_info:
        next(stream)

    assert exc_info.value.code == 1013
