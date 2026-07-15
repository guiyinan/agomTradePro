"""Production readiness checks for realtime channel delivery."""

from unittest.mock import Mock, patch

from django.test import override_settings

from core.checks import check_realtime_channel_readiness


@override_settings(REALTIME_WEBSOCKET_ENABLED=False, DEBUG=False, REDIS_URL="")
def test_realtime_readiness_ignores_disabled_streaming() -> None:
    assert check_realtime_channel_readiness(None) == []


@override_settings(REALTIME_WEBSOCKET_ENABLED=True, DEBUG=False, REDIS_URL="")
def test_realtime_readiness_requires_redis_when_enabled() -> None:
    errors = check_realtime_channel_readiness(None)

    assert [error.id for error in errors] == ["core.E101"]


@override_settings(
    REALTIME_WEBSOCKET_ENABLED=True,
    DEBUG=False,
    REDIS_URL="redis://redis:6379/1",
)
def test_realtime_readiness_reports_unreachable_redis() -> None:
    with patch("core.checks.redis.Redis.from_url") as from_url:
        from_url.return_value.ping.side_effect = ConnectionError("offline")
        errors = check_realtime_channel_readiness(None)

    assert [error.id for error in errors] == ["core.E102"]


@override_settings(
    REALTIME_WEBSOCKET_ENABLED=True,
    DEBUG=False,
    REDIS_URL="redis://redis:6379/1",
)
def test_realtime_readiness_accepts_reachable_redis() -> None:
    redis_client = Mock()
    redis_client.ping.return_value = True
    with patch("core.checks.redis.Redis.from_url", return_value=redis_client):
        assert check_realtime_channel_readiness(None) == []
