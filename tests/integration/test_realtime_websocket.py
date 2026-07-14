"""Authenticated WebSocket contracts for realtime prices."""

from functools import wraps
from http.cookies import SimpleCookie

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.account.infrastructure.models import UserAccessTokenModel
from apps.realtime.infrastructure.models import PriceSubscriptionModel
from core.asgi import build_application

TEST_CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}


def _sync_async_test(async_test):
    @wraps(async_test)
    def wrapper(*args, **kwargs):
        return async_to_sync(async_test)(*args, **kwargs)

    return wrapper


@pytest.fixture
def websocket_identities(db):
    user_model = get_user_model()
    owner = user_model.objects.create_user(username="ws-owner", password="secret")
    other = user_model.objects.create_user(username="ws-other", password="secret")
    _, owner_key = UserAccessTokenModel.create_token(user=owner, name="ws-owner")
    _, other_key = UserAccessTokenModel.create_token(user=other, name="ws-other")
    return owner, owner_key, other, other_key


@pytest.fixture
def websocket_session_cookie(websocket_identities) -> str:
    owner, _, _, _ = websocket_identities
    client = Client()
    client.force_login(owner)
    cookie: SimpleCookie = client.cookies
    return cookie["sessionid"].value


def _headers(token: str | None = None, origin: str = "http://testserver"):
    headers = [(b"origin", origin.encode("ascii"))]
    if token is not None:
        headers.append((b"authorization", f"Token {token}".encode("ascii")))
    return headers


def _seed_subscription_limit(owner_id: int) -> None:
    PriceSubscriptionModel.objects.bulk_create(
        [
            PriceSubscriptionModel(owner_id=owner_id, asset_code=f"LIMIT{i:03d}")
            for i in range(100)
        ]
    )


@pytest.mark.django_db(transaction=True)
@override_settings(
    REALTIME_WEBSOCKET_ENABLED=True,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    ALLOWED_HOSTS=["testserver", "localhost"],
)
@_sync_async_test
async def test_websocket_rejects_anonymous_query_token_and_bad_origin(
    websocket_identities,
) -> None:
    _, owner_key, _, _ = websocket_identities
    application = build_application()

    anonymous = WebsocketCommunicator(
        application,
        "/ws/realtime/prices/",
        headers=_headers(),
    )
    assert await anonymous.connect() == (False, 4401)

    query_token = WebsocketCommunicator(
        application,
        f"/ws/realtime/prices/?token={owner_key}",
        headers=_headers(),
    )
    assert await query_token.connect() == (False, 4401)

    bad_origin = WebsocketCommunicator(
        application,
        "/ws/realtime/prices/",
        headers=_headers(owner_key, origin="https://evil.example"),
    )
    connected, _ = await bad_origin.connect()
    assert connected is False


@pytest.mark.django_db(transaction=True)
@override_settings(
    REALTIME_WEBSOCKET_ENABLED=False,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    ALLOWED_HOSTS=["testserver"],
)
@_sync_async_test
async def test_websocket_feature_flag_closes_with_retry_later(
    websocket_identities,
) -> None:
    _, owner_key, _, _ = websocket_identities
    application = build_application()
    communicator = WebsocketCommunicator(
        application,
        "/ws/realtime/prices/",
        headers=_headers(owner_key),
    )

    assert await communicator.connect() == (False, 1013)


@pytest.mark.django_db(transaction=True)
@override_settings(
    REALTIME_WEBSOCKET_ENABLED=True,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    ALLOWED_HOSTS=["testserver"],
)
@_sync_async_test
async def test_websocket_header_auth_commands_and_reconnect_restore(
    websocket_identities,
) -> None:
    _, owner_key, _, _ = websocket_identities
    application = build_application()
    communicator = WebsocketCommunicator(
        application,
        "/ws/realtime/prices/",
        headers=_headers(owner_key),
    )
    assert (await communicator.connect())[0] is True
    assert await communicator.receive_json_from() == {
        "type": "connection.ready",
        "subscriptions": [],
    }

    await communicator.send_json_to(
        {
            "action": "subscribe",
            "request_id": "req-1",
            "asset_codes": [" 510300.sh ", "510300.SH", "000001.sz"],
        }
    )
    updated = await communicator.receive_json_from()
    assert updated == {
        "type": "subscription.updated",
        "request_id": "req-1",
        "subscriptions": ["000001.SZ", "510300.SH"],
    }

    await communicator.send_json_to({"action": "list", "request_id": "req-2"})
    listed = await communicator.receive_json_from()
    assert listed["request_id"] == "req-2"
    assert listed["subscriptions"] == ["000001.SZ", "510300.SH"]

    await communicator.send_json_to({"action": "ping", "request_id": "req-3"})
    assert await communicator.receive_json_from() == {
        "type": "pong",
        "request_id": "req-3",
    }
    await communicator.disconnect()

    restored = WebsocketCommunicator(
        application,
        "/ws/realtime/prices/",
        headers=_headers(owner_key),
    )
    assert (await restored.connect())[0] is True
    ready = await restored.receive_json_from()
    assert ready["subscriptions"] == ["000001.SZ", "510300.SH"]
    await restored.disconnect()


@pytest.mark.django_db(transaction=True)
@override_settings(
    REALTIME_WEBSOCKET_ENABLED=True,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    ALLOWED_HOSTS=["testserver"],
)
@_sync_async_test
async def test_websocket_session_auth_and_command_bounds(
    websocket_identities,
    websocket_session_cookie: str,
) -> None:
    owner, _, _, _ = websocket_identities
    application = build_application()
    communicator = WebsocketCommunicator(
        application,
        "/ws/realtime/prices/",
        headers=[
            (b"origin", b"http://testserver"),
            (b"cookie", f"sessionid={websocket_session_cookie}".encode("ascii")),
        ],
    )
    assert (await communicator.connect())[0] is True
    await communicator.receive_json_from()

    await communicator.send_json_to({"action": "list"})
    assert (await communicator.receive_json_from())["code"] == "request_id_required"
    await communicator.send_json_to(
        {
            "action": "subscribe",
            "request_id": "too-many",
            "asset_codes": [f"ASSET{i:03d}" for i in range(51)],
        }
    )
    assert (await communicator.receive_json_from())["code"] == "command_asset_limit"

    await database_sync_to_async(_seed_subscription_limit)(owner.id)
    await communicator.send_json_to(
        {
            "action": "subscribe",
            "request_id": "subscription-limit",
            "asset_codes": ["OVERFLOW"],
        }
    )
    assert (await communicator.receive_json_from())["code"] == "subscription_limit"

    for index in range(18):
        await communicator.send_json_to(
            {"action": "ping", "request_id": f"ping-{index}"}
        )
        assert (await communicator.receive_json_from())["type"] == "pong"
    await communicator.send_json_to({"action": "ping", "request_id": "rate-limit"})
    assert (await communicator.receive_json_from())["code"] == "rate_limited"
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@override_settings(
    REALTIME_WEBSOCKET_ENABLED=True,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    ALLOWED_HOSTS=["testserver"],
)
@_sync_async_test
async def test_websocket_asset_groups_are_isolated_between_users(
    websocket_identities,
) -> None:
    _, owner_key, _, other_key = websocket_identities
    application = build_application()
    owner_socket = WebsocketCommunicator(
        application,
        "/ws/realtime/prices/",
        headers=_headers(owner_key),
    )
    other_socket = WebsocketCommunicator(
        application,
        "/ws/realtime/prices/",
        headers=_headers(other_key),
    )
    assert (await owner_socket.connect())[0] is True
    assert (await other_socket.connect())[0] is True
    await owner_socket.receive_json_from()
    await other_socket.receive_json_from()
    await owner_socket.send_json_to(
        {"action": "subscribe", "request_id": "owner", "asset_codes": ["510300.SH"]}
    )
    await other_socket.send_json_to(
        {"action": "subscribe", "request_id": "other", "asset_codes": ["000001.SZ"]}
    )
    await owner_socket.receive_json_from()
    await other_socket.receive_json_from()

    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        "asset.510300.SH",
        {"type": "price.update", "payload": {"asset_code": "510300.SH"}},
    )
    assert (await owner_socket.receive_json_from())["type"] == "price.update"
    assert await other_socket.receive_nothing(timeout=0.05) is True
    await owner_socket.disconnect()
    await other_socket.disconnect()
