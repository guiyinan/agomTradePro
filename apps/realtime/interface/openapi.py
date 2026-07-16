"""OpenAPI authentication extensions for realtime APIs."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class RealtimeTokenAuthenticationScheme(OpenApiAuthenticationExtension):
    """Give the realtime token authenticator a stable, non-colliding scheme."""

    target_class = "apps.realtime.interface.authentication.RealtimeTokenAuthentication"
    name = "realtimeTokenAuth"

    def get_security_definition(self, auto_schema):
        """Return the formal token header definition."""

        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Agom access token using the `Token <value>` authorization format.",
        }
