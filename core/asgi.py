"""ASGI entry point for HTTP and authenticated realtime WebSockets."""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")

django_asgi_app = get_asgi_application()

from apps.realtime.interface.routing import websocket_urlpatterns  # noqa: E402
from apps.realtime.interface.websocket_auth import (  # noqa: E402
    AuthorizationHeaderAuthMiddleware,
)


def build_application() -> ProtocolTypeRouter:
    """Build the ASGI router from the active environment settings."""

    return ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            "websocket": AllowedHostsOriginValidator(
                AuthMiddlewareStack(
                    AuthorizationHeaderAuthMiddleware(
                        URLRouter(websocket_urlpatterns),
                    )
                )
            ),
        }
    )


application = build_application()
