"""Django system checks for production runtime dependencies."""

from typing import Any

import redis
from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def check_realtime_channel_readiness(
    app_configs: Any,
    **kwargs: Any,
) -> list[Error]:
    """Require reachable Redis for enabled production WebSocket delivery."""

    if not settings.REALTIME_WEBSOCKET_ENABLED or settings.DEBUG:
        return []
    redis_url = str(getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return [
            Error(
                "Realtime WebSockets are enabled without REDIS_URL.",
                hint="Configure the production Redis channel layer or disable streaming.",
                id="core.E101",
            )
        ]
    try:
        redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        ).ping()
    except (redis.RedisError, OSError, ConnectionError):
        return [
            Error(
                "Realtime WebSocket Redis is unreachable.",
                hint="Verify REDIS_URL and Redis network readiness before deployment.",
                id="core.E102",
            )
        ]
    return []
