"""OpenAPI authentication extensions for audit ingest APIs."""

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


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
