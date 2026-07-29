"""OpenAPI authentication extensions for audit ingest APIs."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:

    class OpenApiAuthenticationExtension:
        """Typed projection of drf-spectacular's runtime extension base."""

        target_class: str
        name: str

else:
    OpenApiAuthenticationExtension = import_module(
        "drf_spectacular.extensions"
    ).OpenApiAuthenticationExtension


class AuditIngestTokenAuthenticationScheme(OpenApiAuthenticationExtension):
    """Give audit-ingest token authentication a non-colliding scheme name."""

    target_class = "apps.audit.interface.authentication.AuditIngestTokenAuthentication"
    name = "auditIngestTokenAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        """Return the token header definition used by remote MCP clients."""

        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Agom user access token using the `Token <value>` format.",
        }
