"""OpenAPI authentication extensions for Account-owned identities."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class TerminalInternalAuthenticationScheme(OpenApiAuthenticationExtension):
    """Document the signed internal identity headers used by MCP/Terminal calls."""

    target_class = "apps.account.interface.authentication.TerminalInternalAuthentication"
    name = "agomInternalSignature"

    def get_security_definition(self, auto_schema):
        """Return the OpenAPI security scheme for internal signed requests."""

        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-Agom-Internal-Signature",
            "description": (
                "HMAC-SHA256 internal signature. Signed calls must also provide "
                "X-Agom-Internal-Timestamp, X-Agom-Internal-User-Id, and may "
                "provide X-Agom-Internal-Username."
            ),
        }
