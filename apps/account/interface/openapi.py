"""OpenAPI authentication extensions for Account-owned identities."""

from importlib import import_module
from typing import TYPE_CHECKING

from drf_spectacular.openapi import AutoSchema

if TYPE_CHECKING:

    class OpenApiAuthenticationExtension:
        """Typed projection of drf-spectacular's runtime extension base."""

        target_class: str
        name: str

else:
    OpenApiAuthenticationExtension = import_module(
        "drf_spectacular.extensions"
    ).OpenApiAuthenticationExtension


class TerminalInternalAuthenticationScheme(OpenApiAuthenticationExtension):
    """Document the signed internal identity headers used by MCP/Terminal calls."""

    target_class = "apps.account.interface.authentication.TerminalInternalAuthentication"
    name = "agomInternalSignature"

    def get_security_definition(self, auto_schema: AutoSchema) -> dict[str, str]:
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
