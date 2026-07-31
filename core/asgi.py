"""ASGI entry point for HTTP and authenticated realtime WebSockets."""

import os
from importlib import import_module
from typing import Any, cast

from asgiref.typing import ASGI3Application, ASGIApplication
from django.core.asgi import get_asgi_application

from core.asgi_liveness import LivenessApplication

channels_auth: Any = import_module("channels.auth")
channels_routing: Any = import_module("channels.routing")
channels_websocket_security: Any = import_module("channels.security.websocket")
AuthMiddlewareStack = channels_auth.AuthMiddlewareStack
ProtocolTypeRouter = channels_routing.ProtocolTypeRouter
URLRouter = channels_routing.URLRouter
AllowedHostsOriginValidator = channels_websocket_security.AllowedHostsOriginValidator

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")

django_asgi_app = get_asgi_application()

from apps.realtime.interface.routing import websocket_urlpatterns  # noqa: E402
from apps.realtime.interface.websocket_auth import (  # noqa: E402
    AuthorizationHeaderAuthMiddleware,
)


def build_application() -> ASGIApplication:
    """Build the ASGI router from the active environment settings."""

    return cast(
        ASGIApplication,
        ProtocolTypeRouter(
            {
                "http": LivenessApplication(cast(ASGI3Application, django_asgi_app)),
                "websocket": AllowedHostsOriginValidator(
                    AuthMiddlewareStack(
                        AuthorizationHeaderAuthMiddleware(
                            URLRouter(websocket_urlpatterns),
                        )
                    )
                ),
            }
        ),
    )


application = build_application()
